"""Observed trade-unit objectives are model context, never automatic routes."""
from copy import deepcopy
import json
from unittest import TestCase
from civ2.planning import (task_candidates,request_for,category_request_for,target_request_for,
    selected_category_target,make_plan,advance_plan,PlanningError)
from civ2.policy import unit_candidates
from civ2.typesafe import _validate_questions
from tests.test_planning import fixture as base_fixture,fresh


def fixture(freight=False):
    state,rules=base_fixture(False)
    spec=dict(rules['units'][0],id=49 if freight else 48,name='TEST Freight' if freight else 'TEST Caravan',
              role=7,attack=0,max_hp=10)
    rules['units']=[spec];rules['improvements']=[dict(id=39,kind='wonder',name='TEST Wonder')]
    state['units'][0].update(type_id=spec['id'],type=spec['name'],specification=spec,home_city_id=0,hp=10,hp_lost=0)
    state['cities']=[dict(id=0,owner=1,name='TEST Home',x=6,y=8,production={'kind':'unit','id':1,'name':'TEST Warrior'}),
                     dict(id=1,owner=1,name='TEST Builder',x=10,y=8,production={'kind':'improvement','id':39,'name':'TEST Wonder'})]
    state['known_cities']=[dict(id=99,name='TEST Remembered',x=12,y=8,current_information=False,
                               owner='PRIVATE_OWNER',supply='PRIVATE_SUPPLY',demand='PRIVATE_DEMAND')]
    state['map']['tiles'].append(dict(x=12,y=8,terrain='Plains',terrain_id=1,known_improvements=[]))
    state['wonders']=[dict(id=0,improvement_id=39,name='TEST Wonder',status='not_built',owned=False)]
    return state,rules


def new_tasks(state,rules,limit=64):
    return {k:c for k,c in task_candidates(state,rules,limit)[0].items()
            if c['task'] in ('trade_delivery','assist_wonder')}


