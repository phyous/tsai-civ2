"""Original selected-unit economy orders and their separate disband warning.

No input is executed here. Shift+D requests the original warning; its No/Yes
alternatives require a new model answer. H requests support transfer only from
an observed home to the unique owned city under the selected non-trade unit.
"""
from copy import deepcopy
import hashlib
import json
import re
from .revision import revision

DISBAND_SOURCE = dict(tag='DISBAND',title='Warning!',width=None,
    body='Really disband %STRING0?',options=['No','Yes'],buttons=[],listbox=False)
DISBAND_SHA256 = 'b04ffd8e70b413b571f0ea9fe088ea52baa3fab69ad56d1d75c7b049c8bffa34'
ACTOR_FIELDS = ('id','type_id','owner','x','y')
DISBAND_PARAMETERS = dict(key='KeyD',modifiers=['ShiftLeft'],opens_dialog='DISBAND')
DISBAND_SCOPE = ('The prior command opened this warning only. No and Yes require a separate genuine model choice; '
                 'only the original game can remove the unit.')
# Public numeric/name facts from the standard original 1.06 RULES.TXT, for
# replay without requiring the private game archive. Index is the native ID.
STANDARD_NAMES = ('Settlers','Engineers','Warriors','Phalanx','Archers','Legion',
    'Pikemen','Musketeers','Fanatics','Partisans','Alpine Troops','Riflemen',
    'Marines','Paratroopers','Mech. Inf.','Horsemen','Chariot','Elephant',
    'Crusaders','Knights','Dragoons','Cavalry','Armor','Catapult','Cannon',
    'Artillery','Howitzer','Fighter','Bomber','Helicopter','Stlth Ftr.',
    'Stlth Bmbr.','Trireme','Caravel','Galleon','Frigate','Ironclad','Destroyer',
    'Cruiser','AEGIS Cruiser','Battleship','Submarine','Carrier','Transport',
    'Cruise Msl.','Nuclear Msl.','Diplomat','Spy','Caravan','Freight','Explorer',
    'Extra Land','Extra Ship','Extra Air')
STANDARD_HP = (20,20,10,10,10,10,10,20,20,20,20,20,20,20,30,10,10,10,10,10,
    20,20,30,10,20,20,30,20,20,20,20,20,10,10,20,20,30,30,30,30,40,30,40,
    30,10,10,10,10,10,10,10,10,20,20)


def living(unit,spec):
    maximum=spec.get('max_hp')
    if type(maximum)is not int or maximum<=0:return False
    hp,lost=unit.get('hp'),unit.get('hp_lost')
    if 'hp' in unit and (type(hp)is not int or not 0<hp<=maximum):return False
    if 'hp_lost' in unit and (type(lost)is not int or not 0<=lost<maximum):return False
    if type(hp)is int and type(lost)is int and hp!=maximum-lost:return False
    return type(hp)is int or type(lost)is int


def owned_city(state,identifier):
    if type(identifier)is not int or identifier<0:return None
    matches=[c for c in state.get('cities',[]) if isinstance(c,dict) and c.get('id')==identifier]
    if len(matches)!=1:return None
    city=matches[0]
    if (city.get('owner')!=state.get('player',{}).get('id')
            or any(type(city.get(k))is not int for k in ('id','owner','x','y'))
            or not isinstance(city.get('name'),str) or not 1<=len(city['name'])<=60):return None
    return {k:deepcopy(city[k])for k in ('id','owner','name','x','y')}


def home_transfer(state,unit,spec):
    if not living(unit,spec) or type(spec.get('role'))is not int or not 0<=spec['role']<=6:return None
    old=owned_city(state,unit.get('home_city_id'))
    matches=[c for c in state.get('cities',[]) if isinstance(c,dict)
             and (c.get('x'),c.get('y'))==(unit.get('x'),unit.get('y'))]
    if old is None or len(matches)!=1:return None
    new=owned_city(state,matches[0].get('id'))
    if new is None or new['id']==old['id']:return None
    return dict(key='KeyH',modifiers=[],previous_home=old,new_home=new)


