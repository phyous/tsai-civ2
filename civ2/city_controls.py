"""Model-selected native city controls, with no inputs or inferred purchases.

city_control_candidates(state, screen, reviewed=None, rules=None) -> actions
city_control_request_for(state, screen, actions=None, reviewed=None,
                         rules=None, recent_actions=None) -> request
validate_city_control(action, state, screen, reviewed=None, rules=None)

Reviewed controls belong to {city_id, city_name, year_raw, actions}. Record a
review only after its native transaction completes. A newly founded city absent
from the save needs a fresh checkpoint before this module can bind its actor.
"""
from copy import deepcopy
import math
import re

from .city import CityLaborError, WORKED_BITS, city_labor_projection
from .dialogs import classify_dialog
from .policy import PolicyError, STRATEGY_QUESTION, _revision, model_state


class CityControlError(ValueError):
    pass


class ForcedCityControl(CityControlError):
    """Only observed Exit remains; do not fabricate a singleton Jev vector."""


CONTROLS = {
    'change_production': ('change', 'Change production: open the native choices', 'production_choice'),
    'open_buy_quote': ('buy', 'Buy: open the native quote only; no purchase authorized', 'buy_quote'),
    'exit_city': ('exit', 'Exit this city window', 'original_map'),
}
REVIEWABLE = {'change_production', 'open_buy_quote'}
# Every non-center slot was individually clicked and read back through an
# original native save in labor-calibration-01. No center or specialist-type tap.
LABOR_POINTS = {slot:(104+24*dx,192+12*dy)
                for slot,(_,_,dx,dy) in enumerate(WORKED_BITS) if slot != 16}
LABOR_CALIBRATION = 'classic640-labor-grid-20-native-save-v1'



def _name(value):
    return ' '.join(value.casefold().split())


def _context(state, screen, reviewed, rules):
    try:
        revision = _revision(state)
    except PolicyError as error:
        raise CityControlError(str(error)) from None
    if not isinstance(screen, dict):
        raise CityControlError('An observed city screen is required')
    if 'lines' in screen:
        screen = classify_dialog(screen, state=state, rules=rules)
    if screen.get('supported') is not True or screen.get('kind') != 'city_screen':
        raise CityControlError('Only a complete supported native city screen enables city controls')
    title = screen.get('title')
    match = re.match(r'^City of (.+?),\s*(\d{1,5})\s*(B\.?\s*C\.?|A\.?\s*D\.?)\b',
                     title, re.I) if isinstance(title, str) else None
    if not match:
        raise CityControlError('The native city name and displayed year must be readable')
    year = int(match[2]) * (-1 if match[3][0].casefold() == 'b' else 1)
    if type(state.get('year_raw')) is not int or state['year_raw'] != year:
        raise CityControlError('Displayed city year differs from the bound native save')
    player = state.get('player', {}).get('id')
    if type(player) is not int or not 1 <= player <= 7:
        raise CityControlError('Observed human owner is required')
    cities = state.get('cities')
    if not isinstance(cities, list):
        raise CityControlError('An owned-city roster is required')
    name = screen.get('observed_city_name', match[1])
    if not isinstance(name, str):
        raise CityControlError('Observed city name is invalid')
    recovery = screen.get('city_name_recovery')
    if _name(name) != _name(match[1]):
        if (not isinstance(recovery, dict) or recovery.get('ocr_text') != match[1]
                or recovery.get('canonical_name') != name
                or recovery.get('save_sha256') != revision['save_sha256']
                or recovery.get('source') != 'Unique one-edit match to owned city in original save'
                or type(recovery.get('source_line')) is not int or recovery['source_line'] < 0):
            raise CityControlError('Recovered city name lacks original OCR/save provenance')
    matches = [city for city in cities if isinstance(city, dict)
               and isinstance(city.get('name'), str) and _name(city['name']) == _name(name)]
    if len(matches) != 1 or matches[0].get('owner') != player:
        raise CityControlError('Displayed city must uniquely match an owned city in the save')
    city = matches[0]
    if _name(name) != _name(match[1]) and recovery.get('city_id') != city['id']:
        raise CityControlError('Recovered city name belongs to a different saved actor')
    if (any(type(city.get(k)) is not int or city[k] < 0 for k in ('id', 'x', 'y'))
            or sum(c.get('id') == city['id'] for c in cities if isinstance(c, dict)) != 1):
        raise CityControlError('Owned city actor is incomplete or ambiguous')
    actor = {'kind':'city', **{k:deepcopy(city[k]) for k in ('id','owner','name','x','y')}}
    digest = screen.get('sha256')
    if not isinstance(digest, str) or re.fullmatch('[a-f0-9]{64}', digest) is None:
        raise CityControlError('Exact original city image SHA is required')
    if any(type(screen.get(k)) is not int or not 1 <= screen[k] <= 4096 for k in ('width','height')):
        raise CityControlError('Invalid native image dimensions')
    seen = set()
    if reviewed is not None:
        if (not isinstance(reviewed, dict) or set(reviewed) not in ({'city_id','city_name','year_raw','actions'}, {'city_id','city_name','year_raw','actions','labor_reassignments'})
                or type(reviewed['city_id']) is not int or reviewed['city_id'] != city['id']
                or reviewed['city_name'] != city['name']
                or type(reviewed['year_raw']) is not int or reviewed['year_raw'] != year
                or not isinstance(reviewed['actions'], (list, tuple, set, frozenset))
                or any(not isinstance(a, str) or a not in REVIEWABLE for a in reviewed['actions'])
                or type(reviewed.get('labor_reassignments',0)) is not int
                or not 0 <= reviewed.get('labor_reassignments',0) <= 40):
            raise CityControlError('Reviewed controls must belong to this owned city and displayed year')
        seen = set(reviewed['actions'])
    binding={**revision, 'image_sha256':digest,
        'width':screen['width'], 'height':screen['height'], 'screen_kind':'city_screen',
        'observed_city_title':title, 'year_raw':year, 'reviewed_action_ids':sorted(seen)}
    if _name(name)!=_name(match[1]):
        binding.update(observed_city_name=name,city_name_recovery=deepcopy(recovery))
    return screen, actor, binding, seen



