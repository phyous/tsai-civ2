"""Synthetic TEST observations; no gameplay or model calls."""
from copy import deepcopy
import unittest

from civ2.empire import EmpireError,ForcedEmpireAction,empire_candidates,empire_request_for,validate_empire_action,makeempire_candidates


def inputs():
    state=dict(turn=7,year_raw=-3700,evidence={'save_sha256':'a'*64},
        selected_unit_id=None,units=[],visible_units=[],known_cities=[],wonders=[],
        player=dict(id=1,tribe='TEST Romans',leader='TEST Caesar',government_id=1,government='Despotism',
            treasury=50,science_rate=60,tax_rate=40,luxury_rate=0,known_technology_ids=[],known_technologies=[]),
        settings=dict(round_world=True,difficulty='Prince',barbarians='Restless Tribes'),
        map=dict(coordinate_width=32,width=16,height=16,tiles=[dict(x=2,y=2,terrain_id=2,terrain='Grassland',river=False,known_improvements=[])]),
        cities=[dict(id=0,owner=1,name='TEST Rome',x=2,y=2,size=2,disorder=False,production={'name':'Warriors'},
            food_stored=0,shields_stored=3,food_produced=4,shields_produced=2)],diplomacy=[])
    screen=dict(kind='end_turn',supported=True,title='End of Turn',sha256='b'*64,width=640,height=480,options=[])
    rules=dict(advances=[dict(id=54,name='Monarchy',code='Mon',prerequisites=['Cer','CoL'])],units=[],terrain=[])
    return state,screen,rules


