"""Context compression is a representation change, not an action filter."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from civ2.compact import compact_model_state,expand_model_state,decision_facts,TABLE


class CompactStateTests(unittest.TestCase):
    def fixture(self):
        return {'turn':7,'selected_unit':{'id':1,'owner':1,'type_id':2,'x':4,'y':6},
                'planning':{'targets':{str(i):{'task':'TEST','target':{'x':i*2,'y':0}} for i in range(64)}},
                'owned_unit_roster':[{'id':i,'owner':1,'type_id':2,'x':i*2,'y':0,'hp':10,
                    'goto':None,'order_id':255,'movement_thirds_spent':0,'veteran':False} for i in range(12)],
                'recent_actions':[{'id':'move_e','turn':i,'actor_at_issue':{'id':1,'x':i*2,'y':0},
                    'observation_sha256_at_issue':'a'*64,'reported_outcome':'TEST observed movement, not inferred acceptance'} for i in range(8)],
                'recent_observed_events':[{'id':'b'*64,'image_sha256':'c'*64,
                    'observed_at_utc':'TEST wall time','observation_elapsed_ms':100,'resource_tag':'TEST NOTICE',
                    'last_checkpoint':{'turn':i,'year_raw':-4000+50*i,'observation_sha256':'d'*64},
                    'source':{'game_text_sha256':'e'*64,'resource_sha256':'f'*64,'meaning':'TEST keep'},
                    'observed_text':f'TEST whole historical notice {i}'} for i in range(5)],
                'strategic_playbook':{'science':'TEST all advice retained'},
                'city_labor':{'revision':{'observation_sha256':'9'*64},'cities':[]},
                'map':{'explored_terrain_rows':['??123??'],'known_worked_tiles':[]}}

    def test_roundtrip_preserves_all_decision_facts_and_input_is_immutable(self):
        original=self.fixture();before=deepcopy(original);compact=compact_model_state(original)
        self.assertEqual(original,before)
        self.assertEqual(expand_model_state(compact),decision_facts(original))
        self.assertEqual(compact['owned_unit_roster']['$table'],TABLE)
        self.assertEqual(compact['planning'],original['planning'])
        self.assertEqual(compact['selected_unit'],original['selected_unit'])
        self.assertEqual(compact['map'],original['map'])
        self.assertEqual(compact['strategic_playbook'],original['strategic_playbook'])
        self.assertEqual(compact_model_state(compact),compact)

    def test_only_named_audit_metadata_removed_not_game_ids_dates_or_text(self):
        original=self.fixture();facts=decision_facts(original)
        self.assertEqual(facts['city_labor'],original['city_labor'])
        self.assertEqual(facts['owned_unit_roster'],original['owned_unit_roster'])
        self.assertEqual(facts['recent_observed_events'][0]['source'],{'meaning':'TEST keep'})
        self.assertEqual(facts['recent_observed_events'][0]['last_checkpoint'],{'turn':0,'year_raw':-4000})
        self.assertEqual(facts['recent_observed_events'][0]['observed_text'],original['recent_observed_events'][0]['observed_text'])
        self.assertNotIn('observation_sha256_at_issue',facts['recent_actions'][0])

    def test_sparse_records_null_false_zero_empty_values_roundtrip(self):
        state={'owned_unit_roster':[{'id':i,'name':'TEST actor','nested':{'x':i,'long_field':False},
                    'nullable':None,'zero':0,'empty':{},'list':[]} for i in range(8)]}
        del state['owned_unit_roster'][1]['nullable']
        state['owned_unit_roster'][2]['nested']=None
        state['owned_unit_roster'][3]['nested']={}
        compact=compact_model_state(state)
        self.assertEqual(compact['owned_unit_roster']['$table'],TABLE)
        self.assertEqual(expand_model_state(compact),state)

    def test_corrupted_tables_reject_instead_of_shifting_values(self):
        compact=compact_model_state(self.fixture())
        for case in ('width','duplicate_column','missing_value','overlap'):
            broken=deepcopy(compact);t=broken['owned_unit_roster']
            if case=='width':t['rows'][0].pop()
            elif case=='duplicate_column':t['columns'][1]=t['columns'][0]
            elif case=='missing_value':t['absent']=[[0,[t['columns'].index('id')]]]
            elif case=='overlap':t['columns'][1]=t['columns'][0]+'.child'
            with self.subTest(case=case),self.assertRaises(ValueError):expand_model_state(broken)

    def test_actual_failed_request_all_64_choices_and_history_survive(self):
        p=Path(__file__).resolve().parents[1]/'runs/attempt-010/decisions/000414-request.json'
        if not p.exists():self.skipTest('Private retained request unavailable')
        request=json.loads(p.read_text());old=deepcopy(request)
        request['state']=compact_model_state(request['state'])
        self.assertEqual(request['questions'],old['questions'])
        self.assertEqual(len(request['questions']['task_choice']['criteria']),64)
        self.assertEqual(expand_model_state(request['state']),decision_facts(old['state']))
        self.assertLess(len(json.dumps(request)),len(json.dumps(old))*.8)

    def test_unknown_or_extra_encoding_metadata_rejects(self):
        for case in ('revision','scope','extra','table_revision','table_extra'):
            compact=compact_model_state(self.fixture())
            if case in ('revision','scope'):compact['model_state_encoding'][case]='TEST changed'
            elif case=='extra':compact['model_state_encoding']['extra']='TEST'
            elif case=='table_revision':compact['owned_unit_roster']['$table']='unknown'
            else:compact['owned_unit_roster']['extra']='TEST'
            with self.subTest(case=case),self.assertRaises(ValueError):expand_model_state(compact)


if __name__=='__main__':unittest.main()
