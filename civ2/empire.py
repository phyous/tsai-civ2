"""Concrete Jev choices at the original game's observed End of Turn cue.

Commands use original MENU.TXT shortcuts and only open menus. Their contents
need fresh native observations; city navigation additionally binds a requested
owned city. No input, API call or game-state mutation happens in this module.
"""
from __future__ import annotations

from copy import deepcopy
import re

from .dialogs import classify_dialog
from .policy import model_state, STRATEGY_QUESTION, _unit_health_resolved
from .rules import eligible_governments
from .save import parse_rules
from .revision import RevisionError, revision


class EmpireError(ValueError):
    pass


class ForcedEmpireAction(EmpireError):
    """Only one real action remains; do not fabricate a model distribution."""


SHA256=re.compile(r'[0-9a-f]{64}')
MENU_IDS={'open_tax','open_diplomacy','open_research','open_revolution'}


def _rules(value):
    if value is None:return {}
    if isinstance(value,str):return parse_rules(value)
    if not isinstance(value,dict):raise EmpireError('Original parsed rules or RULES.TXT text required')
    return value


def _reviewed(value,turn):
    if value is None:return set()
    if isinstance(value,dict):
        if set(value)!={'turn','actions'} or value['turn']!=turn:
            raise EmpireError('Reviewed menus must belong to this observed turn')
        value=value['actions']
    if not isinstance(value,(set,frozenset,list,tuple)) or any(not isinstance(v,str) for v in value):
        raise EmpireError('Reviewed actions must be a collection of current-turn action IDs')
    result=set(value)
    if any(v not in MENU_IDS and not re.fullmatch(r'inspect_city_\d+',v) for v in result):
        raise EmpireError('Unknown review token; Finish Turn is never a reviewed menu')
    return result


def _context(state,screen,reviewed):
    try:
        bound_revision=revision(state)
    except RevisionError as error:
        raise EmpireError(str(error)) from None
    turn=bound_revision['turn']
    if turn<1:raise EmpireError('Positive observed turn is required')
    if not isinstance(screen,dict):raise EmpireError('Observed End of Turn screen required')
    if 'lines' in screen:screen=classify_dialog(screen,state=state)
    if (screen.get('supported') is not True or screen.get('kind')!='end_turn'
        or not isinstance(screen.get('title'),str) or ' '.join(screen['title'].casefold().split())!='end of turn'
        or screen.get('options')):
        raise EmpireError('Only an unambiguous native End of Turn cue enables empire commands')
    image_hash=screen.get('sha256')
    if not isinstance(image_hash,str) or not SHA256.fullmatch(image_hash):
        raise EmpireError('Exact source image SHA is required')
    if any(type(screen.get(k)) is not int or not 1<=screen[k]<=4096 for k in ('width','height')):
        raise EmpireError('Invalid source image dimensions')
    player=state.get('player',{}).get('id')
    if type(player) is not int or not 1<=player<=7:raise EmpireError('Observed human player required')
    seen=_reviewed(reviewed,turn)
    return screen,seen,dict(**bound_revision,image_sha256=image_hash,
        width=screen['width'],height=screen['height'],screen_kind='end_turn',
        end_turn_text=screen['title'],reviewed_action_ids=sorted(seen))


