"""Extended v1 record representation: exact facts, identities, order and types."""
from copy import deepcopy
import json
from pathlib import Path
from unittest import TestCase
from civ2.compact import (TABLE,ENCODING,EXTENDED_ENCODING,compact_model_state,
                         expand_model_state,decision_facts,_table)


def state():
    targets={}
    for i in range(30):
        key=f'TEST survey {i}'
        target={'x':i*2,'y':i,'unknown_neighbors':[{'x':i*2+j,'y':i+j}for j in range(5)]}
        if i%3==0:target={'id':i,'x':i*2,'y':i}
        targets[key]={'task':'survey' if i%3 else 'defend','target':target}
    return {'turn':7,'planning':{'targets':targets,'target_criteria':{k:'TEST exact '+k for k in targets}},
            'city_labor':{'cities':[{'id':i,'available':True,'nullable':None,'population':4,
                'happiness':{'happy':0,'unhappy':0},'radius':[[i,j,False,None]for j in range(5)]}for i in range(8)]}}


class NestedCompactTests(TestCase):
    def test_nested_keyed_grouped_records_roundtrip_preserving_key_order(self):
        original=state();before=deepcopy(original);encoded=compact_model_state(original)
        self.assertEqual(original,before)
        self.assertEqual(expand_model_state(encoded),original)
        self.assertEqual(list(expand_model_state(encoded)['planning']['targets']),list(original['planning']['targets']))
        self.assertEqual(encoded['model_state_encoding'],EXTENDED_ENCODING)
        table=encoded['planning']['targets'];self.assertEqual(table['$table'],TABLE)
        self.assertIn('groups',table)
        self.assertTrue(any('nested_columns' in group['records'] for group in table['groups']))
        self.assertLess(len(json.dumps(encoded)),len(json.dumps(original))*.85)
        self.assertEqual(compact_model_state(encoded),encoded)

    def test_shared_values_never_conflate_bool_number_missing_null_or_empty(self):
        values=[False,0,0.0,True,1,1.0,None,{},[]]
        records=[{'id':i,'same':'TEST common value with enough bytes for shared column', 'v':v}for i,v in enumerate(values)]
        records.append({'id':99,'same':records[0]['same']})
        original={'owned_unit_roster':records};encoded=compact_model_state(original)
        decoded=expand_model_state(encoded)
        self.assertEqual(json.dumps(decoded,sort_keys=True),json.dumps(original,sort_keys=True))
        self.assertNotIn('v',decoded['owned_unit_roster'][-1])

    def test_legacy_requests_remain_exactly_decodable_and_can_be_reencoded(self):
        legacy={'turn':1,'planning':{'old':{'$table':TABLE,'columns':['id','nested.x'],
            'rows':[[1,False],[2,None]],'absent':[[1,[1]]]}},'model_state_encoding':deepcopy(ENCODING)}
        original=deepcopy(legacy);expected={'turn':1,'planning':{'old':[{'id':1,'nested':{'x':False}},{'id':2}]}}
        self.assertEqual(expand_model_state(legacy),expected)
        self.assertEqual(expand_model_state(compact_model_state(legacy)),expected)
        self.assertEqual(legacy,original)
        bad=deepcopy(legacy);bad['planning']['old']['shared']={'TEST':1}
        with self.assertRaises(ValueError):expand_model_state(bad)

    def test_grouped_malformed_order_coverage_keys_and_schema_reject(self):
        original=compact_model_state(state());self.assertIn('groups',original['planning']['targets'])
        for case in ('duplicate_index','missing_index','index_bool','negative','extra','key_duplicate','key_length','key_null','group_extra','row_mismatch'):
            bad=deepcopy(original);t=bad['planning']['targets'];g=t['groups'][0]
            if case=='duplicate_index':g['indexes'][1]=g['indexes'][0]
            if case=='missing_index':t['length']+=1;t['keys'].append('TEST missing')
            if case=='index_bool':g['indexes'][0]=True
            if case=='negative':g['indexes'][0]=-1
            if case=='extra':t['extra']='TEST'
            if case=='key_duplicate':t['keys'][1]=t['keys'][0]
            if case=='key_length':t['keys'].pop()
            if case=='key_null':t['keys'][0]=None
            if case=='group_extra':g['extra']=0
            if case=='row_mismatch':g['indexes'].pop()
            with self.subTest(case=case),self.assertRaises(ValueError):expand_model_state(bad)

    def test_nested_shared_overlap_unknown_columns_and_bad_width_reject(self):
        base={'$table':TABLE,'columns':['id','neighbors'],'rows':[[1,[[2,3]]],[2,[]]],
              'shared':{'metadata.ok':True},'nested_columns':{'neighbors':['x','y']}}
        for case in ('shared_overlap','shared_parent','nested_missing','nested_duplicate','nested_width','nested_nonrow','empty_columns','bad_keys'):
            t=deepcopy(base)
            if case=='shared_overlap':t['shared']['id']=1
            if case=='shared_parent':t['shared']['metadata']='TEST scalar'
            if case=='nested_missing':t['nested_columns']['missing']=['x']
            if case=='nested_duplicate':t['nested_columns']['neighbors']=['x','x']
            if case=='nested_width':t['rows'][0][1][0].pop()
            if case=='nested_nonrow':t['rows'][0][1]='TEST not rows'
            if case=='empty_columns':t['nested_columns']['neighbors']=[]
            if case=='bad_keys':t['keys']=['same','same']
            with self.subTest(case=case),self.assertRaises(ValueError):
                expand_model_state({'planning':t,'model_state_encoding':deepcopy(EXTENDED_ENCODING)})

    def test_present_parent_empty_object_never_absorbs_child_column(self):
        for shared in (False,True):
            table={'$table':TABLE,'columns':['a','a.b'],'rows':[[{},7]]}
            if shared:table={'$table':TABLE,'columns':['a.b'],'rows':[[7]],'shared':{'a':{}}}
            with self.subTest(shared=shared),self.assertRaises(ValueError):
                expand_model_state({'planning':table,'model_state_encoding':EXTENDED_ENCODING})
        # Mutually exclusive paths in different sparse records are legitimate.
        table={'$table':TABLE,'columns':['a','a.b'],'rows':[[{},None],[None,7]],'absent':[[0,[1]],[1,[0]]]}
        decoded=expand_model_state({'planning':table,'model_state_encoding':EXTENDED_ENCODING})
        self.assertEqual(decoded['planning'],[{'a':{}},{'a':{'b':7}}])

    def test_literal_reserved_marker_rejects_instead_of_changing_game_data(self):
        for value in ({'$table':TABLE,'columns':['x'],'rows':[[1]]},{'$table':'TEST literal'}):
            with self.assertRaises(ValueError):compact_model_state({'planning':{'TEST':value}})
        original={'planning':{'TEST':{'shared':{'x':1},'keys':['TEST'],'groups':[]}}}
        self.assertEqual(expand_model_state(compact_model_state(original)),original)

    def test_actual_failed_552_all_facts_and_questions_preserved_with_reduction(self):
        path=Path('runs/attempt-012/decisions/000552-request.json')
        if not path.exists():self.skipTest('Private actual request unavailable')
        before=json.loads(path.read_text());after=deepcopy(before)
        decoded=expand_model_state(before['state'])
        after['state']=compact_model_state(before['state'])
        self.assertEqual(expand_model_state(after['state']),decoded)
        self.assertEqual(after['questions'],before['questions'])
        self.assertEqual(len(decoded['planning']['targets']),64)
        self.assertEqual(list(expand_model_state(after['state'])['planning']['targets']),list(decoded['planning']['targets']))
        self.assertLess(len(json.dumps(after)),len(json.dumps(before))*.92)
