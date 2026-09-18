"""Lossless array columns: exact values, order, sparse exceptions and old traces."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from civ2 import compact as c


def fixture():
    cities=[]
    for city in range(12):
        radius=[[city*2+i,i,False,False,'explored',i%5,False,[],[1,0,0]] for i in range(21)]
        radius[16][2:4]=[True,True]
        radius[3][6]=True;radius[3][7]=['irrigation']
        cities.append(dict(city_id=city,available=True,radius=radius))
    return dict(turn=27,selected_unit=dict(id=7,x=10,y=8),
                city_labor=dict(radius_columns=['x','y','worked','center','knowledge','terrain','river','works','yield'],cities=cities),
                planning=dict(targets={f'TEST_{i}':dict(task='survey',target=dict(x=i*2,y=i)) for i in range(64)}),
                recent_actions=[dict(id='TEST',turn=1,reported_outcome='TEST exact observed outcome')])


def wrapped(matrix,encoding=None):
    return dict(city_labor=matrix,model_state_encoding=deepcopy(c.MATRIX_ENCODING if encoding is None else encoding))


class MatrixCompactTests(unittest.TestCase):
    def test_full_state_roundtrip_order_candidates_and_idempotence(self):
        original=fixture();before=deepcopy(original)
        encoded=c.compact_model_state(original)
        self.assertEqual(encoded['model_state_encoding'],c.MATRIX_ENCODING)
        decoded=c.expand_model_state(encoded)
        self.assertEqual(decoded,c.decision_facts(original))
        self.assertEqual(list(decoded['planning']['targets']),list(original['planning']['targets']))
        self.assertEqual(len(decoded['planning']['targets']),64)
        self.assertEqual(original,before)
        self.assertEqual(c.compact_model_state(encoded),encoded)
        with patch.object(c,'_matrix_cells',side_effect=deepcopy):
            previous=c.compact_model_state(original)
        self.assertEqual(previous['model_state_encoding'],c.EXTENDED_ENCODING)
        self.assertLess(c._size(encoded),c._size(previous)*.8)
        self.assertEqual(c.expand_model_state(c.compact_model_state(previous)),decoded)

    def test_sparse_columns_preserve_null_bool_float_empty_and_dictionary_order(self):
        variants=[False,0,0.0,True,1,1.0,None,[],{},dict(a=1,b=2),dict(b=2,a=1)]
        original=[[i,'TEST repeated value for exact column encoding',deepcopy(variants[i%len(variants)]),None]
                  for i in range(88)]
        matrix=c._matrix(original)
        self.assertEqual(matrix['$matrix'],c.MATRIX)
        decoded=c.expand_model_state(wrapped(matrix))['city_labor']
        # Python equality alone conflates bool/int/float and ignores key order.
        self.assertEqual(json.dumps(decoded),json.dumps(original))
        self.assertEqual(list(decoded[9][2]),['a','b'])
        self.assertEqual(list(decoded[10][2]),['b','a'])

    def test_shared_mutable_values_decode_to_independent_cells(self):
        matrix={'$matrix':c.MATRIX,'length':5,'columns':[
            {'value':{'TEST':[]},'except':[[2,{'TEST':['changed']}]]},[0,1,2,3,4]]}
        decoded=c.expand_model_state(wrapped(matrix))['city_labor']
        decoded[0][0]['TEST'].append('one row only')
        self.assertEqual(decoded[1][0],{'TEST':[]})
        self.assertEqual(decoded[2][0],{'TEST':['changed']})
        self.assertEqual(matrix['columns'][0]['value'],{'TEST':[]})

    def test_nested_matrices_in_dense_cells_defaults_and_exceptions(self):
        inner={'$matrix':c.MATRIX,'length':4,'columns':[[1,2,3,4],{'value':False}]}
        other={'$matrix':c.MATRIX,'length':2,'columns':[[9,8],{'value':None}]}
        outer={'$matrix':c.MATRIX,'length':3,'columns':[
            {'value':inner,'except':[[1,other]]},[other,None,inner]]}
        decoded=c.expand_model_state(wrapped(outer))['city_labor']
        a=[[1,False],[2,False],[3,False],[4,False]];b=[[9,None],[8,None]]
        self.assertEqual(decoded,[[a,b],[b,None],[a,a]])
        decoded[0][0][0][0]=777
        self.assertEqual(decoded[2][0][0][0],1)
        self.assertEqual(decoded[2][1][0][0],1)

    def test_table_metadata_is_unchanged_and_nested_record_cells_decode(self):
        neighbors=[[i,False,'TEST common value'] for i in range(20)]
        table={'$table':c.TABLE,'columns':['id','neighbors'],'rows':[[1,deepcopy(neighbors)],[2,deepcopy(neighbors)]],
               'nested_columns':{'neighbors':['x','flag','label']},'keys':['first','second']}
        old=wrapped(table,c.EXTENDED_ENCODING);before=deepcopy(old)
        packed=c._matrix_cells(old);packed['model_state_encoding']=deepcopy(c.MATRIX_ENCODING)
        self.assertIsInstance(packed['city_labor']['rows'],list)
        self.assertEqual(packed['city_labor']['columns'],table['columns'])
        self.assertEqual(packed['city_labor']['nested_columns'],table['nested_columns'])
        self.assertEqual(packed['city_labor']['rows'][0][1]['$matrix'],c.MATRIX)
        self.assertEqual(c.expand_model_state(packed),c.expand_model_state(old))
        self.assertEqual(old,before)
        grouped={'$table':c.TABLE,'length':2,'keys':['first','second'],
                 'groups':[{'indexes':[0,1],'records':dict(table,keys=None)}]}
        grouped['groups'][0]['records'].pop('keys')
        old=wrapped(grouped,c.EXTENDED_ENCODING)
        packed=c._matrix_cells(old);packed['model_state_encoding']=deepcopy(c.MATRIX_ENCODING)
        self.assertEqual(packed['city_labor']['groups'][0]['indexes'],[0,1])
        self.assertEqual(c.expand_model_state(packed),c.expand_model_state(old))

    def test_malformed_matrix_dimensions_defaults_and_exceptions_reject(self):
        base={'$matrix':c.MATRIX,'length':4,'columns':[[1,2,3,4],{'value':False,'except':[[2,True]]}]}
        for mode in ('marker','extra','missing','bool_length','negative','zero','huge','cells','few_columns','many_columns','short_vector','bad_column','default_extra','default_missing','bad_exceptions','duplicate','unordered','bool_index','negative_index','overflow','entry_width','wrong_entry','nested_marker'):
            matrix=deepcopy(base)
            if mode=='marker':matrix['$matrix']='TEST unsupported version'
            elif mode=='extra':matrix['extra']=1
            elif mode=='missing':matrix.pop('columns')
            elif mode=='bool_length':matrix['length']=True
            elif mode=='negative':matrix['length']=-1
            elif mode=='zero':matrix['length']=0
            elif mode=='huge':matrix['length']=10001
            elif mode=='cells':matrix['length']=10000;matrix['columns']=[{'value':None}]*11
            elif mode=='few_columns':matrix['columns'].pop()
            elif mode=='many_columns':matrix['columns']=[{'value':None}]*65
            elif mode=='short_vector':matrix['columns'][0].pop()
            elif mode=='bad_column':matrix['columns'][0]=None
            elif mode=='default_extra':matrix['columns'][1]['extra']=0
            elif mode=='default_missing':matrix['columns'][1].pop('value')
            elif mode=='bad_exceptions':matrix['columns'][1]['except']={}
            elif mode=='duplicate':matrix['columns'][1]['except']=[[2,True],[2,False]]
            elif mode=='unordered':matrix['columns'][1]['except']=[[2,True],[1,False]]
            elif mode=='bool_index':matrix['columns'][1]['except']=[[True,True]]
            elif mode=='negative_index':matrix['columns'][1]['except']=[[-1,True]]
            elif mode=='overflow':matrix['columns'][1]['except']=[[4,True]]
            elif mode=='entry_width':matrix['columns'][1]['except']=[[1]]
            elif mode=='wrong_entry':matrix['columns'][1]['except']=[dict(index=1,value=True)]
            else:matrix['columns'][1]['value']={'$matrix':'TEST invalid'}
            with self.subTest(mode=mode),self.assertRaises(ValueError):c.expand_model_state(wrapped(matrix))

    def test_sparse_table_missing_and_null_cells_remain_distinct(self):
        radius=[[i,False,None,'TEST repeated terrain'] for i in range(20)]
        table={'$table':c.TABLE,'columns':['id','radius'],'rows':[[1,radius],[2,None],[3,None]],'absent':[[1,[1]]]}
        before=wrapped(table,c.EXTENDED_ENCODING);packed=c._matrix_cells(before)
        packed['model_state_encoding']=deepcopy(c.MATRIX_ENCODING)
        decoded=c.expand_model_state(packed)['city_labor']
        self.assertNotIn('radius',decoded[1]);self.assertIsNone(decoded[2]['radius'])
        self.assertEqual(decoded,c.expand_model_state(before)['city_labor'])

    def test_earlier_encodings_keep_their_original_interpretation(self):
        for encoding in (c.ENCODING,c.EXTENDED_ENCODING):
            old=wrapped({'$table':c.TABLE,'columns':['id','value'],'rows':[[1,False],[2,None]]},encoding)
            before=deepcopy(old)
            self.assertEqual(c.expand_model_state(old)['city_labor'],[{'id':1,'value':False},{'id':2,'value':None}])
            self.assertEqual(c.expand_model_state(c.compact_model_state(old)),c.expand_model_state(old))
            self.assertEqual(old,before)
            # Older schemas did not reserve this key: keep its literal meaning.
            literal=wrapped({'$matrix':'TEST old literal'},encoding)
            self.assertEqual(c.expand_model_state(literal)['city_labor'],{'$matrix':'TEST old literal'})
        with self.assertRaises(ValueError):c.compact_model_state({'city_labor':{'$matrix':'TEST literal'}})
        broken=c.compact_model_state(fixture());broken['model_state_encoding']['array_matrices']='TEST changed meaning'
        with self.assertRaises(ValueError):c.expand_model_state(broken)

    def test_unprofitable_or_irregular_arrays_keep_previous_representation(self):
        for value in ([[1,2],[3,4]],[[1,2],[3],[4,5],[6,7]],[[1],[2],[3],[4]],[],[False,0,None,[]]):
            self.assertEqual(c._matrix(deepcopy(value)),value)
        tiny={'turn':4,'city_labor':{'radius':[[1,2],[3,4]]}}
        self.assertEqual(c.compact_model_state(tiny)['model_state_encoding'],c.EXTENDED_ENCODING)

    def test_optional_actual_latest_successful_requests_roundtrip_without_candidate_loss(self):
        found=0
        for attempt in ('010','011','012'):
            folder=Path(f'runs/attempt-{attempt}/decisions')
            responses=sorted(folder.glob('*-response.json'))[-30:]
            for response in responses:
                path=response.with_name(response.name.replace('-response','-request'))
                if not path.exists():continue
                request=json.loads(path.read_text());before=deepcopy(request)
                decoded=c.expand_model_state(request['state'])
                compact=c.compact_model_state(request['state'])
                self.assertEqual(c.expand_model_state(compact),decoded)
                self.assertEqual(json.dumps(c.expand_model_state(compact),sort_keys=True),json.dumps(decoded,sort_keys=True))
                if 'planning' in decoded and 'targets' in decoded['planning']:
                    self.assertEqual(list(c.expand_model_state(compact)['planning']['targets']),list(decoded['planning']['targets']))
                after={**request,'state':compact}
                self.assertEqual(after['questions'],request['questions'])
                if request['state']['model_state_encoding']==c.MATRIX_ENCODING:
                    self.assertEqual(after,request)
                else:
                    self.assertLess(c._size(after),c._size(request)*.97)
                self.assertEqual(request,before);found+=1
        if not found:self.skipTest('Private actual requests unavailable')
        self.assertGreaterEqual(found,30)


if __name__=='__main__':unittest.main()