def labor_allowance(state, city_id, reviewed=None):
    city = next((c for c in state.get('cities',[]) if c.get('id')==city_id), {})
    size = city.get('size')
    limit = min(40,2*size) if type(size) is int and size>0 else 0
    used = reviewed.get('labor_reassignments',0) if reviewed else 0
    return {'used':used,'limit':limit,'remaining':max(0,limit-used),
            'scope':'Per city and displayed year; dispatched labor inputs count even if no change is observed. Budget-omitted actions are not claimed illegal.'}


def _labor_anchors(screen):
    if (screen.get('width'),screen.get('height')) != (640,480):return False
    evidence=screen.get('evidence')
    anchors=evidence.get('city_resource_map',{}) if isinstance(evidence,dict) else {}
    if not isinstance(anchors,dict):return False
    for name,target in (('resource_map',(104,255)),('citizens',(103,112))):
        item=anchors.get(name,{})
        if not isinstance(item,dict):return False
        point=item.get('center');bounds=item.get('bounds')
        if (not isinstance(point,(list,tuple)) or len(point)!=2
                or any(type(v) is not int for v in point)
                or max(abs(point[i]-target[i]) for i in (0,1))>7
                or not isinstance(bounds,(list,tuple)) or len(bounds)!=4
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds)
                or not 0 < bounds[2] < 150 or not 0 < bounds[3] < 24
                or type(item.get('source_line')) is not int or item['source_line']<0):return False
    return True


