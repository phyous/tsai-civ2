"""Bounded original city-unit activation; pure evidence, never game inputs.

Opt-in stack metadata and a fresh city checkpoint are required. An activation
intent authorizes inspecting that unit's popup, selecting the exact original
activate-and-close option, and checking a new native observation afterward.
"""
from copy import deepcopy
import hashlib
import json
import re

from .revision import observation_digest,prefixed_revision


class UnitActivationError(ValueError):pass


CALIBRATION='classic640-units-present-single-row-1-5-v1'
ACTIVATE='Activate Unit and Close City Screen.'
IDENTITY=('id','owner','type_id','x','y','veteran','hp_lost','movement_thirds_spent',
          'order_id','home_city_id','counter_or_commodity','waiting','goto')


def _signature(unit):
    if any(k not in unit for k in IDENTITY):raise UnitActivationError('Incomplete observed unit identity')
    return {k:deepcopy(unit[k]) for k in IDENTITY}


def _alive(unit,rules):
    specs=[s for s in rules.get('units',[]) if s.get('id')==unit.get('type_id')]
    if len(specs)!=1:return False
    maximum=specs[0].get('max_hp');lost=unit.get('hp_lost')
    return (type(maximum) is int and maximum>0 and type(lost) is int and 0<=lost<maximum
            and ('hp' not in unit or type(unit['hp']) is int and unit['hp']>0))


def _stack(state,city):
    units=[u for u in state.get('units',[]) if (u.get('x'),u.get('y'))==(city['x'],city['y'])]
    if not units or any(u.get('owner')!=city['owner'] for u in units):return None
    if any((u.get('x'),u.get('y'))==(city['x'],city['y'])
           for u in state.get('visible_units',[]) if u.get('owner')!=city['owner']):return None
    ids=[u.get('id') for u in units]
    if any(type(i) is not int or i<0 for i in ids) or len(set(ids))!=len(ids):return None
    stacks=[s for s in state.get('owned_unit_stacks',[]) if (s.get('x'),s.get('y'))==(city['x'],city['y'])]
    if len(stacks)!=1:return None
    stack=stacks[0];order=stack.get('unit_ids');links=stack.get('links')
    if (set(stack)!={'x','y','unit_ids','links'} or not isinstance(order,list)
            or any(type(i) is not int for i in order) or len(order)!=len(ids) or set(order)!=set(ids)
            or not isinstance(links,list) or len(links)!=len(order)):return None
    expected=[dict(id=i,previous=order[n-1] if n else None,
                   next=order[n+1] if n+1<len(order) else None) for n,i in enumerate(order)]
    if links!=expected:return None
    return deepcopy(stack),{u['id']:u for u in units}


def _anchor(observation,text,center):
    matches=[(i,r) for i,r in enumerate(observation.get('lines',[]))
             if r.get('text','').casefold().replace(' ','')==text]
    if len(matches)!=1:return None
    index,row=matches[0];point=row.get('center');bounds=row.get('bounds')
    if (not isinstance(point,list) or len(point)!=2 or any(type(v) is not int for v in point)
            or abs(point[0]-center[0])>12 or abs(point[1]-center[1])>6
            or not isinstance(bounds,list) or len(bounds)!=4 or any(type(v) is not int for v in bounds)
            or not 0<bounds[2]<150 or not 0<bounds[3]<24 or row.get('confidence',0)<.8):return None
    return dict(source_line=index,text=row['text'],center=point,bounds=bounds)


