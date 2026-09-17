"""Factual strategic context must not create choices or expose foreign records."""
from copy import deepcopy
import json
import unittest
from test_policy import fixture,rules
from civ2.policy import dialog_request_for,model_state

class StrategyContextTests(unittest.TestCase):
    def test_garrisons_and_pipeline_count_owned_checkpoint_facts_only(self):
        s=fixture();r=rules();s['units'][0]['hp']=10
        s['cities']=[dict(id=0,owner=1,name='TEST Rome',x=8,y=8,size=2,production={'kind':'unit','id':0}),
                     dict(id=1,owner=1,name='TEST Veii',x=10,y=8,size=1,production={'kind':'unit','id':1})]
        warrior={**deepcopy(s['units'][0]),'id':8,'type_id':1,'type':'Warriors','x':10,'specification':r['units'][1]}
        foreign={**deepcopy(warrior),'id':99,'owner':2,'type':'SECRET FOREIGN','x':8}
        s['units'] += [warrior,foreign]
        before=deepcopy(s);m=model_state(s,r)['empire_readiness']
        self.assertEqual((m['owned_armed_unit_count'],m['owned_worker_unit_count']),(1,1))
        self.assertEqual(m['city_garrisons'][0]['owned_unit_ids'],[7])
        self.assertEqual(m['city_garrisons'][0]['armed_unit_ids'],[])
        self.assertEqual(m['city_garrisons'][1]['armed_unit_ids'],[8])
        self.assertEqual([c['city_id'] for c in m['worker_production_pipeline']],[0])
        self.assertNotIn('SECRET',json.dumps(m));self.assertNotIn('completion_turn',json.dumps(m))
        self.assertEqual(s,before)

    def test_unavailable_specs_are_reported_and_not_invented(self):
        s=fixture();s['units'][0].pop('specification')
        m=model_state(s,{})['empire_readiness']
        self.assertEqual(m['unknown_unit_specification_count'],1)
        self.assertEqual(m['owned_worker_unit_count'],0)

    def test_known_monarchy_is_an_available_concept_not_an_adopted_regime(self):
        s=fixture();r=rules();s['player'].update(government_id=1,government='Despotism',known_technology_ids=[3])
        r['advances'].append({'id':3,'name':'Monarchy','code':'Mon','prerequisites':['nil','nil']})
        m=model_state(s,r)['empire_readiness']
        self.assertEqual(m['current_government'],'Despotism')
        self.assertEqual([g['name'] for g in m['available_government_concepts']],['Monarchy'])
        self.assertTrue(m['available_government_concepts'][0]['native_menu_verification_required'])
        self.assertIn('does not adopt',m['government_adoption_note'])

    def test_offered_defender_has_original_specs_even_when_no_army_exists(self):
        s=fixture();s['units']=[];s['selected_unit_id']=None;r=rules()
        d={'id':'production_choice','kind':'production_choice','title':'TEST production',
           'sha256':'b'*64,'width':640,'height':480,
           'options':[{'text':'Settlers','center':[200,150]},{'text':'Warriors','center':[200,175]}]}
        request,actions=dialog_request_for(s,d,r)
        context=request['state']['mandatory_dialog']['offered_original_specifications']
        self.assertEqual(context['options']['option_1']['shield_cost'],10)
        self.assertEqual(context['options']['option_1']['attack'],1)
        self.assertEqual(context['options']['option_0']['role'],5)
        self.assertNotIn('Trireme',json.dumps(context))
        self.assertEqual(request['questions']['dialog_action']['criteria'],{k:a['label'] for k,a in actions.items()})
        r['improvements']=[{'id':1,'name':'Warriors','shield_cost':50}]
        ambiguous,_=dialog_request_for(s,d,r)
        self.assertEqual(ambiguous['state']['mandatory_dialog']['offered_original_specifications']['unmatched_option_ids'],['option_1'])

if __name__=='__main__':unittest.main()
