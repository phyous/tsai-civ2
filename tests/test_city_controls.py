"""Synthetic TEST city controls; no game, model or purchase calls."""
from copy import deepcopy
import json
import unittest

from civ2.city_controls import (CityControlError, ForcedCityControl,
    city_control_candidates, city_control_request_for, validate_city_control)


def inputs():
    state=dict(turn=7,year_raw=-3700,evidence={'save_sha256':'a'*64},
        selected_unit_id=None,units=[],visible_units=[],known_cities=[],wonders=[],
        player=dict(id=1,tribe='TEST Romans',government_id=1,government='Despotism',
            treasury=50,science_rate=60,tax_rate=40,luxury_rate=0,
            known_technology_ids=[],known_technologies=[]),
        settings=dict(round_world=True),
        map=dict(coordinate_width=32,width=16,height=16,tiles=[dict(x=2,y=2,
            terrain_id=2,terrain='Grassland',river=False,known_improvements=[])]),
        cities=[dict(id=0,owner=1,name='TEST Rome',x=2,y=2,size=2,disorder=False,
            production={'name':'Warriors'},food_stored=0,shields_stored=3,
            food_produced=4,shields_produced=2)],diplomacy=[])
    buttons=[dict(text=text,center=center,control='button',confidence=1.,enabled=None)
             for text,center in [('Buy',[540,335]),('Change',[610,335]),
                                 ('Info',[540,380]),('Exit',[610,458])]]
    screen=dict(kind='city_screen',supported=True,id='city_screen',
        title='City of TEST Rome, 3700 B.C. Population 20,000 Treasury: 50 Gold',
        sha256='b'*64,width=640,height=480,options=deepcopy(buttons),buttons=buttons)
    return state,screen,dict(advances=[],units=[],terrain=[])


def reviewed(actions=()):
    return dict(city_id=0,city_name='TEST Rome',year_raw=-3700,actions=list(actions))