def activation_candidates(state,observation,rules,reviewed=None,*,ready=False):
    """Return only exact fortified-unit intents in the calibrated city layout.

``ready`` must describe a completed current checkpoint/city reopening, not an
assumption that an older roster remained unchanged. The runner owns that proof.
"""
    if ready is not True or not state.get('owned_unit_stacks'):return {}
    from .city_controls import _context
    from .dialogs import classify_dialog
    if (observation.get('width'),observation.get('height'))!=(640,480):return {}
    selected=state.get('selected_unit_id')
    if selected is not None:
        active=[u for u in state.get('units',[]) if u.get('id')==selected and u.get('owner')==state['player']['id']]
        if len(active)!=1 or not _alive(active[0],rules):return {}
    screen=classify_dialog(observation,state=state,rules=rules)
    if screen.get('kind')!='city_screen' or not screen.get('supported'):return {}
    _,city,binding,_=_context(state,screen,reviewed,rules)
    found=_stack(state,city)
    if not found:return {}
    stack,units=found
    if not all(_alive(u,rules) for u in units.values()):return {}
    # Multirow city layouts remove headings and reposition icons. They are
    # deliberately unavailable until separately calibrated and enabled.
    # 3950 calibration frames26/29/31 bind the second icon to native unit6;
    # original008 frame279 shows the same five-cell row (48px spacing).
    # The separate Supported pane may wrap and lose its own heading.
    if not 1<=len(units)<=5:return {}
    anchors={'unitspresent':_anchor(observation,'unitspresent',(315,283))}
    if not all(anchors.values()):return {}
    tribe=state['player'].get('tribe_id')
    leaders=[x for x in rules.get('leaders',[]) if x.get('id')==tribe]
    if len(leaders)!=1 or not isinstance(leaders[0].get('adjective'),str):return {}
    actions={}
    for slot,identifier in enumerate(stack['unit_ids']):
        unit=units[identifier]
        if unit.get('order_id')!=2 or unit.get('veteran') is not False:continue
        specs=[s for s in rules.get('units',[]) if s.get('id')==unit.get('type_id')]
        homes=[c for c in state.get('cities',[]) if c.get('id')==unit.get('home_city_id') and c.get('owner')==city['owner']]
        if len(specs)!=1 or len(homes)!=1 or specs[0].get('domain')!=0:continue
        try:identity=_signature(unit);roster=[_signature(units[i]) for i in stack['unit_ids']]
        except UnitActivationError:continue
        name=specs[0].get('name')
        if not isinstance(name,str) or not name:continue
        action_id='activate_city_unit_'+str(identifier)
        actions[action_id]=dict(id=action_id,kind='unit_activation',
            label=f"Activate fortified {name} unit {identifier} in {city['name']} and close the city; no movement order",
            actor=dict(kind='unit',**identity),preconditions={**binding,
                'city':deepcopy(city),'unit_roster':roster,'stack':stack,
                'expected_unit_text':leaders[0]['adjective']+' '+name,'expected_home_text':'Home City: '+homes[0]['name'],
                'grid_calibration':CALIBRATION,'grid_anchors':deepcopy(anchors)},
            parameters=dict(control='units_present',slot=slot,center=[216+48*slot,310],
                expected_screen='unit_information',continuation=ACTIVATE,
                native_checkpoint_required=True,movement_authorized=False))
    return actions


def validate_activation(action,state,observation,rules,reviewed=None,*,ready=False):
    if (not isinstance(action,dict) or set(action)!={'id','kind','label','actor','preconditions','parameters'}
            or activation_candidates(state,observation,rules,reviewed,ready=ready).get(action.get('id'))!=action):
        raise UnitActivationError('Activation differs from its bound city, unit, stack or image')


def activation_popup(action,observation,game_text,labels_text):
    """Validate the original pending-intent popup and return observed controls.

This is not a general unit-menu action space. No disband, fortify, sleep or
clear-orders input is authorized by this receipt.
"""
    from .dialogs import dialog_resources,_rows,DialogObservationError
    if action.get('kind')!='unit_activation' or action.get('parameters',{}).get('continuation')!=ACTIVATE:
        raise UnitActivationError('An actual pending activation intent is required')
    templates=[t for t in dialog_resources(game_text) if t['tag']=='UNITOPTIONS']
    if (len(templates)!=1 or templates[0]['title']!='Unit Information'
            or templates[0]['body']!='^%STRING0 ^Home City: %STRING2'
            or not isinstance(labels_text,str) or any(s not in labels_text.splitlines()
                for s in ('No changes.','Clear orders.','Sleep / Board next ship.','Activate Unit.',ACTIVATE,'OK','Cancel'))):
        raise UnitActivationError('Original activation resources differ')
    if ((observation.get('width'),observation.get('height'))!=(640,480)
            or not re.fullmatch('[a-f0-9]{64}',observation.get('sha256',''))):
        raise UnitActivationError('Invalid activation image')
    try:all_rows=_rows(observation)
    except DialogObservationError as error:raise UnitActivationError(str(error)) from None
    rows=[row for row in all_rows if 90<=row['center'][0]<=550 and 112<=row['center'][1]<=367]
    def one(text,low,high):
        found=[r for r in rows if r.get('text','').strip()==text and low<=r['center'][1]<=high]
        if len(found)!=1 or found[0].get('confidence',0)<.8:
            raise UnitActivationError('Activation popup text or control is missing/ambiguous: '+text)
        return {k:deepcopy(found[0][k]) for k in ('text','source_line','center','bounds')}
    title=one('Unit Information',116,134)
    unit=one(action['preconditions']['expected_unit_text'],140,159)
    home=one(action['preconditions']['expected_home_text'],160,181)
    one('No changes.',185,207);one('Clear orders.',210,232)
    one('Sleep / Board next ship.',235,258);one('Activate Unit.',286,307)
    option=one(ACTIVATE,311,333);ok=one('OK',342,365);cancel=one('Cancel',342,365)
    if not (ok['center'][0]<320<cancel['center'][0]):raise UnitActivationError('Original popup buttons moved')
    allowed={'Unit Information',action['preconditions']['expected_unit_text'],action['preconditions']['expected_home_text'],
             'No changes.','Clear orders.','Sleep / Board next ship.','Activate Unit.',ACTIVATE,'OK','Cancel'}
    for row in rows:
        text=row.get('text','').strip();x,y=row['center']
        if text in allowed:continue
        # The measured bitmap b/h confusion occurs only in this unchosen row;
        # it never supplies a disband action or authorizes that control.
        if text in ('Disband','Dishand') and 260<=x<=330 and 260<=y<=282:continue
        if text in ('O','0','•') and 237<=x<=253 and 185<=y<=331:continue
        if 95<=x<=220 and 140<=y<=334 and len(text)<=3 and row.get('confidence',1)<.5:continue
        raise UnitActivationError('Unexpected text overlaps the activation popup')
    source={'resource':templates[0],'labels':[ACTIVATE,'Activate Unit.','Clear orders.','OK','Cancel']}
    return dict(kind='unit_activation_continuation',source_image_sha256=observation['sha256'],
        source_sha256=hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        resource_tag='UNITOPTIONS',title=title,unit=unit,home=home,option=option,ok=ok,cancel=cancel,
        scope='Only the exact already-selected activation intent; ordinary radio click and confirmation, no other unit order')


