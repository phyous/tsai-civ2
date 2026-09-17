"""Source-bound activation intentions and native readback, no game controls."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
import zipfile

from civ2.unit_activation import (activation_candidates,validate_activation,activation_popup,
                                  activation_result,activation_radio_proof,UnitActivationError,ACTIVATE)
from tests.test_city_controls import inputs
from tests.test_city_layout import complete_city
from tests.test_dialogs import observation,row


GAME='@UNITOPTIONS\n@width=320\n@title=Unit Information\n^%STRING0\n^Home City: %STRING2\n'
LABELS='\n'.join(['No changes.','Clear orders.','Sleep / Board next ship.','Activate Unit.',ACTIVATE,'OK','Cancel'])


def fixture():
    state,_,rules=inputs();state['year_raw']=-2600;state['player']['tribe_id']=0
    rules['leaders']=[dict(id=0,adjective='TEST Roman')]
    rules['units']=[dict(id=2,name='Warriors',domain=0,role=1,attack=1,max_hp=10)]
    def unit(i,order):return dict(id=i,owner=1,type_id=2,x=2,y=2,veteran=False,hp_lost=0,
        movement_thirds_spent=0,order_id=order,home_city_id=0,counter_or_commodity=0,waiting=False,goto=None)
    state['units']=[unit(6,2),unit(12,255)];state['selected_unit_id']=12
    state['owned_unit_stacks']=[dict(x=2,y=2,unit_ids=[12,6],links=[dict(id=12,previous=None,next=6),dict(id=6,previous=12,next=None)])]
    image=complete_city();image['lines'].append(row('Units Supported',x=100,y=283,w=110,h=12))
    return state,image,rules


def popup():
    items=[('Unit Information',320,125),('TEST Roman Warriors',330,150),('Home City: TEST Rome',330,170),
           ('No changes.',308,195),('Clear orders.',308,220),('Sleep / Board next ship.',360,246),
           ('Disband',293,271),('Activate Unit.',313,297),(ACTIVATE,388,322),('OK',206,354),('Cancel',435,354)]
    return observation(*[row(t,x=x,y=y,w=min(310,len(t)*6),h=12) for t,x,y in items])


class UnitActivationTests(unittest.TestCase):
    def test_exact_fortified_unit_uses_native_stack_order_not_sorted_slot(self):
        state,image,rules=fixture();before=deepcopy((state,image,rules))
        self.assertEqual(activation_candidates(state,image,rules),{})
        actions=activation_candidates(state,image,rules,ready=True)
        self.assertEqual(list(actions),['activate_city_unit_6'])
        action=actions['activate_city_unit_6'];self.assertEqual(action['parameters']['center'],[264,310])
        self.assertEqual(action['parameters']['slot'],1);self.assertFalse(action['parameters']['movement_authorized'])
        self.assertEqual(action['preconditions']['stack']['unit_ids'],[12,6])
        validate_activation(action,state,image,rules,ready=True)
        self.assertEqual((state,image,rules),before)

    def test_stale_unit_revision_chain_and_geometry_cannot_reuse_an_action(self):
        state,image,rules=fixture();action=activation_candidates(state,image,rules,ready=True)['activate_city_unit_6']
        for case in ('revision','reused_id','order','chain','unit_missing','extra','heading','geometry','veteran'):
            s,o=deepcopy(state),deepcopy(image)
            if case=='revision':s['evidence']['save_sha256']='f'*64
            elif case=='reused_id':s['units'][0]['type_id']=0
            elif case=='order':s['units'][0]['order_id']=255
            elif case=='chain':s['owned_unit_stacks'][0]['links'][0]['next']=999
            elif case=='unit_missing':s['units'].pop()
            elif case=='extra':s['units'].append(dict(s['units'][0],id=15))
            elif case=='heading':o['lines']=[r for r in o['lines'] if r['text']!='Units Present']
            elif case=='geometry':
                r=next(r for r in o['lines'] if r['text']=='Units Present');r['center'][1]-=30;r['bounds'][1]-=30
            else:s['units'][0]['veteran']=True
            with self.subTest(case=case),self.assertRaises((UnitActivationError,ValueError)):
                validate_activation(action,s,o,rules,ready=True)

    def test_five_cell_present_row_remains_independent_of_wrapped_supported_pane(self):
        state,image,rules=fixture();image['lines']=[r for r in image['lines'] if r['text']!='Units Supported']
        state['units']=[dict(state['units'][0],id=i) for i in (2,5,7,11,13)]
        state['selected_unit_id']=None
        order=[13,11,7,5,2]
        state['owned_unit_stacks']=[dict(x=2,y=2,unit_ids=order,links=[dict(id=i,
            previous=order[n-1] if n else None,next=order[n+1] if n<4 else None) for n,i in enumerate(order)])]
        actions=activation_candidates(state,image,rules,ready=True)
        self.assertEqual(len(actions),5)
        self.assertEqual(actions['activate_city_unit_13']['parameters']['center'],[216,310])
        self.assertEqual(actions['activate_city_unit_2']['parameters']['center'],[408,310])
        state['units'].append(dict(state['units'][0],id=18));order.insert(0,18)
        state['owned_unit_stacks']=[dict(x=2,y=2,unit_ids=order,links=[dict(id=i,
            previous=order[n-1] if n else None,next=order[n+1] if n<5 else None) for n,i in enumerate(order)])]
        self.assertEqual(activation_candidates(state,image,rules,ready=True),{})

    def test_dead_stack_member_or_enemy_selected_during_resolution_cannot_be_activated(self):
        for case in ('target_dead','other_dead','zero_hp','enemy_selected','missing_hp_rule'):
            state,image,rules=fixture()
            if case=='target_dead':state['units'][0]['hp_lost']=10
            elif case=='other_dead':state['units'][1]['hp_lost']=10
            elif case=='zero_hp':state['units'][0]['hp']=0
            elif case=='enemy_selected':state['selected_unit_id']=99
            else:rules['units'][0].pop('max_hp')
            with self.subTest(case=case):self.assertEqual(activation_candidates(state,image,rules,ready=True),{})

    def test_exact_pending_popup_returns_only_observed_activation_and_confirmation(self):
        s,o,r=fixture();a=activation_candidates(s,o,r,ready=True)['activate_city_unit_6']
        p=popup();proof=activation_popup(a,p,GAME,LABELS)
        self.assertEqual(proof['option']['text'],ACTIVATE)
        self.assertEqual(proof['option']['center'],[388,322]);self.assertEqual(proof['ok']['center'],[206,354])
        self.assertEqual(proof['source_image_sha256'],p['sha256'])
        self.assertNotIn('disband',proof['scope'].casefold())

    def test_wrong_actor_missing_body_duplicate_control_and_foreground_text_rejected(self):
        s,o,r=fixture();a=activation_candidates(s,o,r,ready=True)['activate_city_unit_6']
        for case in ('unit','home','body','duplicate','extra','low_confidence','moved'):
            p=popup()
            if case=='unit':p['lines'][1]['text']='TEST Roman Settlers'
            elif case=='home':p['lines'][2]['text']='Home City: TEST Veii'
            elif case=='body':p['lines'].pop(2)
            elif case=='duplicate':p['lines'].append(deepcopy(p['lines'][-2]))
            elif case=='extra':p['lines'].append(row('Pay 100 Gold?',x=320,y=280,w=110,h=12))
            elif case=='low_confidence':p['lines'][8]['confidence']=.4
            else:p['lines'][8]['center'][1]-=25;p['lines'][8]['bounds'][1]-=25
            with self.subTest(case=case),self.assertRaises(UnitActivationError):activation_popup(a,p,GAME,LABELS)

    def test_readback_distinguishes_exact_wake_no_effect_and_other_unit_or_turn_change(self):
        s,o,r=fixture();a=activation_candidates(s,o,r,ready=True)['activate_city_unit_6'];after=deepcopy(s)
        after['evidence']['save_sha256']='c'*64
        self.assertEqual(activation_result(a,s,after)['status'],'no_observed_change')
        after['units'][0]['order_id']=255;after['selected_unit_id']=6
        self.assertEqual(activation_result(a,s,after)['status'],'observed_expected_change')
        for case in ('reused_id','missing','movement','other_unit','turn','treasury'):
            altered=deepcopy(after)
            if case=='reused_id':altered['units'][0]['type_id']=0
            elif case=='missing':altered['units'].pop(0)
            elif case=='movement':altered['units'][0]['x']+=2
            elif case=='other_unit':altered['units'][1]['order_id']=2
            elif case=='turn':altered['turn']+=1
            else:altered['player']['treasury']+=1
            with self.subTest(case=case):self.assertEqual(activation_result(a,s,altered)['status'],'unexpected_change')

    def test_original_calibration_images_popup_and_native_readback(self):
        root=Path('.runtime/activation-calibration');bundle=Path('engine/game/civ2-win31.zip')
        if not (root/'awake-after-observation.bin').exists() or not bundle.exists():
            self.skipTest('Private original calibration unavailable')
        from civ2.memory import parse_memory
        from civ2.save import parse_rules
        from civ2.observe import recognize
        with zipfile.ZipFile(bundle) as archive:
            rules_text=archive.read('civ2/RULES.TXT').decode('cp1252')
            game_text=archive.read('civ2/GAME.TXT').decode('cp1252')
            labels_text=archive.read('civ2/LABELS.TXT').decode('cp1252')
        before=parse_memory((root/'awake-before-observation.bin').read_bytes(),rules_text,include_stack_links=True)
        after=parse_memory((root/'awake-after-observation.bin').read_bytes(),rules_text,include_stack_links=True)
        actions=activation_candidates(before,recognize(root/'ui-0000026.png'),parse_rules(rules_text),ready=True)
        self.assertEqual(list(actions),['activate_city_unit_6'])
        action=actions['activate_city_unit_6']
        proof=activation_popup(action,recognize(root/'ui-0000029.png'),game_text,labels_text)
        self.assertEqual(proof['option']['center'],[388,322])
        with self.assertRaises(UnitActivationError):
            activation_radio_proof(action,dict(recognize(root/'ui-0000029.png'),path=str(root/'ui-0000029.png')),game_text,labels_text)
        radio=activation_radio_proof(action,dict(recognize(root/'ui-0000030.png'),path=str(root/'ui-0000030.png')),game_text,labels_text)
        self.assertEqual(radio['selected_bounds'],[243,320,5,3])
        self.assertEqual(activation_result(action,before,after)['status'],'observed_expected_change')


if __name__=='__main__':unittest.main()
