"""Observed-target plans chosen by Jev; no routing, game inputs or probabilities.

Planning and execution are separate model calls. A plan is context for later
ordinary unit choices, never an instruction for the harness to execute a path.
"""
from collections import Counter, defaultdict
from copy import deepcopy

from .policy import (DIRECTIONS, PolicyError, _destination, _grid_distance, _map,
                     _revision, _rules, _specification, _technologies, _unit,
                     _water_access, model_state, validate_action)


class PlanningError(PolicyError):
    pass


TASKS = ('survey', 'settle', 'road', 'irrigate', 'mine', 'defend', 'engage', 'approach_city')
ACTOR_FIELDS = ('id', 'owner', 'type_id', 'x', 'y', 'home_city_id', 'veteran')


def _actor(unit):
    return {key: unit.get(key) for key in ACTOR_FIELDS}


def _neighbors(state, point):
    return [p for _, _, dx, dy, _ in DIRECTIONS
            if (p := _destination(state, point['x']+dx, point['y']+dy)) is not None]


def task_candidates(state, rules=None, limit=64):
    """Return (canonical candidates, omission summary), with a reserved Hold.

    Candidates pass known terrain/role prerequisites, not a reachability oracle.
    Cap by round-robin task categories, each ordered by geometric distance then
    coordinates/ID. Omitted targets are counted; no target is scored as optimal.
    """
    if type(limit) is not int or not 2 <= limit <= 255:
        raise PlanningError('Candidate limit must be 2–255')
    revision = _revision(state); rules = _rules(rules); _, _, tiles = _map(state)
    unit = _unit(state)
    if unit is None:
        raise PlanningError('Planning requires the currently selected owned unit')
    spec = _specification(unit, rules); worker = spec['domain'] == 0 and spec['role'] == 5
    cities = state.get('cities', []); all_cities = cities+state.get('known_cities', [])
    occupied = {(c['x'], c['y']) for c in all_cities}
    foreign = state.get('visible_units', [])
    foreign_points = {(u['x'], u['y']) for u in foreign}
    technology = _technologies(state, rules)
    terrain_rules = {(r['id'], r['name']): r for r in rules.get('terrain', [])}
    groups = defaultdict(list)

    def add(task, target, label):
        identifier = f"{task}_{target['x']}_{target['y']}"+('_'+str(target['id']) if 'id' in target else '')
        groups[task].append(dict(id=identifier, task=task, label=label,
            actor=_actor(unit), preconditions={**revision, 'selected_unit_id':unit['id']}, target=target))

    for (x, y), tile in sorted(tiles.items()):
        point = dict(x=x, y=y); terrain = tile.get('terrain')
        compatible = spec['domain'] == 1 or (terrain == 'Ocean') == (spec['domain'] == 2)
        if not compatible or (worker and (x, y) in foreign_points):
            continue
        distance = _grid_distance(state, unit, point)
        suffix = f" at ({x},{y}); {terrain}, {distance} geometric steps away; route unverified"
        unknown = [p for p in _neighbors(state, point) if (p['x'], p['y']) not in tiles]
        if unknown:
            add('survey', {**point, 'unknown_neighbors':unknown}, f'Reveal new terrain near a known frontier ({len(unknown)} unknown neighbors)'+suffix)
        if not worker or (x, y) in occupied:
            continue
        if terrain in ('Grassland', 'Plains') and all(_grid_distance(state, point, c) > 1 for c in all_cities):
            spacing = min((_grid_distance(state, point, c) for c in cities), default=None)
            add('settle', point, 'Establish a city'+suffix+f"; nearest owned city {spacing if spacing is not None else 'none'} steps")
        works = set(tile.get('known_improvements', []))
        if not works & {'road', 'railroad'} and (tile.get('river') is not True or 'bridge building' in technology):
            add('road', point, 'Build a useful road'+suffix)
        rule = terrain_rules.get((tile.get('terrain_id'), terrain), {})
        if not works & {'mine', 'irrigation', 'farmland'}:
            if rule.get('irrigation_result', '').casefold() == 'yes' and _water_access(state, tile, tiles):
                add('irrigate', point, 'Irrigate a useful tile'+suffix)
            if rule.get('mining_result', '').casefold() == 'yes':
                add('mine', point, 'Mine a useful tile'+suffix)
    if not worker and spec['domain'] == 0 and spec.get('defense', 0) > 0:
        for city in cities:
            add('defend', {k:city[k] for k in ('id','x','y')}, f"Defend observed {city.get('name', 'owned city')} at ({city['x']},{city['y']})")
    enemies = {d['civ_id'] for d in state.get('diplomacy', []) if d.get('war') is True}
    if spec['attack'] > 0:
        for enemy in foreign:
            if enemy.get('owner') in enemies or enemy.get('owner') == 0:
                target = {k:enemy[k] for k in ('id','owner','type_id','x','y')}
                add('engage', target, f"Engage currently visible {enemy.get('type', 'hostile unit')} at ({enemy['x']},{enemy['y']}); current visibility required")
    if not worker and spec['domain'] == 0 and spec['attack'] > 0:
        for city in state.get('known_cities', []):
            point = (city.get('x'), city.get('y'))
            if point not in tiles or point in {(c['x'],c['y']) for c in cities}:
                continue
            target = {key:city[key] for key in ('x','y')}
            if _grid_distance(state, unit, target) <= 1:
                continue
            add('approach_city', target,
                f"Approach remembered foreign city {city.get('name','')} at ({target['x']},{target['y']}) "
                'to reassess its current situation; current owner and defenses are unknown. '
                'This objective does not authorize an attack or assert a safe route.')
    hold = dict(id='hold_one_turn', task='hold', label='Hold this unit for one turn, then reassess',
                actor=_actor(unit), preconditions={**revision, 'selected_unit_id':unit['id']}, target={'turn':state['turn']+1})
    for bucket in groups.values():
        bucket.sort(key=lambda c: (_grid_distance(state, unit, c['target']), c['target']['y'], c['target']['x'], c['id']))
    chosen = {hold['id']:hold}; depth = 0
    while len(chosen) < limit:
        batch = [groups[task][depth] for task in TASKS if depth < len(groups[task])]
        if not batch: break
        for candidate in batch[:limit-len(chosen)]: chosen[candidate['id']] = candidate
        depth += 1
    counts = Counter(c['task'] for c in chosen.values())
    omitted = {task:len(groups[task])-counts[task] for task in TASKS if len(groups[task])>counts[task]}
    return chosen, dict(limit=limit, total=1+sum(map(len,groups.values())), offered=len(chosen), omitted_by_task=omitted,
        selection_rule='Hold reserved; round-robin task categories, each nearest geometric distance then y/x/ID. No route or strategic score.',
        limits='Known-compatible proposed targets only. Native legality, reachability, current fog and tactical safety are not established.')


