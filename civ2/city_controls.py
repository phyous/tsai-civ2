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
        if (not isinstance(reviewed, dict) or set(reviewed) != {'city_id','city_name','year_raw','actions'}
                or type(reviewed['city_id']) is not int or reviewed['city_id'] != city['id']
                or reviewed['city_name'] != city['name']
                or type(reviewed['year_raw']) is not int or reviewed['year_raw'] != year
                or not isinstance(reviewed['actions'], (list, tuple, set, frozenset))
                or any(not isinstance(a, str) or a not in REVIEWABLE for a in reviewed['actions'])):
            raise CityControlError('Reviewed controls must belong to this owned city and displayed year')
        seen = set(reviewed['actions'])
    return screen, actor, {**revision, 'image_sha256':digest,
        'width':screen['width'], 'height':screen['height'], 'screen_kind':'city_screen',
        'observed_city_title':title, 'year_raw':year, 'reviewed_action_ids':sorted(seen)}, seen


def city_control_candidates(state, screen, reviewed=None, rules=None):
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
    if 'exit_city' not in actions:
        raise CityControlError('A unique observed Exit must remain available')
    return actions


def city_control_request_for(state, screen, actions=None, reviewed=None, rules=None, recent_actions=None):
    expected = city_control_candidates(state, screen, reviewed, rules)
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
        controls={identifier:action['label'] for identifier,action in actions.items()},
        scope='City statistics come from the bound native save; buttons come from this current original city image. Change only opens production choices. Buy only opens a native quote. Its actual price and purchase confirmation require a new observation and a separate Jev choice. No purchase or price is inferred.',
        review_policy='Omit a control only after its native review finishes for this same city/year. Exit remains available; useful review does not require visiting every control.')
    return dict(state=projection, questions={
        'city_action':dict(type='choice', instructions='Choose one actual native control for this owned city. Consider current production, growth, happiness, available treasury and the wider empire. Review production when useful, request a purchase quote only when worth examining, or exit when finished. This answer authorizes only the selected control, never a purchase. empire_strategy is independent advice, not a previous answer or another executable command.',
                           criteria={identifier:action['label'] for identifier,action in actions.items()}),
        'empire_strategy':deepcopy(STRATEGY_QUESTION)})


def validate_city_control(action, state, screen, reviewed=None, rules=None):
    if not isinstance(action, dict) or set(action) != {'id','kind','label','actor','preconditions','parameters'}:
        raise CityControlError('Invalid city-control action schema')
    expected = city_control_candidates(state, screen, reviewed, rules)
    if action.get('id') not in expected or action != expected[action['id']]:
        raise CityControlError('City control is stale or differs from its canonical observed candidate')
