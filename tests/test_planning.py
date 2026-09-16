"""Pure planning tests: synthetic TEST states, no model calls or game controls."""
from copy import deepcopy
import json
import unittest

from civ2.planning import PlanningError, advance_plan, make_plan, request_for, task_candidates
from civ2.policy import DIRECTIONS, unit_candidates
from civ2.typesafe import _validate_questions


def fixture(worker=True):
    spec=dict(id=0 if worker else 1,name='TEST Settler' if worker else 'TEST Warrior',domain=0,
              role=5 if worker else 1,attack=0 if worker else 1,defense=1,movement=1)
    tiles=[dict(x=8+dx,y=8+dy,terrain='Plains',terrain_id=1,river=False,known_improvements=[])
           for _,_,dx,dy,_ in (('here','here',0,0,''),*DIRECTIONS)]
    state=dict(turn=1,selected_unit_id=7,settings={'round_world':False},
        player=dict(id=1,government='Despotism',known_technology_ids=[],known_technologies=[]),
        units=[dict(id=7,owner=1,type_id=spec['id'],type=spec['name'],x=8,y=8,home_city_id=None,
                    veteran=False,hp=20,movement_thirds_spent=0,order_id=255,specification=spec)],
        cities=[],known_cities=[],visible_units=[],diplomacy=[],
        map=dict(width=20,coordinate_width=40,height=20,tiles=tiles),evidence={'save_sha256':'a'*64})
    rules=dict(units=[spec],advances=[],terrain=[dict(id=1,name='Plains',irrigation_result='yes',mining_result='For'),
        dict(id=4,name='Hills',irrigation_result='yes',mining_result='yes')])
    return state,rules


def fresh(state):
    state=deepcopy(state);state['evidence']['save_sha256']='b'*64;return state


def select(state,rules,task,point=None,**kwargs):
    candidates,_=task_candidates(state,rules,limit=255)
    candidate=next(c for c in candidates.values() if c['task']==task and
                   (point is None or (c['target'].get('x'),c['target'].get('y'))==point))
    return make_plan(candidate,state,rules,limit=255,**kwargs)