def request_for(state, rules=None, recent_actions=None, limit=64):
    candidates, summary = task_candidates(state, rules, limit)
    if len(candidates) < 2:
        raise PlanningError('Only Hold is available; no fabricated singleton Choice')
    projection = model_state(state, rules, recent_actions)
    projection['planning'] = {'candidate_summary':summary, 'targets':{k:{'task':c['task'],'target':c['target']} for k,c in candidates.items()},
        'scope':'Select a persistent task for this observed actor. This call executes no input; a later independent unit-action call chooses every next command.'}
    question = dict(type='choice', instructions='Choose a useful concrete task and observed target for this selected unit. Balance settlement, purposeful exploration, productive tile work and appropriate military roles. Consider current cities, known terrain, unit support and visible threats. Hold only for a useful reason. Targets are proposals, not proven routes or guaranteed safe/legal sites. Do not infer hidden information; the later action model may detour, wait or request a new plan.',
                    criteria={key:c['label'] for key,c in candidates.items()})
    return {'state':projection, 'questions':{'task_choice':question}}, candidates


def make_plan(candidate, state, rules=None, limit=64, max_turns=8):
    if type(max_turns) is not int or not 1 <= max_turns <= 20:
        raise PlanningError('Plan review interval must be 1–20 turns')
    candidates, _ = task_candidates(state, rules, limit)
    if not isinstance(candidate,dict) or candidates.get(candidate.get('id')) != candidate:
        raise PlanningError('Plan differs from a current canonical candidate')
    return dict(candidate=deepcopy(candidate), actor=deepcopy(candidate['actor']),
        current_save_sha256=_revision(state)['save_sha256'], created_turn=state['turn'],
        expires_turn=state['turn']+max_turns, observations=0, status='active', reason='Jev-selected task; no input executed')