def activation_radio_proof(action,observation,game_text,labels_text):
    """Require the chosen native radio's actual pixels before confirming it.

Calibrated original640 popup: every radio has a five-by-three central patch
at x243..247; only Activate-and-Close (y320..322) may be black. All other
centers must remain the native gray. Source-image hashing binds these samples.
"""
    from pathlib import Path
    from PIL import Image
    import io
    popup=activation_popup(action,observation,game_text,labels_text)
    path=observation.get('path')
    if not isinstance(path,str):raise UnitActivationError('Original radio image path is missing')
    data=Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest()!=observation['sha256']:
        raise UnitActivationError('Radio pixels differ from the observed image')
    with Image.open(io.BytesIO(data)) as raw:
        image=raw.convert('RGB')
        if image.size!=(640,480):raise UnitActivationError('Original radio geometry changed')
        rows=(195,220,246,271,296,321)
        for index,y in enumerate(rows):
            # The measured center uses the three pixels y-1..y+1.
            expected=(0,0,0) if index==5 else (195,195,195)
            if any(image.getpixel((x,yy))!=expected for x in range(243,248) for yy in range(y-1,y+2)):
                raise UnitActivationError('Activate-and-Close is not uniquely visibly selected')
    return dict(source_image_sha256=observation['sha256'],
        calibration='classic640-unit-options-radio-centers-v1',
        selected_label=ACTIVATE,selected_bounds=[243,320,5,3],
        unselected_bounds=[[243,y-1,5,3] for y in rows[:-1]],
        popup_source_sha256=popup['source_sha256'])


def activation_result(action,before,after):
    """Compare a fresh native checkpoint; never treat a sent click as success."""
    if action.get('kind')!='unit_activation':raise UnitActivationError('A bound activation action is required')
    actor=action['actor'];identifier=actor['id']
    old=next((u for u in before.get('units',[]) if u.get('id')==identifier),None)
    if (old is None or _signature(old)!={k:actor[k] for k in IDENTITY}
            or observation_digest(before) not in (action['preconditions'].get('save_sha256'),
                                                  action['preconditions'].get('observation_sha256'))):
        raise UnitActivationError('Activation does not bind its original unit observation')
    new=next((u for u in after.get('units',[]) if u.get('id')==identifier),None)
    old_units=[_signature(u) for u in before['units']];expected=deepcopy(old_units)
    next(u for u in expected if u['id']==identifier)['order_id']=255
    after_units=[_signature(u) for u in after['units']]
    preserved=all(before.get(k)==after.get(k) for k in set(before)|set(after)
                  if k not in ('evidence','view','selected_unit_id','units','owned_unit_stacks'))
    if preserved and after_units==expected and after.get('selected_unit_id')==identifier:status='observed_expected_change'
    elif preserved and after_units==old_units and after.get('selected_unit_id')==before.get('selected_unit_id'):status='no_observed_change'
    else:status='unexpected_change'
    return dict(status=status,unit_id=identifier,before_unit=_signature(old),after_unit=_signature(new) if new else None,
        selected_before=before.get('selected_unit_id'),selected_after=after.get('selected_unit_id'),
        **prefixed_revision(before,'before_'),**prefixed_revision(after,'after_'),
        turn=after['turn'],observation='Native order/selection comparison only; no movement or tactical outcome inferred')