def _labor_candidates(state,screen,actor,binding,reviewed,rules):
    if not _labor_anchors(screen):return {}
    allowance=labor_allowance(state,actor['id'],reviewed)
    if not allowance['remaining']:return {}
    try: labor=city_labor_projection(state,actor['id'],rules)
    except CityLaborError:return {}
    if labor['warnings'] or not labor['labor_balance']['consistent'] or not labor['specialists']['type_counts_complete']:
        return {}
    specialists=labor['specialists']['stored_type_counts']
    # Mixed specialist consumption order has not been calibrated in native UI.
    if specialists.get('taxman',0) or specialists.get('scientist',0):return {}
    occupied=set();assign_ok=True
    for city in state.get('cities',[]):
        if city['id']==actor['id']:continue
        try:other=city_labor_projection(state,city['id'],rules)
        except CityLaborError:assign_ok=False;continue
        occupied.update((c['position']['x'],c['position']['y']) for c in other['worked_positions'] if c['position'])
    occupied.update((u.get('x'),u.get('y')) for u in state.get('visible_units',[]) if u.get('owner')!=actor['owner'])
    occupied.update((c.get('x'),c.get('y')) for c in state.get('known_cities',[]))
    before={'worked_tiles_bits':labor['worked_tiles_bits'],'specialist_count':labor['specialists']['count'],
            'specialists':specialists,'size':labor['city']['size']}
    actions={}
    for cell in labor['city_radius']:
        slot=cell['slot'];point=cell['position']
        if slot not in LABOR_POINTS or cell['is_center'] or cell['knowledge']!='explored' or not point:continue
        if cell['worked']:mode='remove_worker';verb='Remove worker from';suffix=' to create one entertainer'
        elif (assign_ok and specialists.get('entertainer',0)>0 and (point['x'],point['y']) not in occupied):
            mode='assign_entertainer';verb='Assign one entertainer to';suffix=''
        else:continue
        identifier=f'labor_{mode}_{slot}'
        label=f"{verb} {cell['terrain']['name']} at ({point['x']},{point['y']}){suffix}"
        actions[identifier]=dict(id=identifier,kind='city_labor',label=label,actor=deepcopy(actor),
            preconditions={**deepcopy(binding),'labor_before':deepcopy(before),
                           'labor_review_used':allowance['used'],'labor_review_limit':allowance['limit'],
                           'labor_calibration':LABOR_CALIBRATION},
            parameters=dict(control='resource_map',center=list(LABOR_POINTS[slot]),slot=slot,
                position=deepcopy(point),mode=mode,source_byte=cell['source_byte'],source_bit=cell['source_bit'],
                only_open_menu=False,purchase_authorized=False,expected_screen='city_screen',
                native_checkpoint_required=True,city_center_immutable=True))
    return actions


def city_labor_result(action,before,after):
    """Compare native labor facts after one issued click; never assume success."""
    if not isinstance(action,dict) or action.get('kind')!='city_labor':raise CityControlError('A bound labor action is required')
    actor=action['actor'];a=city_labor_projection(before,actor['id']);b=city_labor_projection(after,actor['id'])
    signature=('id','owner','name','x','y','size')
    if (any(a['city'][k]!=b['city'][k] for k in signature)
            or any(a['city'][k]!=actor[k] for k in ('id','owner','name','x','y'))
            or before['turn']!=after['turn'] or before['year_raw']!=after['year_raw']
            or action['preconditions']['save_sha256']!=before['evidence']['save_sha256']):
        raise CityControlError('Labor checkpoint changed city identity or turn')
    def values(p):return {'worked_tiles_bits':p['worked_tiles_bits'],
        'specialist_count':p['specialists']['count'],
        'specialists':{k:v for k,v in p['specialists']['stored_type_counts'].items() if v},'size':p['city']['size']}
    old,new=values(a),values(b);bound=deepcopy(action['preconditions']['labor_before'])
    bound['specialists']={k:v for k,v in bound['specialists'].items() if v}
    if old!=bound:raise CityControlError('Labor action does not bind the prior native bitmap')
    expected=deepcopy(old);slot=action['parameters']['slot']
    if slot not in LABOR_POINTS:raise CityControlError('The immutable center is not a labor action')
    byte,bit,_,_=WORKED_BITS[slot];mode=action['parameters']['mode']
    if mode=='remove_worker' and old['worked_tiles_bits'][byte]&(1<<bit):delta=1
    elif mode=='assign_entertainer' and not old['worked_tiles_bits'][byte]&(1<<bit) and old['specialists'].get('entertainer',0)>0:delta=-1
    else:raise CityControlError('Labor action has invalid original worker preconditions')
    expected['worked_tiles_bits'][byte]^=1<<bit
    expected['specialist_count']+=delta
    expected['specialists']['entertainer']=expected['specialists'].get('entertainer',0)+delta
    expected['specialists']={k:v for k,v in expected['specialists'].items() if v}
    status='observed_expected_change' if new==expected else 'no_observed_change' if new==old else 'unexpected_change'
    return dict(status=status,before=old,expected=expected,after=new,
        before_save_sha256=before['evidence']['save_sha256'],after_save_sha256=after['evidence']['save_sha256'],
        turn=after['turn'],city=deepcopy(b['city']),
        observation='Actual native save comparison after the labor input; city yields and wider pending decisions are not attributed to this click.')