def advance_plan(plan, before, after, action=None, rules=None):
    """Conservative observation-only continuity; no guessed unit-ID remapping.

    Any removed roster slot, nonunique physical actor, unexpected actor movement
    or changed actor type invalidates. New slots may be added. Undecodable birth/
    death replacement cannot be proven absent; this is context, not input binding.
    """
    old, new = _revision(before), _revision(after)
    result = deepcopy(plan)
    if result.get('status') != 'active': return result
    def stop(status, reason):
        result.update(status=status, reason=reason); return result
    if old['save_sha256'] != result.get('current_save_sha256') or after['turn'] < before['turn']:
        return stop('invalidated', 'Checkpoint continuity is unavailable')
    actor = result['actor']; candidate = result['candidate']; task = candidate['task']; target = candidate['target']
    units = {u['id']:u for u in before['units']}; fresh = {u['id']:u for u in after['units']}
    if actor['id'] not in units or _actor(units[actor['id']]) != actor:
        return stop('invalidated', 'Previous actor fingerprint changed')
    if action is not None:
        validate_action(action, before, rules)
    result['observations'] += 1; result['current_save_sha256'] = new['save_sha256']
    point = (target.get('x'),target.get('y'))
    old_cities = {(c['x'],c['y']) for c in before['cities']}
    new_cities = {(c['x'],c['y']) for c in after['cities']}
    if task == 'settle' and point in new_cities-old_cities:
        return stop('complete', 'An owned city is newly observed at the target; causal attribution is not inferred')
    _, _, tiles = _map(after); tile = tiles.get(point)
    if task in ('road','irrigate','mine') and tile and {'road':'road','irrigate':'irrigation','mine':'mine'}[task] in tile.get('known_improvements',[]):
        return stop('complete', 'The requested improvement is now reported at the target; causal attribution is not inferred')
    if task == 'survey' and any((p['x'],p['y']) in tiles for p in target['unknown_neighbors']):
        return stop('complete', 'At least one previously unknown neighboring tile is now observed')
    if not set(units).issubset(fresh) or actor['id'] not in fresh:
        return stop('invalidated', 'Roster removal or possible ID compaction; no identity guessed')
    positions = {(actor['x'],actor['y'])}
    if action and action['actor']['id'] == actor['id'] and action['kind'] == 'move':
        p = action['parameters']['destination']; positions.add((p['x'],p['y']))
    identity = ('owner','type_id','home_city_id','veteran')
    matches = [u for u in fresh.values() if all(u.get(k)==actor.get(k) for k in identity) and (u['x'],u['y']) in positions]
    if len(matches)!=1 or matches[0]['id']!=actor['id']:
        return stop('invalidated', 'Observed actor transition is not unique')
    result['actor'] = _actor(matches[0])
    if task == 'hold' and after['turn'] >= target['turn']:
        return stop('complete', 'The requested one-turn hold has elapsed')
    if after['turn'] >= result['expires_turn'] or result['observations'] >= 32:
        return stop('expired', 'Bounded review interval reached; ask Jev for a new task')
    if task == 'defend' and point not in new_cities:
        return stop('invalidated', 'Target is no longer an observed owned city')
    if task == 'approach_city':
        if point in new_cities:
            return stop('complete', 'An owned city is now observed at the target; conquest is not inferred')
        if not any((c.get('x'),c.get('y'))==point for c in after.get('known_cities',[])):
            return stop('invalidated', 'The remembered city location is no longer in the observation')
        if _grid_distance(after, result['actor'], target) <= 1:
            return stop('complete', 'The actor is now near the remembered city; reassess current diplomacy and visible threats')
    if task == 'engage' and not any(all(u.get(k)==v for k,v in target.items()) for u in after.get('visible_units', [])):
        return stop('invalidated', 'Exact hostile target is no longer currently visible; destruction is not inferred')
    if task == 'settle' and (not tile or tile.get('terrain') not in ('Grassland','Plains') or any(
            _grid_distance(after, target, c) <= 1 for c in after['cities']+after.get('known_cities', []))):
        return stop('invalidated', 'Known settlement-site prerequisites changed')
    if task in ('road','irrigate','mine'):
        if not tile or point in new_cities or any((c['x'],c['y'])==point for c in after.get('known_cities', [])):
            return stop('invalidated', 'Improvement target is unavailable or now a city center')
        works=set(tile.get('known_improvements', [])); technology=_technologies(after,_rules(rules))
        rule=next((r for r in _rules(rules).get('terrain',[]) if r.get('id')==tile.get('terrain_id') and r.get('name')==tile.get('terrain')), {})
        invalid=(task=='road' and ('railroad' in works or (tile.get('river') is True and 'bridge building' not in technology)))
        invalid |= task=='irrigate' and (bool(works & {'mine','farmland'}) or rule.get('irrigation_result','').casefold()!='yes' or not _water_access(after,tile,tiles))
        invalid |= task=='mine' and (bool(works & {'irrigation','farmland'}) or rule.get('mining_result','').casefold()!='yes')
        if invalid:return stop('invalidated', 'Known improvement prerequisites changed')
    result['reason'] = 'Observed actor continuity retained; Jev still chooses the next legal action'
    return result
