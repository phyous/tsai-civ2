"""Policy tests use synthetic observations; they are not model/game runs."""
import copy
import json
import unittest

from civ2.policy import (PolicyError, DIRECTIONS, dialog_candidates, dialog_request_for,
                         model_state, unit_candidates, unit_request_for, validate_action)
from civ2.save import parse_rules
from civ2.typesafe import _validate_questions


RULES_TEXT = """@UNITS
Settlers,nil,0,1.,0,0a,1d,2h,1f,4,0,5,nil,0000
Warriors,nil,0,1.,0,1a,1d,1h,1f,1,0,1,nil,0000
Trireme,nil,2,3.,0,1a,1d,1h,1f,4,2,4,Map,0000
@CIVILIZE
Bridge Building,4,0,Iro,Cst,0,4 ; Bri
Railroad,6,0,SE,Bri,2,1 ; RR
Refrigeration,3,1,E1,San,3,1 ; Rfg
"""


def rules():
    r = parse_rules(RULES_TEXT)
    r["terrain"] = [
        {"id":0,"name":"Desert","irrigation_result":"yes","mining_result":"yes"},
        {"id":1,"name":"Plains","irrigation_result":"yes","mining_result":"For"},
        {"id":2,"name":"Grassland","irrigation_result":"yes","mining_result":"For"},
        {"id":4,"name":"Hills","irrigation_result":"yes","mining_result":"yes"},
        {"id":5,"name":"Mountains","irrigation_result":"no","mining_result":"yes"},
    ]
    return r


def fixture(unit_type=0):
    r = rules()
    terrain=[{"x":8+dx,"y":8+dy,"terrain_id":2,"terrain":"Grassland","river":False,"known_improvements":[]} for _,_,dx,dy,_ in (("here","here",0,0,""),*DIRECTIONS)]
    return {"turn":1,"year_raw":-4000,"selected_unit_id":7,"settings":{"round_world":False},
            "player":{"id":1,"tribe":"TEST Romans","treasury":50,"known_technology_ids":[],"known_technologies":[]},
            "units":[{"id":7,"owner":1,"type_id":unit_type,"type":r['units'][unit_type]['name'],"x":8,"y":8,"movement_thirds_spent":0,"order_id":255,"specification":r['units'][unit_type]}],
            "visible_units":[],"cities":[],"known_cities":[],"diplomacy":[],
            "map":{"coordinate_width":32,"width":16,"height":16,"explored_count":len(terrain),"tiles":terrain},
            "evidence":{"save_sha256":"a"*64}}


def here(s):
    return next(t for t in s['map']['tiles'] if (t['x'],t['y'])==(s['units'][0]['x'],s['units'][0]['y']))


def dialog():
    return {"id":"research","title":"TEST: What shall we discover?","sha256":"b"*64,"width":640,"height":480,
            "options":[{"text":"Alphabet","center":[140,180]},{"text":"Bronze Working","center":[140,205]}]}