class PlanningTests(unittest.TestCase):
    def test_observed_targets_only_no_hidden_map_and_no_worker_combat(self):
        s,r=fixture();s['map']['hidden_tiles']=[dict(x=30,y=10,terrain='SECRET')]
        candidates,summary=task_candidates(s,r)
        known={(t['x'],t['y']) for t in s['map']['tiles']}
        self.assertTrue(all((c['target']['x'],c['target']['y']) in known for c in candidates.values() if c['task']!='hold'))
        self.assertFalse({'engage','defend'} & {c['task'] for c in candidates.values()})
        self.assertNotIn('SECRET',json.dumps(candidates));self.assertEqual(summary['omitted_by_task'],{})

    def test_worker_site_city_center_terrain_technology_and_water_constraints(self):
        s,r=fixture();s['cities']=[dict(id=0,owner=1,name='TEST City',x=8,y=8)]
        north=next(t for t in s['map']['tiles'] if (t['x'],t['y'])==(8,6))
        north.update(terrain='Hills',terrain_id=4,river=True)
        candidates,_=task_candidates(s,r,limit=255)
        center=[c['task'] for c in candidates.values() if c['target'].get('x')==8 and c['target'].get('y')==8]
        self.assertFalse(set(center)&{'settle','road','irrigate','mine'})
        at_north={c['task'] for c in candidates.values() if c['target'].get('x')==8 and c['target'].get('y')==6}
        self.assertIn('mine',at_north);self.assertIn('irrigate',at_north)
        self.assertNotIn('settle',at_north);self.assertNotIn('road',at_north)
        s['player']['known_technologies']=[{'name':'Bridge Building'}]
        candidates,_=task_candidates(s,r,limit=255)
        self.assertIn('road_8_6',candidates)

    def test_enemy_tasks_require_war_or_visible_barbarian_and_never_use_future_order(self):
        s,r=fixture(False);s['cities']=[dict(id=0,owner=1,name='TEST City',x=8,y=8)]
        s['visible_units']=[dict(id=11,owner=2,type_id=1,type='TEST Enemy',x=10,y=8,goto={'secret':'SECRET'})]
        candidates,_=task_candidates(s,r);self.assertNotIn('engage',set(c['task'] for c in candidates.values()))
        self.assertIn('defend',set(c['task'] for c in candidates.values()))
        s['diplomacy']=[dict(civ_id=2,contact=True,war=True)]
        candidates,_=task_candidates(s,r);self.assertIn('engage_10_8_11',candidates)
        self.assertNotIn('SECRET',json.dumps(candidates))
        s['diplomacy']=[];s['visible_units'][0]['owner']=0
        self.assertIn('engage_10_8_11',task_candidates(s,r)[0])

    def test_candidate_cap_is_deterministic_reports_omissions_and_reserves_hold(self):
        s,r=fixture();s['map']['tiles']=[dict(x=2*c+y%2,y=y,terrain='Plains',terrain_id=1,
            river=False,known_improvements=[]) for y in range(20) for c in range(20)]
        candidates,summary=task_candidates(s,r,limit=7)
        self.assertEqual(len(candidates),7);self.assertIn('hold_one_turn',candidates)
        self.assertEqual(summary['total']-summary['offered'],sum(summary['omitted_by_task'].values()))
        s['map']['tiles'].reverse()
        self.assertEqual((candidates,summary),task_candidates(s,r,limit=7))
        self.assertEqual(len(task_candidates(s,r,limit=255)[0]),255)

    def test_request_is_real_separate_task_choice_without_probabilities_or_input(self):
        s,r=fixture();request,candidates=request_for(s,r)
        _validate_questions(request['questions'])
        self.assertEqual(set(request['questions']),{'task_choice'})
        self.assertEqual(set(request['questions']['task_choice']['criteria']),set(candidates))
        self.assertNotIn('probabilities',json.dumps(request));self.assertNotIn('parameters',json.dumps(candidates))
        self.assertNotIn('actor',next(iter(request['state']['planning']['targets'].values())))

    def test_creation_rejects_stale_actor_revision_or_tampered_target(self):
        s,r=fixture();c=next(c for c in task_candidates(s,r)[0].values() if c['task']=='settle')
        for mutate in (lambda x:x['target'].update(x=30),lambda x:x['actor'].update(id=6),
                       lambda x:x['preconditions'].update(save_sha256='c'*64)):
            changed=deepcopy(c);mutate(changed)
            with self.assertRaises(PlanningError):make_plan(changed,s,r)
        for limit in (1,256,True):
            with self.assertRaises(PlanningError):task_candidates(s,r,limit)

    def test_verified_move_retains_goal_but_arrival_does_not_found_a_city(self):
        s,r=fixture();plan=select(s,r,'settle',(10,8));action=unit_candidates(s,rules=r)['move_e']
        after=fresh(s);after['units'][0].update(x=10,y=8)
        updated=advance_plan(plan,s,after,action,r)
        self.assertEqual(updated['status'],'active');self.assertEqual(updated['actor']['x'],10)
        self.assertEqual(updated['candidate'],plan['candidate']);self.assertEqual(plan['actor']['x'],8)
        self.assertEqual(advance_plan(plan,s,after,rules=r)['status'],'invalidated')

    def test_id_compaction_and_ambiguous_stack_invalidate_without_guessing(self):
        s,r=fixture();plan=select(s,r,'settle',(10,8));after=fresh(s)
        after['units'][0]['id']=6;after['selected_unit_id']=6
        self.assertEqual(advance_plan(plan,s,after,rules=r)['status'],'invalidated')
        after=fresh(s);extra=deepcopy(after['units'][0]);extra['id']=8;after['units'].append(extra)
        self.assertEqual(advance_plan(plan,s,after,rules=r)['status'],'invalidated')
        after=fresh(s);after['units'][0]['type_id']=1
        self.assertEqual(advance_plan(plan,s,after,rules=r)['status'],'invalidated')

    def test_observed_completion_does_not_claim_causal_attribution(self):
        s,r=fixture();plan=select(s,r,'settle',(8,8));after=fresh(s)
        after['units']=[];after['cities']=[dict(id=0,owner=1,name='TEST City',x=8,y=8)]
        updated=advance_plan(plan,s,after,rules=r)
        self.assertEqual(updated['status'],'complete');self.assertIn('causal attribution is not inferred',updated['reason'])
        plan=select(s,r,'road',(8,8));after=fresh(s)
        next(t for t in after['map']['tiles'] if (t['x'],t['y'])==(8,8))['known_improvements']=['road']
        self.assertEqual(advance_plan(plan,s,after,rules=r)['status'],'complete')

    def test_frontier_completion_requires_new_observed_terrain(self):
        s,r=fixture();plan=select(s,r,'survey');after=fresh(s)
        self.assertEqual(advance_plan(plan,s,after,rules=r)['status'],'active')
        p=plan['candidate']['target']['unknown_neighbors'][0]
        after['map']['tiles'].append(dict(**p,terrain='Plains',terrain_id=1,river=False,known_improvements=[]))
        self.assertEqual(advance_plan(plan,s,after,rules=r)['status'],'complete')

    def test_current_frontier_remains_useful_without_inventing_unknown_terrain(self):
        s,r=fixture(False);s['map']['tiles']=[t for t in s['map']['tiles'] if (t['x'],t['y'])==(8,8)]
        request,candidates=request_for(s,r)
        self.assertEqual(set(candidates),{'hold_one_turn','survey_8_8'})
        target=candidates['survey_8_8']['target']
        self.assertEqual(len(target['unknown_neighbors']),8)
        self.assertTrue(all(set(p)=={'x','y'} for p in target['unknown_neighbors']))
        plan=make_plan(candidates['survey_8_8'],s,r)
        self.assertEqual(advance_plan(plan,s,fresh(s),rules=r)['status'],'active')

    def test_improvement_plan_invalidates_when_target_becomes_city_center(self):
        s,r=fixture();plan=select(s,r,'road',(10,8));after=fresh(s)
        after['cities']=[dict(id=0,owner=1,name='TEST City',x=10,y=8)]
        self.assertEqual(advance_plan(plan,s,after,rules=r)['status'],'invalidated')

    def test_hold_review_bound_and_checkpoint_continuity(self):
        s,r=fixture();after=fresh(s);after['turn']=2
        self.assertEqual(advance_plan(select(s,r,'hold'),s,after,rules=r)['status'],'complete')
        self.assertEqual(advance_plan(select(s,r,'settle',(10,8),max_turns=1),s,after,rules=r)['status'],'expired')
        plan=select(s,r,'settle',(10,8));plan['observations']=31
        self.assertEqual(advance_plan(plan,s,fresh(s),rules=r)['status'],'expired')
        before=fresh(s)
        self.assertEqual(advance_plan(plan,before,after,rules=r)['status'],'invalidated')

    def test_fogged_enemy_is_invalidated_not_assumed_destroyed(self):
        s,r=fixture(False);s['diplomacy']=[dict(civ_id=2,war=True)]
        s['visible_units']=[dict(id=11,owner=2,type_id=1,type='TEST Enemy',x=10,y=8)]
        plan=select(s,r,'engage');after=fresh(s);after['visible_units']=[]
        updated=advance_plan(plan,s,after,rules=r)
        self.assertEqual(updated['status'],'invalidated');self.assertIn('destruction is not inferred',updated['reason'])


if __name__=='__main__':unittest.main()