def request_context(action,state,decision,*,standard=False):
    """Rebuild the exact actor/revision after a recorded Shift+D dispatch."""
    if (type(decision)is not int or decision<=0 or not isinstance(action,dict)
            or action.get('id')!='request_disband' or action.get('kind')!='request_disband'
            or action.get('parameters')!=DISBAND_PARAMETERS):return None
    player=state.get('player',{}).get('id')
    if type(player)is not int or not 1<=player<=7:return None
    actor=action.get('actor',{});pre=action.get('preconditions',{})
    if set(actor)!=set(ACTOR_FIELDS) or any(type(actor.get(k))is not int for k in ACTOR_FIELDS):return None
    matches=[u for u in state.get('units',[]) if u.get('id')==actor['id']]
    if (len(matches)!=1 or any(matches[0].get(k)!=actor[k] for k in ACTOR_FIELDS)
            or actor['id']!=state.get('selected_unit_id') or actor['owner']!=state.get('player',{}).get('id')
            or pre.get('selected_unit_id')!=actor['id']):return None
    unit=matches[0];spec=unit.get('specification',{});name=unit.get('type')
    if standard:
        index=actor['type_id']
        if not 0<=index<len(STANDARD_NAMES):return None
        spec={'max_hp':STANDARD_HP[index]};name=STANDARD_NAMES[index]
    if not living(unit,spec) or not isinstance(name,str) or not 1<=len(name)<=60:return None
    try:bound=revision(state)
    except ValueError:return None
    if any(pre.get(k)!=v for k,v in bound.items()):return None
    if any(pre.get(k)!=unit.get(k) for k in ('movement_thirds_spent','order_id')):return None
    return dict(decision=decision,actor=deepcopy(actor),revision=bound,unit_name=name)


def valid_context(state,pending):
    if not isinstance(pending,dict) or set(pending)!={'decision','actor','revision','unit_name'}:return False
    actor=pending.get('actor',{})
    matches=[u for u in state.get('units',[]) if u.get('id')==actor.get('id')]
    if len(matches)!=1:return False
    unit=matches[0]
    action=dict(id='request_disband',kind='request_disband',actor=actor,
        parameters=DISBAND_PARAMETERS,preconditions={**pending.get('revision',{}),
        'selected_unit_id':actor.get('id'),**{k:unit.get(k)for k in ('movement_thirds_spent','order_id')}})
    return request_context(action,state,pending.get('decision'))==pending


def _normal(text):return ' '.join(text.casefold().split())
def _radio(text):return re.sub(r'^(?:O|[○●•])\s+','',text)


def classify_disband(observation,rows,resources,state):
    pending=state.get('pending_disband') if isinstance(state,dict) else None
    if (not isinstance(state,dict) or not valid_context(state,pending)
            or (observation.get('width'),observation.get('height'))!=(640,480)
            or not re.fullmatch('[a-f0-9]{64}',str(observation.get('sha256','')))
            or observation.get('ocr',{}).get('conflicts')
            or [r for r in resources if r.get('tag')=='DISBAND']!=[DISBAND_SOURCE]):return None
    titles=[r for r in rows if _normal(r['text'])=='warning!']
    oks=[r for r in rows if _normal(r['text'])=='ok']
    if len(titles)!=1 or len(oks)!=1:return None
    title,ok=titles[0],oks[0];cx,cy=title['center']
    if not 280<=cx<=360 or not 90<=cy<=300 or abs(ok['center'][0]-cx)>12 or not 75<=ok['center'][1]-cy<=190:return None
    panel=[r for r in rows if r not in (title,ok) and cy<r['center'][1]<ok['center'][1] and abs(r['center'][0]-cx)<=230]
    panel.sort(key=lambda r:(r['bounds'][1],r['bounds'][0]))
    if len(panel)!=3 or any(r['confidence']<.8 for r in [title,*panel,ok]):return None
    body,no,yes=panel
    if (_normal(body['text'])!=_normal('Really disband '+pending['unit_name']+'?')
            or [_radio(r['text'])for r in (no,yes)]!=['No','Yes']
            or not 16<=yes['center'][1]-no['center'][1]<=35
            or abs(no['bounds'][0]-yes['bounds'][0])>24
            or no['bounds'][1]<body['bounds'][1]+body['bounds'][3]+4
            or ok['bounds'][1]<yes['bounds'][1]+yes['bounds'][3]+6
            or any(abs(r['center'][0]-cx)>230 for r in (body,no,yes))):return None
    selected=[title,*panel,ok]
    if any(r not in selected and _normal(_radio(r['text'])) in ('no','yes','ok','cancel','help','warning!')for r in rows):return None
    def control(row,kind):return {k:deepcopy(row[k])for k in ('text','center','source_line','confidence')}|{'control':kind,'enabled':None}
    proof=dict(request=deepcopy(pending),resource_sha256=DISBAND_SHA256,
        source_image_sha256=observation['sha256'],observed_body=body['text'],
        scope=DISBAND_SCOPE)
    return dict(kind='disband_confirmation',title=title['text'],resource_tag='DISBAND',
        options=[control(no,'option'),control(yes,'option')],buttons=[control(ok,'button')],
        evidence={'disband_confirmation':proof})