class PolicyTests(unittest.TestCase):
    def test_full_observed_dialog_terms_reach_model_without_truncation(self):
        d=dialog();d['visible_text']='TEST emissary offers:\n'+('TEST terms. '*60)+'\nPay 75 gold.'
        request,_=dialog_request_for(fixture(),d,rules())
        self.assertEqual(request['state']['mandatory_dialog']['observed_text'],d['visible_text'])
        for invalid in ('x'*8001,{'not':'observed text'}):
            d['visible_text']=invalid
            with self.assertRaises(PolicyError):dialog_request_for(fixture(),d,rules())

    def test_model_labor_projects_center_worker_and_unexplored_without_hidden_data(self):
        s=fixture();r=rules()
        s['cities']=[dict(id=0,owner=1,name='TEST Rome',x=8,y=8,size=1,
            worked_tiles_bits=[32,0,16],specialist_count=0,specialists={},
            happy=0,unhappy=0,disorder=False,celebrating=False,food_produced=4)]
        s['map']['tiles']=[here(s),dict(x=6,y=8,terrain_id=2,terrain='Grassland',river=True,
            known_improvements=['road'],actual_improvements=['SECRET'],hidden_owner='SECRET')]
        s['map']['hidden_tiles']=[dict(x=8,y=6,terrain_id=5,terrain='SECRET')]
        r['terrain'][2].update(food=2,shields=0,trade=0)
        old=copy.deepcopy(s)
        actions=unit_candidates(s,rules=r)
        request=unit_request_for(s,actions,r)
        labor=request['state']['city_labor'];city=labor['cities'][0]
        self.assertEqual(labor['revision'],{'save_sha256':'a'*64,'turn':1})
        self.assertEqual(len(city['radius']),21)
        center=next(row for row in city['radius'] if row[3])
        self.assertEqual(center[:6],[8,8,True,True,'explored',2])
        self.assertEqual(center[8],[2,0,0])
        west=next(row for row in city['radius'] if row[:2]==[6,8])
        self.assertEqual(west,[6,8,True,False,'explored',2,True,['road'],[2,0,0]])
        north=next(row for row in city['radius'] if row[:2]==[8,6])
        self.assertEqual(north[4:],['unexplored',None,None,None,None])
        self.assertNotIn('SECRET',json.dumps(labor))
        self.assertIn('not actual tile yields',labor['yield_note'])
        self.assertIn('not verified',labor['action_note'])
        self.assertEqual(request['questions']['unit_action']['criteria'],{k:v['label'] for k,v in actions.items()})
        self.assertEqual(s,old)

    def test_model_labor_partial_observation_unavailable_not_invented(self):
        s=fixture();s['cities']=[dict(id=0,name='TEST Rome',x=8,y=8,size=1)]
        labor=model_state(s,rules())['city_labor']
        self.assertEqual(labor['cities'][0]['available'],False)
        self.assertNotIn('radius',labor['cities'][0])
        s['cities'][0].update(owner=1,worked_tiles_bits=[32,0,16],specialist_count=0,specialists={})
        city=model_state(s,rules())['city_labor']['cities'][0]
        self.assertTrue(city['available'])
        self.assertTrue(all(row[8] is None for row in city['radius']))

    def test_model_labor_supplied_invalid_bitmap_fails_instead_of_silently_omitting(self):
        s=fixture();s['cities']=[dict(id=0,owner=1,name='TEST Rome',x=8,y=8,size=1,
            worked_tiles_bits=[32,0,0],specialist_count=0,specialists={})]
        with self.assertRaisesRegex(PolicyError,'city-center worked bit'):
            model_state(s,rules())

    def test_model_labor_specialist_uncertainty_is_available_to_dialog_decision(self):
        s=fixture();s['cities']=[dict(id=0,owner=1,name='TEST Rome',x=8,y=8,size=3,
            worked_tiles_bits=[32,0,16],specialist_count=2,specialists={'entertainer':1},
            happy=1,unhappy=2,disorder=True)]
        request,_=dialog_request_for(s,dialog(),rules())
        city=request['state']['city_labor']['cities'][0]
        self.assertTrue(city['labor_balance']['consistent'])
        self.assertEqual(city['specialists']['untyped_count'],1)
        self.assertFalse(city['specialists']['type_counts_complete'])
        self.assertTrue(city['happiness']['disorder'])
        self.assertTrue(city['warnings'])

    def test_full_known_map_retains_odd_row_coordinates_and_remembered_works_only(self):
        s=fixture();s['map']['tiles']=[
            {'x':8,'y':8,'terrain_id':2,'terrain':'Grassland','river':True,'known_improvements':['road','irrigation'], 'live_enemy':'SECRET_LIVE'},
            {'x':21,'y':13,'terrain_id':5,'terrain':'Mountains','river':False,'known_improvements':['mine','pollution'], 'resource_seed':'SECRET_SEED'}]
        s['map']['hidden_tiles']=[{'x':20,'y':12,'terrain':'SECRET_TERRAIN'}]
        state=model_state(s,rules());world=state['map']
        self.assertEqual(world['terrain_rows'][13][10],'5')
        self.assertEqual(world['terrain_rows'][12][10],'?')
        self.assertEqual(world['terrain_rows'][8][4],'2')
        self.assertEqual(world['known_rivers_xy'],[[8,8]])
        self.assertEqual(world['remembered_improvements_xy_codes'],[[8,8,'ri'],[21,13,'mp']])
        self.assertEqual(world['explored_count'],2)
        self.assertNotIn('SECRET',json.dumps(state))
        self.assertIn('remembered',world['knowledge'])

    def test_small_map_two_thousand_cells_are_compact_and_complete(self):
        s=fixture();s['map'].update(coordinate_width=80,width=40,height=50)
        s['map']['tiles']=[{'x':2*c+y%2,'y':y,'terrain_id':2,'terrain':'Grassland',
                            'river':False,'known_improvements':[]} for y in range(50) for c in range(40)]
        world=model_state(s,rules())['map']
        self.assertEqual(world['explored_count'],2000)
        self.assertEqual(world['terrain_rows'],['2'*40]*50)
        self.assertLess(len(json.dumps(world)),4000)

    def test_roster_all_owned_units_and_city_locations_survive_detail_limit(self):
        s=fixture()
        distant=copy.deepcopy(s['units'][0]);distant.update(id=8,x=22,y=14,order_id=3)
        s['units'].append(distant)
        s['cities']=[{'id':i,'name':f'TEST {i}','x':2*(i%16),'y':2*(i//16),'size':1} for i in range(40)]
        state=model_state(s,rules())
        self.assertEqual(len(state['owned_unit_roster']),2)
        self.assertEqual(state['owned_unit_roster'][1]['x'],22)
        self.assertEqual(state['owned_unit_roster'][1]['order_id'],3)
        self.assertNotIn('specification',state['owned_unit_roster'][1])
        self.assertEqual(state['owned_unit_type_specifications']['0']['role'],5)
        self.assertEqual(len(state['owned_city_locations']),40)
        self.assertEqual(len(state['owned_cities']),32)
        self.assertEqual(state['omitted_owned_city_details'],8)
        self.assertEqual(len(state['city_labor']['cities']),32)
        self.assertEqual(state['city_labor']['omitted_city_count'],8)

    def test_city_distance_is_geometric_and_wrap_aware(self):
        s=fixture();s['units'][0].update(x=0,y=8)
        s['cities']=[{'id':0,'name':'TEST Rome','x':30,'y':8}]
        state=model_state(s,rules())
        self.assertEqual(state['selected_unit_city_context']['nearest_owned_city']['geometric_grid_steps'],15)
        s['settings']['round_world']=True
        state=model_state(s,rules())
        self.assertEqual(state['selected_unit_city_context']['nearest_owned_city']['geometric_grid_steps'],1)
        self.assertIn('0 grid steps from TEST Rome',unit_candidates(s,rules=rules())['move_w']['label'])
        self.assertIn('Not terrain costs',state['selected_unit_city_context']['distance_note'])

    def test_city_centers_do_not_offer_ordinary_worker_improvements(self):
        for foreign in (False,True):
            s=fixture();here(s).update(river=True,known_improvements=['road','irrigation'])
            s['player']['known_technology_ids']=[0,1,2]
            s['known_cities' if foreign else 'cities']=[{'id':0,'x':8,'y':8}]
            a=unit_candidates(s,rules=rules())
            self.assertFalse(set(a)&{'settle','road','railroad','irrigate','farmland','mine'})
            self.assertIn('move_e',a)
        s=fixture();here(s).update(terrain='Hills',terrain_id=4)
        s['cities']=[{'id':0,'x':8,'y':8}]
        self.assertNotIn('mine',unit_candidates(s,rules=rules()))
        s['cities'][0]['x']=6
        self.assertIn('mine',unit_candidates(s,rules=rules()))

    def test_recent_receipts_are_bounded_projected_and_not_inferred_success(self):
        s=fixture();a=unit_candidates(s,rules=rules())
        history=[{'turn':i,'actor':{'id':7,'type_id':0,'owner':1,'x':8,'y':8},
                  'order':'Move north','outcome':'No observed state change','private':'SECRET'} for i in range(30)]
        history.append({'action':a['move_e'],'receipt':{'issued':True,'accepted':False,'state_changed':False,
            'outcome':'No observed state change','before':{'turn':1,'save_sha256':'a'*64,'private':'SECRET'},
            'after':{'turn':1,'save_sha256':'a'*64,'selected_unit_id':6},'server_raw':'SECRET'}})
        old=copy.deepcopy(history)
        request=unit_request_for(s,a,rules(),recent_actions=history)
        rows=request['state']['recent_actions']
        self.assertEqual(len(rows),24);self.assertEqual(rows[0]['turn'],7)
        self.assertNotIn('accepted',rows[0]);self.assertNotIn('state_changed',rows[0])
        self.assertIs(rows[-1]['accepted'],False);self.assertIs(rows[-1]['state_changed'],False)
        self.assertEqual(rows[-1]['attempted_destination'],{'x':10,'y':8})
        self.assertEqual(rows[-1]['save_sha256_at_issue'],'a'*64)
        self.assertEqual(rows[-1]['after']['selected_unit_id'],6)
        self.assertNotIn('SECRET',json.dumps(request));self.assertEqual(history,old)
        # The same action remains canonical; memory never dispatches or rewrites it.
        validate_action(a['move_e'],s,rules())
        self.assertEqual(request['questions']['unit_action']['criteria'],{k:v['label'] for k,v in a.items()})

    def test_memory_never_attaches_old_compacted_slot_to_current_unit(self):
        s=fixture();a=unit_candidates(s,rules=rules())
        history=[{'action':a['move_e'],'receipt':{'issued':True,'state_changed':True}}]
        s['evidence']['save_sha256']='c'*64;s['units'][0].update(type_id=1,type='Warriors',specification=rules()['units'][1])
        state=model_state(s,rules(),recent_actions=history)
        self.assertEqual(state['recent_actions'][0]['actor_at_issue']['type_id'],0)
        self.assertEqual(state['owned_unit_roster'][0]['type_id'],1)
        self.assertIn('not persistent',state['unit_identity_note'])
        self.assertNotIn('last_action',state['selected_unit'])

    def test_dialog_memory_backwards_compatibility_and_no_empire_fabrication(self):
        d=dialog();history=[{'turn':1,'order':'Choose Alphabet','outcome':'Observed dialog closed'}]
        req,actions=dialog_request_for({},d,recent_actions=history)
        self.assertEqual(req['state']['recent_actions'][0]['attempted_order'],'Choose Alphabet')
        self.assertNotIn('map',req['state']);self.assertNotIn('player',req['state'])
        self.assertEqual(actions,dialog_candidates({},d))
        self.assertEqual(model_state(fixture(),rules())['recent_actions'],[])
        with self.assertRaises(PolicyError):model_state(fixture(),rules(),recent_actions=['not a receipt'])

    def test_research_paths_use_original_prerequisites_and_observed_knowledge(self):
        r=rules();r['advances']=[
            {'id':10,'name':'Alphabet','code':'Alp','prerequisites':['nil','nil']},
            {'id':11,'name':'Code of Laws','code':'CoL','prerequisites':['Alp','nil']},
            {'id':12,'name':'Monarchy','code':'Mon','prerequisites':['CoL','nil']}]
        s=fixture();s['player'].update(known_technology_ids=[10],researching_id=11)
        context=model_state(s,r)['research_context']
        self.assertEqual(context['current_research'],'Code of Laws')
        self.assertEqual(context['prerequisite_satisfied_advances'],[{'id':11,'name':'Code of Laws'}])
        self.assertEqual(context['possible_strategic_paths'][0]['unknown_prerequisites_then_target'],['Code of Laws','Monarchy'])
        self.assertIn('not the exact native research menu',context['note'])
        self.assertIn('Despotism',model_state(s,r)['strategic_playbook']['despotism'])

    def test_original_keypad_deltas_and_bound_actor(self):
        s=fixture(1);a=unit_candidates(s,rules=rules())
        for short,_,dx,dy,key in DIRECTIONS:
            move=a['move_'+short]
            self.assertEqual(move['parameters']['key'],key)
            self.assertEqual(move['parameters']['destination'],{'x':8+dx,'y':8+dy})
            self.assertEqual(move['preconditions']['save_sha256'],'a'*64)
            self.assertEqual(move['actor'],{'id':7,'type_id':1,'owner':1,'x':8,'y':8})
        self.assertNotIn('disband',a);self.assertNotIn('end_turn',a)

    def test_edge_and_round_world_wrap(self):
        s=fixture(1);s['units'][0].update(x=0,y=0);s['map']['tiles']=[]
        a=unit_candidates(s,rules=rules());self.assertNotIn('move_n',a);self.assertNotIn('move_w',a)
        s['settings']['round_world']=True;a=unit_candidates(s,rules=rules())
        self.assertEqual(a['move_w']['parameters']['destination'],{'x':30,'y':0})
        self.assertNotIn('move_n',a)

    def test_unknown_tiles_not_replaced_by_hidden_terrain(self):
        s=fixture(1);s['map']['tiles']=[here(s)]
        a=unit_candidates(s,rules=rules());self.assertIn('unexplored',a['move_e']['label'])
        self.assertEqual(a['move_e']['parameters']['knowledge'],'unexplored')
        self.assertNotIn('terrain',next(t for t in model_state(s,rules())['neighboring_tiles'] if t['direction']=='east'))

    def test_known_ocean_blocks_land_but_not_air_or_sea(self):
        s=fixture(1);east=next(t for t in s['map']['tiles'] if t['x']==10);east.update(terrain='Ocean',terrain_id=10)
        self.assertNotIn('move_e',unit_candidates(s,rules=rules()))
        s=fixture(2);east=next(t for t in s['map']['tiles'] if t['x']==10);east.update(terrain='Ocean',terrain_id=10)
        a=unit_candidates(s,rules=rules());self.assertIn('move_e',a);self.assertNotIn('move_w',a)
        s['cities']=[{'x':6,'y':8,'id':0,'name':'TEST Port'}]
        self.assertIn('move_w',unit_candidates(s,rules=rules()))

    def test_foreign_occupied_destination_not_offered_to_unarmed_settler(self):
        s=fixture();s['visible_units']=[{'id':22,'type':'Warriors','owner':2,'x':10,'y':8}]
        self.assertNotIn('move_e',unit_candidates(s,rules=rules()))
        s=fixture(1);s['visible_units']=[{'id':22,'type':'Warriors','owner':2,'x':10,'y':8}]
        self.assertIn('combat or diplomacy',unit_candidates(s,rules=rules())['move_e']['label'])

    def test_settlement_only_compatible_worker_on_grass_or_plains_without_city(self):
        s=fixture();self.assertIn('settle',unit_candidates(s,rules=rules()))
        here(s).update(terrain='Plains',terrain_id=1);self.assertIn('settle',unit_candidates(s,rules=rules()))
        here(s).update(terrain='Mountains',terrain_id=5);self.assertNotIn('settle',unit_candidates(s,rules=rules()))
        s=fixture();s['cities']=[{'id':0,'x':8,'y':8}];self.assertNotIn('settle',unit_candidates(s,rules=rules()))
        self.assertNotIn('settle',unit_candidates(fixture(1),rules=rules()))

    def test_settlement_rejects_all_adjacent_owned_and_remembered_city_squares(self):
        for collection in ('cities','known_cities'):
            for _,_,dx,dy,_ in (("here","here",0,0,""),*DIRECTIONS):
                with self.subTest(collection=collection,dx=dx,dy=dy):
                    s=fixture();s[collection]=[{'id':0,'x':8+dx,'y':8+dy}]
                    self.assertNotIn('settle',unit_candidates(s,rules=rules()))
            # Two keypad steps are legal with respect to this spacing rule.
            for point in ((8,12),(12,8),(10,10)):
                s=fixture();s[collection]=[{'id':0,'x':point[0],'y':point[1]}]
                self.assertIn('settle',unit_candidates(s,rules=rules()))

    def test_settlement_spacing_wraps_only_on_observed_round_world(self):
        for collection in ('cities','known_cities'):
            for point in ((30,8),(31,7),(31,9)):
                s=fixture();s['units'][0]['x']=0
                s['map']['tiles']=[dict(x=0,y=8,terrain_id=2,terrain='Grassland',river=False,known_improvements=[])]
                s[collection]=[{'id':0,'x':point[0],'y':point[1]}]
                self.assertIn('settle',unit_candidates(s,rules=rules()))
                s['settings']['round_world']=True
                self.assertNotIn('settle',unit_candidates(s,rules=rules()))
                s[collection][0].update(x=28,y=8)
                self.assertIn('settle',unit_candidates(s,rules=rules()))

    def test_unobserved_city_does_not_invent_a_settlement_spacing_restriction(self):
        s=fixture();s['hidden_cities']=[{'id':0,'x':8,'y':6}]
        self.assertIn('settle',unit_candidates(s,rules=rules()))

    def test_unload_is_original_transport_request_bound_to_selected_actor(self):
        s=fixture(2);r=rules();old=copy.deepcopy(s)
        actions=unit_candidates(s,rules=r);action=actions['unload']
        self.assertEqual(action['kind'],'unload')
        self.assertEqual(action['parameters'],{'key':'KeyU','transport_specification':{
            'id':2,'domain':2,'role':4,'transport_capacity':2}})
        self.assertEqual(action['actor'],{'id':7,'type_id':2,'owner':1,'x':8,'y':8})
        self.assertEqual(action['preconditions']['save_sha256'],'a'*64)
        self.assertIn('Request unloading',action['label'])
        self.assertIn('unverified',action['label'])
        self.assertNotIn('cargo_units',action['parameters'])
        validate_action(action,s,r)
        request=unit_request_for(s,actions,r);_validate_questions(request['questions'])
        self.assertEqual(request['questions']['unit_action']['criteria']['unload'],action['label'])
        self.assertEqual(s,old)

    def test_unload_requires_original_naval_transport_role_and_positive_integer_capacity(self):
        for changes in ({'domain':0},{'domain':1},{'domain':True},{'role':2},
                        {'transport_capacity':0},{'transport_capacity':-1},
                        {'transport_capacity':True},{'transport_capacity':2.5},
                        {'transport_capacity':None}):
            with self.subTest(changes=changes):
                s=fixture(2);r=rules()
                s['units'][0]['specification'].update(changes);r['units'][2].update(changes)
                self.assertNotIn('unload',unit_candidates(s,rules=r))
        for unit_type in (0,1):
            self.assertNotIn('unload',unit_candidates(fixture(unit_type),rules=rules()))

    def test_unload_does_not_trust_missing_ambiguous_or_conflicting_original_specification(self):
        s=fixture(2);self.assertNotIn('unload',unit_candidates(s))
        r=rules();r['units'].append(copy.deepcopy(r['units'][2]))
        self.assertNotIn('unload',unit_candidates(s,rules=r))
        r=rules();s['units'][0]['specification']['transport_capacity']=8
        self.assertNotIn('unload',unit_candidates(s,rules=r))
        # The original rules can supply the specification if omitted from the observation.
        s['units'][0].pop('specification')
        self.assertIn('unload',unit_candidates(s,rules=r))

    def test_unload_never_infers_cargo_or_changes_land_to_ocean_moves(self):
        s=fixture();here(s).update(terrain='Grassland',terrain_id=2)
        next(t for t in s['map']['tiles'] if (t['x'],t['y'])==(10,8)).update(terrain='Ocean',terrain_id=10)
        ship=copy.deepcopy(fixture(2)['units'][0]);ship.update(id=8,x=10,y=8)
        s['units'].append(ship)
        self.assertNotIn('unload',unit_candidates(s,rules=rules()))
        self.assertNotIn('move_e',unit_candidates(s,rules=rules()))
        s['selected_unit_id']=8
        first=unit_candidates(s,rules=rules())['unload']
        s['units'][0].update(x=10,y=8)
        self.assertEqual(unit_candidates(s,rules=rules())['unload'],first)
        s['units'][1]['owner']=2
        with self.assertRaises(PolicyError):unit_candidates(s,rules=rules())

    def test_unload_canonical_validation_rejects_altered_key_cargo_and_stale_actor(self):
        s=fixture(2);action=unit_candidates(s,rules=rules())['unload']
        for mutate in (lambda a:a['parameters'].update(key='KeyL'),
                       lambda a:a['parameters'].update(cargo_units=[9]),
                       lambda a:a['parameters']['transport_specification'].update(transport_capacity=8)):
            tampered=copy.deepcopy(action);mutate(tampered)
            with self.assertRaises(PolicyError):validate_action(tampered,s,rules())
        for mutate in (lambda state:state['evidence'].update(save_sha256='b'*64),
                       lambda state:state['units'][0].update(x=10),
                       lambda state:state.update(selected_unit_id=None)):
            fresh=copy.deepcopy(s);mutate(fresh)
            with self.assertRaises(PolicyError):validate_action(action,fresh,rules())

    def test_worker_F_not_mislabeled_fortify(self):
        self.assertNotIn('fortify',unit_candidates(fixture(),rules=rules()))
        self.assertEqual(unit_candidates(fixture(1),rules=rules())['fortify']['parameters']['key'],'KeyF')

    def test_river_road_requires_observed_bridge_building(self):
        s=fixture();here(s)['river']=True
        self.assertNotIn('road',unit_candidates(s,rules=rules()))
        s['player']['known_technology_ids']=[0]
        self.assertIn('road',unit_candidates(s,rules=rules()))

    def test_irrigation_needs_reported_terrain_rule_and_known_water_access(self):
        s=fixture();self.assertNotIn('irrigate',unit_candidates(s,rules=rules()))
        east=next(t for t in s['map']['tiles'] if t['x']==10);east.update(terrain='Ocean',terrain_id=10)
        self.assertIn('irrigate',unit_candidates(s,rules=rules()))
        self.assertNotIn('irrigate',unit_candidates(s,rules=parse_rules(RULES_TEXT)))
        east.update(terrain='Grassland',terrain_id=2,known_improvements=['irrigation'])
        self.assertIn('irrigate',unit_candidates(s,rules=rules()))

    def test_mining_uses_rule_yes_not_a_terrain_conversion(self):
        s=fixture();self.assertNotIn('mine',unit_candidates(s,rules=rules()))
        here(s).update(terrain='Hills',terrain_id=4);self.assertIn('mine',unit_candidates(s,rules=rules()))
        here(s)['known_improvements']=['mine'];self.assertNotIn('mine',unit_candidates(s,rules=rules()))

    def test_upgrades_require_known_technology_and_existing_improvement(self):
        s=fixture();here(s).update(river=True,known_improvements=['road','irrigation'])
        a=unit_candidates(s,rules=rules());self.assertNotIn('railroad',a);self.assertNotIn('farmland',a)
        s['player']['known_technology_ids']=[0,1,2]
        a=unit_candidates(s,rules=rules());self.assertEqual(a['railroad']['parameters']['key'],'KeyR');self.assertEqual(a['farmland']['parameters']['key'],'KeyI')

    def test_stale_save_turn_slot_type_owner_and_position_are_all_rejected(self):
        s=fixture();action=unit_candidates(s,rules=rules())['settle'];validate_action(action,s,rules())
        mutations=[lambda x:x['evidence'].update(save_sha256='c'*64),lambda x:x.update(turn=2),lambda x:x['units'][0].update(type_id=1),lambda x:x['units'][0].update(owner=2),lambda x:x['units'][0].update(x=10),lambda x:x.update(selected_unit_id=6)]
        for mutate in mutations:
            fresh=copy.deepcopy(s);mutate(fresh)
            with self.subTest(mutation=mutate),self.assertRaises(PolicyError):validate_action(action,fresh,rules())

    def test_tampered_key_or_candidate_question_rejected(self):
        s=fixture();a=unit_candidates(s,rules=rules());a['settle']['parameters']['key']='KeyD'
        with self.assertRaises(PolicyError):validate_action(a['settle'],s,rules())
        with self.assertRaises(PolicyError):unit_request_for(s,a,rules())

    def test_selected_actor_only_and_missing_rules_fail_closed(self):
        s=fixture()
        with self.assertRaises(PolicyError):unit_candidates(s,unit_id=3,rules=rules())
        s['units'][0].pop('specification')
        with self.assertRaises(PolicyError):unit_candidates(s)
        s['selected_unit_id']=None;self.assertEqual(unit_candidates(s,rules=rules()),{})

    def test_companion_strategy_is_not_a_dependent_question(self):
        s=fixture();a=unit_candidates(s,rules=rules());request=unit_request_for(s,a,rules())
        self.assertEqual(set(request['questions']),{'unit_action','empire_strategy'})
        self.assertEqual(set(request['questions']['unit_action']['criteria']),set(a))
        self.assertEqual(len(request['questions']['empire_strategy']['criteria']),6)
        self.assertIn('independent',request['questions']['unit_action']['instructions'])
        _validate_questions(request['questions']);self.assertNotIn('probabilities',json.dumps(request))

    def test_dialog_options_are_exact_ocr_labels_and_bound_coordinates(self):
        s=fixture();d=dialog();request,a=dialog_request_for(s,d,rules())
        self.assertEqual(a['option_1']['parameters']['center'],[140,205])
        self.assertEqual(request['questions']['dialog_action']['criteria'],{'option_0':'Alphabet','option_1':'Bronze Working'})
        self.assertEqual(a['option_0']['preconditions']['image_sha256'],'b'*64)
        _validate_questions(request['questions']);validate_action(a['option_0'],s,rules(),d)
        d['sha256']='c'*64
        with self.assertRaises(PolicyError):validate_action(a['option_0'],s,rules(),d)

    def test_dialog_duplicate_labels_centers_and_outside_image_rejected(self):
        for mutate in [lambda d:d['options'][1].update(text='Alphabet'),lambda d:d['options'][1].update(center=[140,180]),lambda d:d['options'][1].update(center=[640,480]),lambda d:d.update(sha256='bad')]:
            d=dialog();mutate(d)
            with self.assertRaises(PolicyError):dialog_candidates(fixture(),d)

    def test_single_dialog_acknowledgement_is_not_fabricated_choice(self):
        d=dialog();d['options']=d['options'][:1]
        self.assertEqual(len(dialog_candidates({},d)),1)
        with self.assertRaises(PolicyError):dialog_request_for({},d)

    def test_foreign_future_orders_and_private_city_fields_not_forwarded(self):
        s=fixture();s['visible_units']=[{'id':3,'owner':2,'type':'Warriors','x':10,'y':8,'goto':{'secret':'SECRET_WAYPOINT'}}]
        s['known_cities']=[{'id':9,'name':'Known','x':16,'y':8,'current_information':False,'production':'SECRET_PRODUCTION'}]
        self.assertNotIn('SECRET',json.dumps(model_state(s,rules())))


if __name__ == '__main__':
    unittest.main()
