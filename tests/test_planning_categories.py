"""Pure synthetic tests for separate real category and target model requests."""
from copy import deepcopy
import unittest

from civ2.planning import (PlanningError, category_request_for, request_for,
                          selected_category_target, target_request_for, task_candidates)
from civ2.typesafe import _validate_questions
from test_planning import fixture, fresh


class PlanningCategoryTests(unittest.TestCase):
    def test_categories_partition_every_unchanged_original_leaf(self):
        state,rules=fixture(); original,summary=task_candidates(state,rules)
        old_request,old_candidates=request_for(state,rules)
        request,categories=category_request_for(state,rules)
        _validate_questions(request['questions'])
        self.assertEqual(set(categories),{c['task'] for c in original.values()})
        self.assertEqual(request['state']['planning']['candidate_summary'],summary)
        self.assertEqual(request['state']['planning']['targets'],old_request['state']['planning']['targets'])
        self.assertEqual(request['state']['planning']['target_criteria'],old_request['questions']['task_choice']['criteria'])
        offered=[key for category in categories.values() for key in category['target_ids']]
        self.assertEqual(len(offered),len(set(offered)))
        self.assertEqual(set(offered),set(original))
        for name,category in categories.items():
            self.assertEqual(category['target_ids'],[k for k,c in original.items() if c['task']==name])
            self.assertEqual(category['target_count'],len(category['target_ids']))
            self.assertEqual(category['actor'],original['hold_one_turn']['actor'])
            self.assertEqual(category['preconditions'],original['hold_one_turn']['preconditions'])
            self.assertEqual(request['questions']['task_category']['criteria'][name],category['label'])
        self.assertEqual(request_for(state,rules),(old_request,old_candidates))

    def test_each_multi_target_request_keeps_exact_ids_labels_objects_and_prior_selection(self):
        state,rules=fixture(); original,_=task_candidates(state,rules)
        _,categories=category_request_for(state,rules)
        for category in categories.values():
            if category['target_count']==1:continue
            request,leaves=target_request_for(state,category,37,rules)
            expected={k:c for k,c in original.items() if c['task']==category['task']}
            self.assertEqual(leaves,expected)
            self.assertEqual(list(leaves),category['target_ids'])
            self.assertEqual(request['questions']['task_choice']['criteria'],{k:c['label'] for k,c in expected.items()})
            self.assertEqual(request['state']['planning']['category_selection'],{'decision':37,'category':category})
            self.assertEqual(request['state']['planning']['selected_category_target_count'],len(expected))
            _validate_questions(request['questions'])
            self.assertIsNone(selected_category_target(state,category,rules))

    def test_hold_and_sole_defend_complete_explicit_category_without_fake_singleton(self):
        state,rules=fixture(False)
        state['cities']=[dict(id=0,owner=1,name='TEST City',x=8,y=8)]
        original,_=task_candidates(state,rules)
        _,categories=category_request_for(state,rules)
        for name,key in (('hold','hold_one_turn'),('defend','defend_8_8_0')):
            category=categories[name]
            self.assertEqual(category['sole_target'],original[key])
            self.assertIn(original[key]['label'],category['label'])
            self.assertIn('sole offered target',category['label'])
            self.assertEqual(selected_category_target(state,category,rules),original[key])
            with self.assertRaises(PlanningError):target_request_for(state,category,1,rules)

    def test_changed_actor_revision_dataset_and_forged_category_reject(self):
        state,rules=fixture();_,categories=category_request_for(state,rules)
        category=categories['settle']
        for mode in ('revision','actor','extra','missing','order','label','sole'):
            current=deepcopy(state);changed=deepcopy(category)
            if mode=='revision':current=fresh(state)
            if mode=='actor':current['units'][0]['x']+=2
            if mode=='extra':changed['target_ids'].append('settle_30_10')
            if mode=='missing':changed['target_ids'].pop()
            if mode=='order':changed['target_ids'].reverse()
            if mode=='label':changed['label']='SECRET substituted task'
            if mode=='sole':changed['sole_target']={'id':'SECRET'}
            with self.subTest(mode=mode),self.assertRaises(PlanningError):
                target_request_for(current,changed,37,rules)
            with self.subTest(mode=mode),self.assertRaises(PlanningError):
                selected_category_target(current,changed,rules)

    def test_no_singleton_category_and_no_invented_prior_decision(self):
        state,rules=fixture();state['map']['tiles']=[]
        with self.assertRaises(PlanningError):category_request_for(state,rules)
        state,rules=fixture();_,categories=category_request_for(state,rules)
        for identifier in (None,0,-1,True,'1'):
            with self.assertRaises(PlanningError):target_request_for(state,categories['settle'],identifier,rules)

    def test_hidden_state_not_exposed_and_requests_do_not_mutate_sources(self):
        state,rules=fixture();state['map']['hidden_tiles']=[{'x':30,'y':10,'terrain':'SECRET'}]
        prior=deepcopy(state);request,categories=category_request_for(state,rules)
        self.assertNotIn('SECRET',str(request))
        self.assertEqual(state,prior)
        category=deepcopy(categories['settle'])
        target,_=target_request_for(state,category,37,rules)
        target['state']['planning']['category_selection']['category']['target_ids'].clear()
        self.assertEqual(category,categories['settle'])


if __name__=='__main__':unittest.main()