def _production_context(state,rules):
    """Observed production/roster arithmetic, never a claim of adequate defense."""
    player=state['player']['id']
    units=[u for u in state.get('units',[]) if isinstance(u,dict) and u.get('owner')==player]
    cities=state.get('cities',[])
    def spec(identifier):
        matches=[s for s in rules.get('units',[]) if s.get('id')==identifier]
        return matches[0] if len(matches)==1 else {}
    unresolved={u['id'] for u in units if not _unit_health_resolved(u,spec(u.get('type_id')))}
    workers=[u for u in units if u['id'] not in unresolved and spec(u.get('type_id')).get('role')==5]
    unknown=sum(type(spec(u.get('type_id')).get('role')) is not int for u in units)
    builds=[];unknown_builds=0;city_facts=[]
    for city in cities:
        production=city.get('production',{});build=spec(production.get('id')) if production.get('kind')=='unit' else {}
        if production.get('kind')=='unit' and type(build.get('role')) is not int:unknown_builds+=1
        if production.get('kind') not in ('unit','improvement','wonder'):unknown_builds+=1
        if build.get('role')==5:builds.append(city['id'])
        here=[u for u in units if (u.get('x'),u.get('y'))==(city.get('x'),city.get('y'))]
        armed=sum(u['id'] not in unresolved and spec(u.get('type_id')).get('attack',0)>0 for u in here)
        home=[u for u in units if type(u.get('home_city_id')) is int and u['home_city_id']==city['id']]
        # These stock ground roles are explicitly covered by the manual's
        # military/Settler support rules. Other types remain unclassified.
        ground=[u for u in home if spec(u.get('type_id')).get('domain')==0
                and (spec(u.get('type_id')).get('role')==5
                     or (spec(u.get('type_id')).get('role') in (0,1)
                         and type(spec(u.get('type_id')).get('attack')) is int
                         and spec(u.get('type_id'))['attack']>0))]
        home_workers=[u for u in ground if spec(u.get('type_id')).get('role')==5]
        support=dict(home_units=len(home),home_units_away=sum(
            (u.get('x'),u.get('y'))!=(city.get('x'),city.get('y')) for u in home),
            known_ground_support_units=len(ground),home_worker_units=len(home_workers),
            unclassified_home_units=len(home)-len(ground),
            unresolved_native_home_unit_ids=[u['id'] for u in home if u['id'] in unresolved])
        government=state['player'].get('government_id');size=city.get('size')
        if support['unresolved_native_home_unit_ids']:
            support['arithmetic_unavailable']='Home roster contains unresolved native HP; await a stable native observation before estimating support.'
        if not support['unresolved_native_home_unit_ids'] and type(government) is int and government in (1,2) and type(size) is int and size>0:
            allowance=size if government==1 else 3
            support.update(free_shield_support_allowance=allowance,
                minimum_shield_support=max(0,len(ground)-allowance),
                food_for_population=2*size,food_for_known_home_workers=len(home_workers))
            for resource in ('food','shields'):
                gross=city.get(resource+'_produced')
                if type(gross) is int and gross>=0:
                    support['gross_'+resource]=gross
                    cost=2*size+len(home_workers) if resource=='food' else support['minimum_shield_support']
                    support[resource+'_after_listed_costs']=gross-cost
        city_facts.append(dict(city_id=city['id'],name=city['name'],owned_units_here=len(here),
            armed_units_here=armed,unresolved_native_unit_ids=[u['id'] for u in here if u['id'] in unresolved],unknown_unit_specifications_here=sum(type(spec(u.get('type_id')).get('attack')) is not int for u in here),
            production=deepcopy(production),unit_production_repeats=production.get('kind')=='unit',support_review=support))
    return dict(owned_worker_units=len(workers),worker_producing_city_ids=builds,
        unknown_unit_specifications=unknown,unknown_production_specifications=unknown_builds,
        unresolved_native_unit_ids=sorted(unresolved),
        no_observed_worker_or_worker_build=(not workers and not builds and not unresolved and unknown==unknown_builds==0),
        cities=city_facts,
        note='Only owned records and original unit roles/base attack are counted. Zero or unresolved HP records remain visible but are excluded from armed/worker counts; they block support arithmetic for their home city. Garrison counts do not establish safety, sufficiency or a required build. Unit production repeats after completion until changed; this is not a completion forecast.',
        support_note='Original manual: home city pays support regardless of current location. Arithmetic is limited to Despotism/Monarchy and current recorded population/output. The shield minimum counts only known ground combat/worker roles; unclassified units may add costs. Food subtracts two per citizen and one per known home worker. These remainders are not verified net surplus: waste, other unit costs, food routes and native effects are not modeled. A nonnegative remainder does not establish sustainability or predict output after Settler completion. Missing home identities are not assigned to a nearby city.',
        support_source='https://archive.org/details/civ2_manual')