class CityControlTests(unittest.TestCase):
    def test_three_controls_bind_exact_city_save_image_and_observed_centers(self):
        state,screen,rules=inputs();actions=city_control_candidates(state,screen,rules=rules)
        self.assertEqual(set(actions),{'change_production','open_buy_quote','exit_city'})
        for action in actions.values():
            self.assertEqual(action['kind'],'city_control')
            self.assertEqual(action['actor'],dict(kind='city',id=0,owner=1,name='TEST Rome',x=2,y=2))
            binding=action['preconditions']
            self.assertEqual((binding['save_sha256'],binding['image_sha256'],binding['turn']),('a'*64,'b'*64,7))
            self.assertEqual(binding['year_raw'],-3700)
            self.assertEqual(binding['observed_city_title'],screen['title'])
            p=action['parameters'];button=screen['buttons'][p['button_index']]
            self.assertEqual(p['center'],button['center']);self.assertEqual(p['observed_text'],button['text'])
            self.assertEqual(p['control'],'button')
            validate_city_control(action,state,screen,rules=rules)

    def test_buy_only_requests_quote_without_cost_confirmation_or_purchase(self):
        state,screen,rules=inputs();action=city_control_candidates(state,screen,rules=rules)['open_buy_quote']
        p=action['parameters']
        self.assertTrue(p['only_open_menu'])
        self.assertEqual(p['expected_screen'],'buy_quote')
        self.assertTrue(p['confirmation_requires_separate_choice'])
        self.assertFalse(p['purchase_authorized'])
        self.assertNotIn('cost',p);self.assertNotIn('price',p);self.assertNotIn('confirm',p)
        state['player']['treasury']=0
        # No price is inferred from an owned treasury or production counter.
        self.assertIn('open_buy_quote',city_control_candidates(state,screen,rules=rules))

    def test_review_scope_omits_only_reviewed_controls_and_retains_exit(self):
        state,screen,rules=inputs();record=reviewed(['change_production'])
        actions=city_control_candidates(state,screen,record,rules)
        self.assertEqual(set(actions),{'open_buy_quote','exit_city'})
        self.assertEqual(actions['exit_city']['preconditions']['reviewed_action_ids'],['change_production'])
        with self.assertRaises(CityControlError):
            validate_city_control(city_control_candidates(state,screen,rules=rules)['change_production'],state,screen,record,rules)

    def test_only_exit_has_no_fabricated_choice_vector(self):
        state,screen,rules=inputs();record=reviewed(['change_production','open_buy_quote'])
        actions=city_control_candidates(state,screen,record,rules)
        self.assertEqual(list(actions),['exit_city'])
        self.assertFalse(actions['exit_city']['parameters']['only_open_menu'])
        with self.assertRaises(ForcedCityControl): city_control_request_for(state,screen,actions,record,rules)

    def test_review_ledger_cannot_cross_city_or_year_or_remove_exit(self):
        state,screen,rules=inputs()
        for changes in ({'city_id':1},{'city_name':'TEST Veii'},{'year_raw':-3650},
                        {'actions':['exit_city']},{'actions':['purchase']},{'extra':True}):
            with self.subTest(changes=changes),self.assertRaises(CityControlError):
                city_control_candidates(state,screen,{**reviewed(),**changes},rules)
        with self.assertRaises(CityControlError): city_control_candidates(state,screen,['open_buy_quote'],rules)
        state['year_raw']=-3650;screen['title']=screen['title'].replace('3700','3650')
        with self.assertRaises(CityControlError): city_control_candidates(state,screen,reviewed(),rules)
        self.assertEqual(len(city_control_candidates(state,screen,rules=rules)),3)

    def test_request_has_actual_action_vector_and_separate_strategy_advice(self):
        state,screen,rules=inputs();actions=city_control_candidates(state,screen,rules=rules)
        request=city_control_request_for(state,screen,actions,rules=rules)
        self.assertEqual(set(request['questions']),{'city_action','empire_strategy'})
        self.assertEqual(request['questions']['city_action']['criteria'],{k:a['label'] for k,a in actions.items()})
        review=request['state']['city_control_review']
        self.assertEqual(review['actor']['name'],'TEST Rome')
        self.assertIn('separate Jev choice',review['scope'])
        self.assertNotIn('probabilities',json.dumps(request))

    def test_newly_founded_or_foreign_city_needs_owned_save_identity(self):
        for mode in ('missing','foreign','duplicate_name','duplicate_id','bad_coordinate'):
            state,screen,rules=inputs()
            if mode=='missing':state['cities']=[]
            elif mode=='foreign':state['cities'][0]['owner']=2
            elif mode=='duplicate_name':state['cities'].append(dict(state['cities'][0],id=1,x=4))
            elif mode=='duplicate_id':state['cities'].append(dict(state['cities'][0],name='TEST Other',x=4))
            else:state['cities'][0]['x']=None
            with self.subTest(mode=mode),self.assertRaises(CityControlError):city_control_candidates(state,screen,rules=rules)

    def test_wrong_or_unreadable_city_year_and_unrecognized_screen_refuse(self):
        state,screen,rules=inputs()
        for changes in ({'title':'Original city screen'}, {'title':'City of TEST Veii, 3700 B.C.'},
                        {'title':'City of TEST Rome, 3650 B.C.'},{'supported':False},
                        {'kind':'production_choice'},{'sha256':'invalid'},{'width':True}):
            with self.subTest(changes=changes),self.assertRaises(CityControlError):
                city_control_candidates(state,{**screen,**changes},rules=rules)
        state['year_raw']=50;screen['title']='City of TEST Rome, 50 A.D., Treasury: 50 Gold'
        self.assertEqual(city_control_candidates(state,screen,rules=rules)['exit_city']['preconditions']['year_raw'],50)

    def test_missing_disabled_or_uncertain_buttons_are_never_invented(self):
        state,screen,rules=inputs()
        for field,value in [('enabled',False),('confidence',.5)]:
            partial=deepcopy(screen);partial['buttons'][0][field]=value
            self.assertNotIn('open_buy_quote',city_control_candidates(state,partial,rules=rules))
        partial=deepcopy(screen);partial['buttons']=[b for b in partial['buttons'] if b['text']!='Buy']
        self.assertNotIn('open_buy_quote',city_control_candidates(state,partial,rules=rules))
        screen['buttons']=[b for b in screen['buttons'] if b['text']!='Exit']
        with self.assertRaises(CityControlError):city_control_candidates(state,screen,rules=rules)

    def test_duplicate_labels_centers_and_outside_image_buttons_refuse(self):
        state,screen,rules=inputs()
        for mode in ('duplicate_label','duplicate_center','outside','nan','boolean_center'):
            bad=deepcopy(screen)
            if mode=='duplicate_label':bad['buttons'].append(deepcopy(bad['buttons'][0]))
            elif mode=='duplicate_center':bad['buttons'][1]['center']=bad['buttons'][0]['center']
            elif mode=='outside':bad['buttons'][0]['center']=[650,335]
            elif mode=='nan':bad['buttons'][0]['confidence']=float('nan')
            else:bad['buttons'][0]['center']=[True,335]
            with self.subTest(mode=mode),self.assertRaises(CityControlError):city_control_candidates(state,bad,rules=rules)

    def test_stale_save_image_turn_actor_and_tampered_parameters_refuse(self):
        state,screen,rules=inputs();action=city_control_candidates(state,screen,rules=rules)['open_buy_quote']
        for mode in ('save','image','turn','actor','center','purchase'):
            s,c,a=deepcopy(state),deepcopy(screen),deepcopy(action)
            if mode=='save':s['evidence']['save_sha256']='c'*64
            elif mode=='image':c['sha256']='c'*64
            elif mode=='turn':s['turn']+=1
            elif mode=='actor':s['cities'][0]['x']=4
            elif mode=='center':a['parameters']['center']=[12,12]
            else:a['parameters']['purchase_authorized']=True
            with self.subTest(mode=mode),self.assertRaises(CityControlError):validate_city_control(a,s,c,rules=rules)

    def test_request_rejects_swapped_labels_and_module_never_mutates_sources(self):
        state,screen,rules=inputs();before=deepcopy((state,screen,rules))
        actions=city_control_candidates(state,screen,rules=rules)
        city_control_request_for(state,screen,actions,rules=rules)
        self.assertEqual((state,screen,rules),before)
        actions['open_buy_quote']['label']='Purchase now for 50 gold'
        with self.assertRaises(CityControlError):city_control_request_for(state,screen,actions,rules=rules)

    def test_recovered_owned_city_name_requires_exact_raw_and_save_provenance(self):
        state,screen,rules=inputs();screen['title']=screen['title'].replace('TEST Rome','TEST Rone')
        screen['observed_city_name']='TEST Rome'
        with self.assertRaises(CityControlError):city_control_candidates(state,screen,rules=rules)
        screen['city_name_recovery']=dict(source='Unique one-edit match to owned city in original save',
            ocr_text='TEST Rone',canonical_name='TEST Rome',city_id=0,save_sha256='a'*64,source_line=0)
        action=city_control_candidates(state,screen,rules=rules)['exit_city']
        self.assertEqual(action['actor']['name'],'TEST Rome')
        self.assertIn('TEST Rone',action['preconditions']['observed_city_title'])
        for field,value in [('city_id',1),('save_sha256','c'*64),('ocr_text','Other')]:
            bad=deepcopy(screen);bad['city_name_recovery'][field]=value
            with self.assertRaises(CityControlError):city_control_candidates(state,bad,rules=rules)


if __name__=='__main__':unittest.main()