class EmpireTests(unittest.TestCase):
    def test_repeated_unit_build_and_missing_worker_pipeline_are_actionable_facts(self):
        s,screen,r=inputs()
        r['units']=[dict(id=2,name='Warriors',role=1,attack=1),dict(id=0,name='Settlers',role=5,attack=0)]
        s['cities'][0]['production']=dict(id=2,kind='unit',name='Warriors')
        s['units']=[dict(id=i,owner=1,type_id=2,type='Warriors',x=2,y=2,order=2,hp=10) for i in range(5)]
        for case in ('none','existing_worker','worker_build','unknown','foreign_worker'):
            ss=deepcopy(s)
            if case in ('existing_worker','foreign_worker'):
                ss['units'].append(dict(id=10,owner=1 if case=='existing_worker' else 2,type_id=0,type='Settlers',x=4,y=4,hp=10))
            if case=='worker_build':ss['cities'][0]['production']=dict(id=0,kind='unit',name='Settlers')
            if case=='unknown':ss['units'].append(dict(id=10,owner=1,type_id=99,x=4,y=4))
            actions=empire_candidates(ss,screen,rules=r)
            request=empire_request_for(ss,screen,actions,rules=r)
            context=request['state']['end_of_turn_review']['production_review']
            self.assertEqual(context['no_observed_worker_or_worker_build'],case in ('none','foreign_worker'))
            self.assertEqual(context['cities'][0]['armed_units_here'],5)
            self.assertTrue(context['cities'][0]['unit_production_repeats'])
            self.assertIn('completed unit types repeat',actions['finish_turn']['label'])
            self.assertIn('5 armed units here',actions['inspect_city_0']['label'])
            self.assertEqual('empire has no worker and no worker build' in actions['inspect_city_0']['label'],case in ('none','foreign_worker'))
            self.assertIn('automatically repeats',request['questions']['empire_action']['instructions'])
            self.assertEqual(set(actions),{'finish_turn','inspect_city_0','open_tax','open_research'})
            self.assertEqual(actions['inspect_city_0']['parameters']['key'],'KeyC')
            self.assertTrue(actions['inspect_city_0']['parameters']['only_open_menu'])
            self.assertEqual(request['questions']['empire_action']['criteria'],{k:a['label'] for k,a in actions.items()})

    def test_concrete_only_open_commands_and_finish_turn(self):
        s,screen,r=inputs();actions=makeempire_candidates(s,screen,rules=r)
        self.assertEqual(set(actions),{'finish_turn','inspect_city_0','open_tax','open_research'})
        self.assertEqual(actions['finish_turn']['parameters']['key'],'Enter')
        self.assertFalse(actions['finish_turn']['parameters']['only_open_menu'])
        self.assertEqual(actions['inspect_city_0']['parameters']['key'],'KeyC')
        self.assertEqual(actions['inspect_city_0']['parameters']['modifiers'],['ShiftLeft'])
        self.assertEqual(actions['inspect_city_0']['parameters']['target_city'],{'id':0,'owner':1,'name':'TEST Rome','x':2,'y':2})
        self.assertTrue(actions['inspect_city_0']['parameters']['navigation_requires_fresh_locator'])
        self.assertEqual(actions['open_tax']['parameters']['key'],'KeyT')
        self.assertEqual(actions['open_research']['parameters']['key'],'F6')
        self.assertTrue(all(a['parameters']['only_open_menu'] for key,a in actions.items() if key!='finish_turn'))
        self.assertTrue(all('choice' not in a['parameters'] and 'center' not in a['parameters'] for a in actions.values()))

    def test_bindings_include_exact_save_turn_screen_and_review_ledger(self):
        s,screen,r=inputs();actions=empire_candidates(s,screen,{'open_tax'},r)
        for action in actions.values():
            p=action['preconditions']
            self.assertEqual((p['save_sha256'],p['image_sha256'],p['turn']),('a'*64,'b'*64,7))
            self.assertEqual(p['screen_kind'],'end_turn');self.assertEqual(p['end_turn_text'],'End of Turn')
            self.assertEqual(p['reviewed_action_ids'],['open_tax'])
            validate_empire_action(action,s,screen,{'open_tax'},r)

    def test_actual_endturn_cue_required_not_normal_map_or_modal(self):
        for change in [dict(kind='normal_map'),dict(supported=False),dict(title='Game Over!'),dict(options=[{'text':'OK'}]),dict(sha256='bad')]:
            s,screen,r=inputs();screen.update(change)
            with self.assertRaises(EmpireError):empire_candidates(s,screen,rules=r)

    def test_raw_ocr_native_end_turn_supported(self):
        s,screen,r=inputs()
        s['player'].update(tribe_id=0,tribe='Romans')
        def row(text,x,y,w):return dict(text=text,center=[x,y],bounds=[x-w//2,y-6,w,12],confidence=1.)
        o=dict(sha256='c'*64,width=640,height=480,lines=[
            row('Game Kingdom View Orders Advisors World Cheat Civilopedia',253,27,490),
            row('Roman Map',231,53,78),row('World',552,53,44),
            row('10,000 People',513,210,74),row('4000 B.C.',501,222,50),
            row('0 Gold 4.0.6',508,234,68),row('End of Turn',550,259,72)])
        a=empire_candidates(s,o,rules=r)
        self.assertEqual(a['finish_turn']['preconditions']['image_sha256'],'c'*64)

    def test_only_actual_contacts_offer_foreign_minister(self):
        s,screen,r=inputs();s['diplomacy']=[dict(civ_id=2,contact=False)]
        self.assertNotIn('open_diplomacy',empire_candidates(s,screen,rules=r))
        s['diplomacy']=[dict(civ_id=2,contact=True)]
        a=empire_candidates(s,screen,rules=r)['open_diplomacy']
        self.assertEqual(a['parameters']['key'],'F3');self.assertEqual(a['parameters']['expected_screen'],'foreign_minister')
        self.assertNotIn('target_civ',a['parameters'])

    def test_revolution_requires_available_alternative_and_confirmation(self):
        s,screen,r=inputs()
        self.assertNotIn('open_revolution',empire_candidates(s,screen,rules=r))
        s['player']['known_technology_ids']=[54]
        a=empire_candidates(s,screen,rules=r)['open_revolution']
        self.assertEqual(a['parameters']['key'],'KeyR');self.assertEqual(a['parameters']['modifiers'],['ShiftLeft'])
        self.assertEqual(a['parameters']['available_government_ids'],[2])
        self.assertTrue(a['parameters']['confirmation_requires_separate_choice'])
        self.assertNotIn('Yes',str(a['parameters']))
        s['player']['government_id']=0
        self.assertNotIn('open_revolution',empire_candidates(s,screen,rules=r))
        s['player']['government_id']=2
        self.assertNotIn('open_revolution',empire_candidates(s,screen,rules=r))

    def test_reviewed_city_and_menus_omitted_without_reordering_scope(self):
        s,screen,r=inputs();s['cities'].append(dict(s['cities'][0],id=1,name='TEST Veii',x=4))
        reviewed={'turn':7,'actions':['open_tax','inspect_city_0']}
        a=empire_candidates(s,screen,reviewed,r)
        self.assertNotIn('open_tax',a);self.assertNotIn('inspect_city_0',a)
        self.assertIn('inspect_city_1',a);self.assertIn('finish_turn',a)
        with self.assertRaises(EmpireError):empire_candidates(s,screen,{'turn':6,'actions':[]},r)
        s['turn']=8
        self.assertIn('inspect_city_0',empire_candidates(s,screen,{'turn':8,'actions':[]},r))

    def test_single_remaining_action_has_no_fabricated_distribution(self):
        s,screen,r=inputs();reviewed={'open_tax','open_research','inspect_city_0'}
        a=empire_candidates(s,screen,reviewed,r)
        self.assertEqual(list(a),['finish_turn'])
        with self.assertRaises(ForcedEmpireAction):empire_request_for(s,screen,a,reviewed,r)

    def test_model_request_contains_actual_choices_and_explicit_review_history(self):
        s,screen,r=inputs();a=empire_candidates(s,screen,{'open_tax'},r)
        request=empire_request_for(s,screen,a,{'open_tax'},r)
        self.assertEqual(set(request['questions']),{'empire_action','empire_strategy'})
        self.assertEqual(request['questions']['empire_action']['criteria'],{k:v['label'] for k,v in a.items()})
        self.assertEqual(request['state']['end_of_turn_review']['reviewed_action_ids'],['open_tax'])
        self.assertIn('fresh',request['state']['end_of_turn_review']['command_scope'])
        self.assertNotIn('open_tax',request['state']['end_of_turn_review']['remaining_options'])

    def test_stale_hash_turn_review_actor_and_tampered_key_rejected(self):
        s,screen,r=inputs();a=empire_candidates(s,screen,rules=r)['inspect_city_0']
        for which in ('save','image','turn','name','location'):
            ss,sc=deepcopy(s),deepcopy(screen)
            if which=='save':ss['evidence']['save_sha256']='c'*64
            elif which=='image':sc['sha256']='c'*64
            elif which=='turn':ss['turn']=8
            elif which=='name':ss['cities'][0]['name']='TEST Renamed'
            else:ss['cities'][0]['x']=4
            with self.subTest(which=which),self.assertRaises(EmpireError):validate_empire_action(a,ss,sc,rules=r)
        with self.assertRaises(EmpireError):validate_empire_action(a,s,screen,{'open_tax'},r)
        altered=deepcopy(a);altered['parameters']['key']='KeyQ'
        with self.assertRaises(EmpireError):validate_empire_action(altered,s,screen,rules=r)

    def test_foreign_city_or_duplicate_locator_name_not_actionable(self):
        s,screen,r=inputs();s['cities'][0]['owner']=2
        with self.assertRaises(EmpireError):empire_candidates(s,screen,rules=r)
        s,screen,r=inputs();s['cities'].append(dict(s['cities'][0],id=1,x=4))
        with self.assertRaises(EmpireError):empire_candidates(s,screen,rules=r)

    def test_no_mutation_of_observations_actions_or_rules(self):
        s,screen,r=inputs();before=deepcopy((s,screen,r));a=empire_candidates(s,screen,rules=r)
        empire_request_for(s,screen,a,rules=r)
        self.assertEqual((s,screen,r),before)
        a['inspect_city_0']['actor']['name']='TEST CHANGED'
        self.assertEqual(s['cities'][0]['name'],'TEST Rome')

    def test_reject_malformed_review_tokens_and_missing_state_revision(self):
        s,screen,r=inputs()
        for reviewed in ['open_tax',['finish_turn'],['unknown_menu'],{'turn':7,'actions':[],'extra':1}]:
            with self.assertRaises(EmpireError):empire_candidates(s,screen,reviewed,r)
        s['evidence']={}
        with self.assertRaises(EmpireError):empire_candidates(s,screen,rules=r)

    def test_request_cannot_swap_candidate_labels_or_add_unseen_menu(self):
        s,screen,r=inputs();a=empire_candidates(s,screen,rules=r)
        a['open_tax']['label']='TEST Automatically set tax to 100%'
        with self.assertRaises(EmpireError):empire_request_for(s,screen,a,rules=r)


if __name__=='__main__':unittest.main()