def empire_candidates(state,screen,reviewed=None,rules=None):
    """Current-turn choices. Reviewed menus are omitted; Finish Turn remains.

    ``reviewed`` can be a current-turn set of canonical IDs or a safer record
    ``{'turn': state['turn'], 'actions': [...]}``. A mismatched turn is rejected.
    Mark a menu reviewed only after its native transaction actually completed.
    """
    screen,seen,preconditions=_context(state,screen,reviewed)
    rules=_rules(rules);player=state['player']['id'];actions={}
    cities=state.get('cities',[])
    if not isinstance(cities,list):raise EmpireError('Owned cities must be a list')
    identifiers=set();names=set()
    for city in cities:
        if not isinstance(city,dict) or city.get('owner')!=player:
            raise EmpireError('City navigation requires owned city records only')
        if any(type(city.get(k)) is not int or city[k]<0 for k in ('id','x','y','size')):
            raise EmpireError('City actor signature is incomplete')
        if not isinstance(city.get('name'),str) or not city['name'].strip() or any(ord(c)<32 for c in city['name']):
            raise EmpireError('Observed city name is invalid')
        if city['id'] in identifiers:raise EmpireError('Duplicate city slot')
        identifiers.add(city['id'])
        # A locator with duplicate labels cannot bind an exact city by text.
        normalized=city['name'].casefold().strip()
        if normalized in names:raise EmpireError('Duplicate owned city names make native locator selection ambiguous')
        names.add(normalized)
    def add(identifier,kind,label,actor,key,modifiers=(),**parameters):
        if identifier in seen:return
        actions[identifier]=dict(id=identifier,kind=kind,label=label,actor=deepcopy(actor),
            preconditions=deepcopy(preconditions),parameters=dict(key=key,modifiers=list(modifiers),**parameters))
    production_context=_production_context(state,rules)
    city_context={c['city_id']:c for c in production_context['cities']}
    disorder=sum(c.get('disorder') is True for c in cities)
    note=f' ({disorder} owned cities currently in disorder)' if disorder else ''
    add('finish_turn','finish_turn','Finish this turn: advance current production, research and other civilizations; completed unit types repeat until changed'+note,
        dict(kind='empire',player_id=player),'Enter',only_open_menu=False,expected_screen='native_turn_progress')
    for city in sorted(cities,key=lambda c:c['id']):
        actor={key:city[key] for key in ('id','owner','name','x','y')};actor['kind']='city'
        details=[f"size {city['size']}"]
        if city.get('disorder') is True:details.append('in disorder')
        production=city.get('production',{}).get('name')
        if isinstance(production,str) and production:details.append('producing '+production)
        fact=city_context[city['id']]
        if fact['unknown_unit_specifications_here']==0:details.append(f"{fact['armed_units_here']} armed units here")
        if production_context['no_observed_worker_or_worker_build']:details.append('empire has no worker and no worker build')
        add('inspect_city_'+str(city['id']),'inspect_city',f"Review or change {city['name']} production in its city screen ({', '.join(details)}); the actual change needs a separate choice",
            actor,'KeyC',('ShiftLeft',),only_open_menu=True,expected_screen='city_locator',
            target_city={key:city[key] for key in ('id','owner','name','x','y')},
            navigation_requires_fresh_locator=True)
    actor=dict(kind='empire',player_id=player)
    add('open_tax','empire_menu','Review empire tax and luxury settings in the native Tax Rate screen',actor,'KeyT',('ShiftLeft',),
        only_open_menu=True,expected_screen='native_tax_rates')
    contacts=[d for d in state.get('diplomacy',[]) if isinstance(d,dict) and d.get('contact') is True
              and type(d.get('civ_id')) is int and 1<=d['civ_id']<=7 and d['civ_id']!=player]
    if contacts:
        add('open_diplomacy','empire_menu','Consult the Foreign Minister about actual contacted civilizations',actor,'F3',
            only_open_menu=True,expected_screen='foreign_minister')
    add('open_research','empire_menu','Review the Science Advisor and current research; any subsequent choice needs its own observation',actor,'F6',
        only_open_menu=True,expected_screen='science_advisor')
    current=state['player'].get('government_id')
    if type(current) is not int or not 0<=current<=6:raise EmpireError('Observed government ID required')
    alternatives=[g for g in eligible_governments(state,rules) if g['id']>1 and g['id']!=current]
    if current!=0 and alternatives:
        labels=', '.join(g['name'] for g in alternatives)
        add('open_revolution','empire_menu','Consider a revolution: review the native confirmation; available alternatives include '+labels,
            actor,'KeyR',('ShiftLeft',),only_open_menu=True,expected_screen='revolution_choice',
            available_government_ids=[g['id'] for g in alternatives],
            confirmation_requires_separate_choice=True)
    if len(actions)>255:raise EmpireError('More than 255 current choices require a separate observed city-selection stage')
    return actions