def city_control_candidates(state, screen, reviewed=None, rules=None, *, labor_ready=False):
    screen, actor, binding, seen = _context(state, screen, reviewed, rules)
    buttons = screen.get('buttons')
    if not isinstance(buttons, list) or not 1 <= len(buttons) <= 64:
        raise CityControlError('A bounded observed city-button list is required')
    observed, centers = {}, set()
    for index, button in enumerate(buttons):
        if not isinstance(button, dict) or not isinstance(button.get('text'), str):
            raise CityControlError('Malformed observed city button')
        label = _name(button['text']); center = button.get('center')
        if (not label or len(button['text']) > 100 or not isinstance(center, (list, tuple))
                or len(center) != 2 or any(type(v) is not int for v in center)
                or not 0 <= center[0] < screen['width'] or not 0 <= center[1] < screen['height']
                or label in observed or tuple(center) in centers):
            raise CityControlError('City button labels or image-bound centers are ambiguous')
        confidence = button.get('confidence', 1.)
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise CityControlError('Malformed city-button confidence')
        observed[label] = (index, button, confidence)
        centers.add(tuple(center))
    actions = {}
    for identifier, (native, label, next_screen) in CONTROLS.items():
        if identifier in seen or native not in observed:
            continue
        index, button, confidence = observed[native]
        if button.get('enabled') is False or confidence < .8:
            continue
        actions[identifier] = dict(id=identifier, kind='city_control', label=label,
            actor=deepcopy(actor), preconditions=deepcopy(binding), parameters=dict(
                center=list(button['center']), observed_text=button['text'], button_index=index,
                control='button', only_open_menu=identifier!='exit_city',
                expected_screen=next_screen, purchase_authorized=False,
                confirmation_requires_separate_choice=identifier=='open_buy_quote'))
    if labor_ready:
        actions.update(_labor_candidates(state,screen,actor,binding,reviewed,rules))
    if 'exit_city' not in actions:
        raise CityControlError('A unique observed Exit must remain available')
    return actions


def city_control_request_for(state, screen, actions=None, reviewed=None, rules=None, recent_actions=None, *, labor_ready=False):
    expected = city_control_candidates(state, screen, reviewed, rules, labor_ready=labor_ready)
    if actions is None:
        actions = expected
    if actions != expected:
        raise CityControlError('City controls differ from the bound native observation')
    if len(actions) < 2:
        raise ForcedCityControl('Only Exit remains; record native housekeeping without a fabricated model vector')
    projection = model_state(state, rules, recent_actions)
    binding = actions['exit_city']['preconditions']
    projection['city_control_review'] = dict(actor=deepcopy(actions['exit_city']['actor']),
        observed_title=binding['observed_city_title'], year_raw=binding['year_raw'],
        reviewed_action_ids=binding['reviewed_action_ids'],
        labor_review=labor_allowance(state,actions['exit_city']['actor']['id'],reviewed),
        labor_checkpoint_ready=labor_ready,
        controls={identifier:action['label'] for identifier,action in actions.items()},
        scope='City statistics come from the bound native save; buttons come from this current original city image. Change only opens production choices. Buy only opens a native quote. Its actual price and purchase confirmation require a new observation and a separate Jev choice. No purchase or price is inferred. Labor choices use the calibrated native Resource Map: remove one worker into an entertainer or assign one entertainer to an observed unworked tile. The city center cannot be changed. Each click requires a new native save comparison before another labor choice; no yield gain is assumed.',
        review_policy='Omit a control only after its native review finishes for this same city/year. Exit remains available; useful review does not require visiting every control.')
    return dict(state=projection, questions={
        'city_action':dict(type='choice', instructions='Choose one actual native control for this owned city. Consider current production, growth, happiness, available treasury and the wider empire. Review production when useful, request a purchase quote only when worth examining, or exit when finished. Consider food, shields, trade and happiness before a labor reassignment; original base tile yields are not actual forecasts. Avoid undoing recent labor choices without a reason. Labor review has an explicit per-city/year input budget; budget omission does not mean the native action is illegal. This answer authorizes only the selected control, never a purchase. empire_strategy is independent advice, not a previous answer or another executable command.',
                           criteria={identifier:action['label'] for identifier,action in actions.items()}),
        'empire_strategy':deepcopy(STRATEGY_QUESTION)})


def validate_city_control(action, state, screen, reviewed=None, rules=None, *, labor_ready=False):
    if not isinstance(action, dict) or set(action) != {'id','kind','label','actor','preconditions','parameters'}:
        raise CityControlError('Invalid city-control action schema')
    expected = city_control_candidates(state, screen, reviewed, rules, labor_ready=labor_ready)
    if action.get('id') not in expected or action != expected[action['id']]:
        raise CityControlError('City control is stale or differs from its canonical observed candidate')