def recover_disband_warning(image,rows,executable,directory,evidence):
    """Measured warning-row locators only; every replacement needs two reads."""
    from .observe import _crop_text,_same_location,_replace_crop_row
    if image.size!=(640,480):return
    titles=[r for r in rows if r['text'] in ('Warning!','Warring!') and r['confidence']>=.8]
    oks=[r for r in rows if r['text'] in ('OK','Cancel','Help')]
    if len(titles)!=1 or len(oks)!=1 or oks[0]['text']!='OK':return
    title,ok=titles[0],oks[0];cx,cy=title['center']
    if not 308<=cx<=332 or not 172<=cy<=196 or not 280<=ok['center'][1]<=306:return
    panel=sorted([r for r in rows if cy<r['center'][1]<ok['center'][1] and abs(r['center'][0]-cx)<=230],key=lambda r:r['center'][1])
    if len(panel)!=3 or min(panel[0]['confidence'],ok['confidence'])<.8 or min(panel[1]['confidence'],panel[2]['confidence'])<.3:return
    body,no,yes=panel
    match=re.fullmatch(r'Really dis[bh]and ([A-Za-z][A-Za-z. ]{0,59})\?',body['text'])
    def label(text):return re.sub(r'^(?:\)|O|[○●•])\s*','',text)
    if (not match or [label(no['text']),label(yes['text'])]!=['No','Yes']
            or not 16<=yes['center'][1]-no['center'][1]<=35
            or abs(no['bounds'][0]-yes['bounds'][0])>24
            or not cy<body['center'][1]<no['center'][1]<yes['center'][1]<ok['center'][1]):return
    wanted=[(title,'Warning!',2,'title'),(body,'Really disband '+match[1]+'?',3,'body'),
            (no,'No',2,'no'),(yes,'Yes',2,'yes')]
    tasks=[]
    for old,text,scale,name in wanted:
        if old['text']==text:continue
        a=_crop_text(image,old,'disband_'+name+'_rgb'+str(scale),executable,directory,evidence,padding=(3,3),scale=scale)
        b=_crop_text(image,old,'disband_'+name+'_gray'+str(scale),executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=text or b[0]['text']!=text
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        tasks.append((rows.index(old),a,b))
    resolved=[]
    for index,a,b in tasks:
        old=rows[index]
        if a[0]['text'] in ('No','Yes'):
            for conflict in evidence.get('conflicts',[]):
                box=conflict.get('bounds')
                if (conflict.get('text')!=a[0]['text'] or conflict.get('reason')!='contradictory overlapping native text'
                        or not isinstance(box,list) or len(box)!=4 or any(type(v)is not int for v in box)
                        or box[2]<=0 or box[3]<=0):continue
                other={'bounds':box,'center':[round(box[0]+box[2]/2),round(box[1]+box[3]/2)]}
                if _same_location(old,other) and _same_location(a[0],other):resolved.append(conflict)
        if _replace_crop_row(rows,index,a,lambda old,new:True):rows[index]['provenance']+=b[0]['provenance']
    if resolved:
        evidence.setdefault('resolved_control_conflicts',[]).extend(deepcopy(resolved))
        evidence['conflicts']=[c for c in evidence['conflicts'] if c not in resolved]