def empire_request_for(state,screen,actions=None,reviewed=None,rules=None,recent_actions=None):
    expected=empire_candidates(state,screen,reviewed,rules)
    if actions is None:actions=expected
    if actions!=expected:raise EmpireError('Empire candidates differ from the current observation/review ledger')
    if len(actions)<2:raise ForcedEmpireAction('Only Finish Turn remains after reviewed menus; record a forced native action, not a fabricated Jev probability')
    projection=model_state(state,rules,recent_actions)
    production_context=_production_context(state,_rules(rules))
    _,seen,_=_context(state,screen,reviewed)
    projection['end_of_turn_review']=dict(
        observed_cue=screen.get('title','End of Turn'),
        production_review=production_context,
        reviewed_action_ids=sorted(seen),
        remaining_options={identifier:action['label'] for identifier,action in actions.items()},
        review_policy='Menus/cities already completed this turn are omitted. This does not claim their settings were changed or optimized. The ledger must reset on the next observed turn.',
        command_scope='Each menu action only opens a native screen. Menu contents, confirmations and changes require fresh observed options. Inspect City includes only exact owned-city navigation through the observed locator.',
        outcome='The original End of Turn indicator is visible. Finish Turn is an explicit choice; it can trigger original production, research, diplomacy and turn events.')
    return dict(state=projection,questions={
        'empire_action':dict(type='choice',instructions=(
            'The original game is at End of Turn. Choose exactly one actual action. '
            'Unit production automatically repeats after completion: a city still producing Warriors can already have made several. '
            'Check current garrisons and the worker pipeline before continuing that repeated build. '
            'Also check home-city support: movement does not remove that cost, and Settler completion can lower population and output while adding a supported unit. Gross output and listed-cost arithmetic are not verified net surplus. '
            'If no worker exists and no city is building one, further military production alone cannot expand the empire or improve terrain; consider a concrete production change when food and defense permit. '
            'The supplied current city records already show builds, stored resources, output and happiness; '
            'opening a city is not needed merely to learn those facts. Production and research progress by advancing turns. '
            'Let a still-appropriate build progress; do not interpret a completed unit followed by the same build as an unfinished first unit. '
            'Review useful unresolved city production, happiness, income, science or diplomatic matters before finishing; '
            'finish when further review is not useful. Menu actions do not themselves choose a new setting or promise an improvement. '
            'Previously reviewed menus are explicitly listed and omitted to prevent repeated interface loops. '
            'Do not delay merely to inspect everything, and do not assume opening an advisor changed the game. '
            'empire_strategy is independent advice and cannot serve as this question\'s previous answer.'),
            criteria={identifier:action['label'] for identifier,action in actions.items()}),
        'empire_strategy':deepcopy(STRATEGY_QUESTION)})


def validate_empire_action(action,state,screen,reviewed=None,rules=None):
    if not isinstance(action,dict) or set(action)!={'id','kind','label','actor','preconditions','parameters'}:
        raise EmpireError('Invalid empire action schema')
    expected=empire_candidates(state,screen,reviewed,rules)
    if action.get('id') not in expected or action!=expected[action['id']]:
        raise EmpireError('Empire action is stale or differs from its current canonical candidate')


makeempire_candidates=empire_candidates
make_empire_candidates=empire_candidates