class CaravanPlanningTests(TestCase):
    def test_caravan_and_freight_offer_owned_and_remembered_delivery_and_current_wonder(self):
        for freight in (False,True):
            with self.subTest(freight=freight):
                state,rules=fixture(freight);before=deepcopy(state)
                actions=unit_candidates(state,rules=rules);offered=new_tasks(state,rules)
                self.assertEqual(set(offered),{'trade_delivery_10_8','trade_delivery_12_8','assist_wonder_10_8_1'})
                self.assertEqual(offered['trade_delivery_12_8']['target'],{'x':12,'y':8})
                self.assertEqual(offered['assist_wonder_10_8_1']['target'],{'id':1,'x':10,'y':8,'improvement_id':39})
                self.assertTrue(all(c['actor']['id']==7 and c['preconditions']['save_sha256']=='a'*64 for c in offered.values()))
                self.assertNotIn('PRIVATE',json.dumps(offered));self.assertNotIn('parameters',json.dumps(offered))
                self.assertIn('current owner is unknown',offered['trade_delivery_12_8']['label'])
                self.assertIn('separate original Help build WONDER choice',offered['assist_wonder_10_8_1']['label'])
                self.assertEqual(state,before);self.assertEqual(unit_candidates(state,rules=rules),actions)

    def test_original_trade_role_and_living_actor_required_without_pruning_other_tasks(self):
        for mode in ('settler','diplomat','warrior','air','ship','attack','saved_mismatch','dead','hp_spec_type'):
            state,rules=fixture();spec=rules['units'][0]
            if mode=='settler':spec['role']=5
            elif mode=='diplomat':spec['role']=6
            elif mode=='warrior':spec.update(role=1,attack=1)
            elif mode=='air':spec['domain']=1
            elif mode=='ship':spec['domain']=2
            elif mode=='attack':spec['attack']=1
            elif mode=='saved_mismatch':state['units'][0]['specification']=dict(spec,role=6)
            elif mode=='hp_spec_type':spec['max_hp']=10.0
            else:state['units'][0]['hp']=0
            with self.subTest(mode=mode):
                self.assertEqual(new_tasks(state,rules),{})
                self.assertIn('hold_one_turn',task_candidates(state,rules)[0])

    def test_delivery_excludes_home_here_unknown_water_duplicate_and_unobserved_home(self):
        for mode in ('home','here','unknown','water','duplicate','unknown_home'):
            state,rules=fixture()
            if mode=='home':state['units'][0]['home_city_id']=1
            elif mode=='here':state['units'][0]['x']=10
            elif mode=='unknown':state['map']['tiles']=[t for t in state['map']['tiles'] if (t['x'],t['y'])!=(12,8)]
            elif mode=='water':next(t for t in state['map']['tiles'] if (t['x'],t['y'])==(12,8))['terrain']='Ocean'
            elif mode=='duplicate':state['known_cities'].append(deepcopy(state['known_cities'][0]))
            else:state['units'][0]['home_city_id']=None
            tasks=new_tasks(state,rules)
            with self.subTest(mode=mode):
                if mode in ('home','here'):self.assertNotIn('trade_delivery_10_8',tasks)
                elif mode=='unknown_home':self.assertFalse(any(c['task']=='trade_delivery' for c in tasks.values()))
                else:self.assertNotIn('trade_delivery_12_8',tasks)
        state,rules=fixture();self.assertNotIn('trade_delivery_6_8',new_tasks(state,rules))

    def test_wonder_requires_exact_current_owned_production_and_public_unbuilt_status(self):
        for mode in ('building','unit','different_name','unowned','built','destroyed','missing_status','duplicate_status','unknown_rule'):
            state,rules=fixture();city=state['cities'][1]
            if mode=='building':rules['improvements'][0]['kind']='building'
            elif mode=='unit':city['production']['kind']='unit'
            elif mode=='different_name':city['production']['name']='OTHER Wonder'
            elif mode=='unowned':city['owner']=2
            elif mode in ('built','destroyed'):state['wonders'][0]['status']=mode
            elif mode=='missing_status':state['wonders']=[]
            elif mode=='duplicate_status':state['wonders']*=2
            else:rules['improvements']=[]
            with self.subTest(mode=mode):self.assertFalse(any(c['task']=='assist_wonder' for c in new_tasks(state,rules).values()))

    def test_category_and_target_vectors_retain_every_offered_leaf_and_exact_labels(self):
        state,rules=fixture();flat,leaves=request_for(state,rules)
        category_request,categories=category_request_for(state,rules)
        _validate_questions(category_request['questions'])
        self.assertEqual(category_request['state']['planning']['target_criteria'],flat['questions']['task_choice']['criteria'])
        self.assertEqual({i for c in categories.values() for i in c['target_ids']},set(leaves))
        request,targets=target_request_for(state,categories['trade_delivery'],17,rules)
        self.assertEqual(targets,{k:c for k,c in leaves.items() if c['task']=='trade_delivery'})
        self.assertEqual(request['questions']['task_choice']['criteria'],{k:c['label'] for k,c in targets.items()})
        self.assertEqual(selected_category_target(state,categories['assist_wonder'],rules),leaves['assist_wonder_10_8_1'])
        with self.assertRaises(PlanningError):target_request_for(fresh(state),categories['trade_delivery'],17,rules)

    def test_round_robin_budget_remains_deterministic_and_reports_every_omission(self):
        state,rules=fixture();full,full_summary=task_candidates(state,rules)
        limited,summary=task_candidates(state,rules,limit=5)
        self.assertEqual({c['task'] for c in limited.values()},{'hold','survey','defend','trade_delivery','assist_wonder'})
        self.assertEqual(summary['total'],full_summary['total'])
        self.assertEqual(summary['total']-summary['offered'],sum(summary['omitted_by_task'].values()))
        state['cities'].reverse();state['map']['tiles'].reverse()
        self.assertEqual(task_candidates(state,rules,limit=5),(limited,summary))

    def test_arrival_completes_travel_only_after_independent_legal_move(self):
        for task in ('trade_delivery_10_8','assist_wonder_10_8_1'):
            state,rules=fixture();candidate=task_candidates(state,rules)[0][task]
            plan=make_plan(candidate,state,rules);action=unit_candidates(state,rules=rules)['move_e']
            after=fresh(state);after['units'][0]['x']=10
            result=advance_plan(plan,state,after,action,rules)
            self.assertEqual(result['status'],'complete')
            self.assertIn('not inferred',result['reason']);self.assertIn('arrival choice',result['reason'])
            self.assertEqual(advance_plan(plan,state,after,rules=rules)['status'],'invalidated')

    def test_consumed_unit_changed_production_and_lost_target_never_claim_delivery(self):
        for mode in ('consumed','production','built','lost_city','hidden_tile','home_changed'):
            state,rules=fixture();candidate=task_candidates(state,rules)[0]['assist_wonder_10_8_1']
            plan=make_plan(candidate,state,rules);after=fresh(state)
            if mode=='consumed':after['units']=[]
            elif mode=='production':after['cities'][1]['production']={'kind':'unit','id':1,'name':'TEST Warrior'}
            elif mode=='built':after['wonders'][0]['status']='built'
            elif mode=='lost_city':after['cities'].pop()
            elif mode=='hidden_tile':after['map']['tiles']=[t for t in after['map']['tiles'] if (t['x'],t['y'])!=(10,8)]
            else:after['units'][0]['home_city_id']=1
            with self.subTest(mode=mode):self.assertEqual(advance_plan(plan,state,after,rules=rules)['status'],'invalidated')

    def test_trade_actor_can_request_entry_into_observed_foreign_city_separately(self):
        state,rules=fixture();state['known_cities'][0].update(x=9,y=7)
        for key in ('owner','supply','demand'):state['known_cities'][0].pop(key)
        state['visible_units']=[dict(id=5,owner=2,type_id=1,type='TEST Guard',x=9,y=7)]
        candidate=task_candidates(state,rules)[0]['trade_delivery_9_7']
        plan=make_plan(candidate,state,rules)
        self.assertEqual(plan['status'],'active')
        moves=unit_candidates(state,rules=rules)
        self.assertIn('move_ne',moves)
        self.assertEqual(moves['move_ne']['parameters']['destination'],{'x':9,'y':7})
        self.assertIn('remembered city location, current owner unverified',moves['move_ne']['label'])
        self.assertNotIn('move_ne',candidate)

    def test_foreign_unit_without_unambiguous_observed_city_never_enables_trade_entry(self):
        for mode in ('no_city','duplicate','own','unknown_tile','water'):
            state,rules=fixture();state['known_cities']=[dict(id=99,name='TEST City',x=9,y=7,current_information=False)]
            state['visible_units']=[dict(id=5,owner=2,type_id=1,type='TEST Guard',x=9,y=7)]
            if mode=='no_city':state['known_cities']=[]
            elif mode=='duplicate':state['known_cities']*=2
            elif mode=='own':state['cities'].append(dict(id=2,owner=1,name='TEST Own',x=9,y=7))
            elif mode=='unknown_tile':state['map']['tiles']=[t for t in state['map']['tiles'] if (t['x'],t['y'])!=(9,7)]
            else:next(t for t in state['map']['tiles'] if (t['x'],t['y'])==(9,7))['terrain']='Ocean'
            with self.subTest(mode=mode):self.assertNotIn('move_ne',unit_candidates(state,rules=rules))
