"""One model intent may inspect and confirm only its exact original unit."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from civ2.activation_flow import (begin_activation, activation_step,
    dispatch_activation_step, complete_activation)
from civ2.unit_activation import activation_radio_proof, UnitActivationError
from civ2.policy import city_actions, city_action_request_for, validate_city_action
from civ2.city_controls import city_control_candidates,city_control_request_for
from civ2.dialogs import classify_dialog
from tests.test_unit_activation import fixture,popup,GAME,LABELS


def with_radio(observation, directory, selected=5):
    image=Image.new('RGB',(640,480),(195,195,195))
    for x in range(243,248):
        for y in range((195,220,246,271,296,321)[selected]-1,
                       (195,220,246,271,296,321)[selected]+2):image.putpixel((x,y),(0,0,0))
    path=Path(directory)/f'radio-{selected}.png';image.save(path)
    observation=deepcopy(observation)
    observation.update(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return observation


class FakeGame:
    def __init__(self):self.inputs=[]
    def rpc(self,method):self.inputs.append(('rpc',method))
    def click(self,x,y):
        self.inputs.append(('click',x,y));return [dict(type='TEST_CLICK',x=x,y=y)]


class FakeUI:
    def __init__(self,*images):self.images=list(images);self.game=FakeGame()
    def observe(self):return self.images.pop(0)
    def park_pointer(self):return dict(type='TEST_POINTER_PARK',issued=True)
    def key(self,key,settle):
        self.game.inputs.append(('key',key));return [dict(type='TEST_KEY',key=key)]


class ActivationFlowTests(unittest.TestCase):
    def setUp(self):
        self.state,self.image,self.rules=fixture()
        self.screen=classify_dialog(self.image,state=self.state,rules=self.rules)
        self.actions=city_actions(self.state,self.screen,rules=self.rules,
            observation=self.image,activation_ready=True)
        self.action=self.actions['activate_city_unit_6'];self.events=[]
        self.emit=lambda kind,**payload:self.events.append(dict(kind=kind,**payload))

    def begin(self):
        return begin_activation(self.action,self.state,self.image,self.rules,7,self.emit,ready=True)

    def test_wrapper_is_exactly_legacy_when_disabled_and_adds_only_optin_intents(self):
        base=city_control_candidates(self.state,self.screen,rules=self.rules)
        self.assertEqual(city_actions(self.state,self.screen,rules=self.rules),base)
        self.assertEqual(city_action_request_for(self.state,self.screen,rules=self.rules),
                         city_control_request_for(self.state,self.screen,rules=self.rules))
        request=city_action_request_for(self.state,self.screen,self.actions,rules=self.rules,
            observation=self.image,activation_ready=True)
        self.assertEqual(request['questions']['city_action']['criteria'],{i:a['label'] for i,a in self.actions.items()})
        self.assertEqual(set(self.actions)-set(base),{'activate_city_unit_6'})
        validate_city_action(self.action,self.state,self.screen,rules=self.rules,
                            observation=self.image,activation_ready=True)
        with self.assertRaises(ValueError):validate_city_action(self.action,self.state,self.screen,rules=self.rules)
        modified=deepcopy(self.actions);modified['activate_city_unit_6']['parameters']['center'][0]+=48
        with self.assertRaises(ValueError):city_action_request_for(self.state,self.screen,modified,rules=self.rules,
            observation=self.image,activation_ready=True)

    def test_reviewed_exit_and_activation_are_two_real_choices(self):
        reviewed=dict(city_id=0,city_name='TEST Rome',year_raw=-2600,
                      actions=['change_production','open_buy_quote'],labor_reassignments=40)
        actions=city_actions(self.state,self.screen,reviewed,self.rules,observation=self.image,activation_ready=True)
        self.assertEqual(set(actions),{'exit_city','activate_city_unit_6'})
        request=city_action_request_for(self.state,self.screen,actions,reviewed,self.rules,
            observation=self.image,activation_ready=True)
        self.assertEqual(set(request['questions']['city_action']['criteria']),set(actions))

    def test_confirmation_requires_unique_selected_radio_pixels_and_original_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            for selected in range(6):
                image=with_radio(popup(),directory,selected)
                if selected!=5:
                    with self.assertRaises(UnitActivationError):activation_radio_proof(self.action,image,GAME,LABELS)
                else:
                    proof=activation_radio_proof(self.action,image,GAME,LABELS)
                    self.assertEqual(proof['selected_bounds'],[243,320,5,3])
                    image['sha256']='f'*64
                    with self.assertRaises(UnitActivationError):activation_radio_proof(self.action,image,GAME,LABELS)

    def test_exact_three_inputs_then_checkpoint_are_required_for_effect(self):
        pending=self.begin()
        with patch('civ2.activation_flow.time.sleep'),tempfile.TemporaryDirectory() as directory:
            panel=with_radio(popup(),directory,1);selected=with_radio(popup(),directory,5)
            ui=FakeUI(self.image,panel)
            dispatch_activation_step(pending,ui,self.image,GAME,LABELS,self.emit)
            self.assertEqual(pending['phase'],'select_activation')
            self.assertEqual([i for i in ui.game.inputs if i[0]=='click'],[('click',264,310)])
            with self.assertRaises(UnitActivationError):complete_activation(pending,self.state,2,self.emit)
            ui=FakeUI(panel,selected)
            dispatch_activation_step(pending,ui,panel,GAME,LABELS,self.emit)
            self.assertEqual(pending['phase'],'confirm_activation')
            self.assertFalse(any(i[0]=='key' for i in ui.game.inputs))
            ui=FakeUI(selected,dict(self.image,sha256='e'*64))
            dispatch_activation_step(pending,ui,selected,GAME,LABELS,self.emit)
            self.assertEqual(pending['phase'],'checkpoint')
            self.assertEqual([i for i in ui.game.inputs if i[0]=='key'],[('key','Enter')])
            after=deepcopy(self.state);after['evidence']['save_sha256']='e'*64
            after['units'][0]['order_id']=255;after['selected_unit_id']=6
            self.assertEqual(complete_activation(pending,after,2,self.emit)['status'],'observed_expected_change')
        completed=[e['step'] for e in self.events if e['kind']=='unit_activation_step_dispatched']
        self.assertEqual(completed,['inspect_unit','select_activation','confirm_activation'])
        self.assertEqual(self.events[-1]['kind'],'unit_activation_observed')

    def test_changed_screen_sends_nothing_and_capture_failure_cannot_replay_click(self):
        pending=self.begin();ui=FakeUI(dict(self.image,sha256='f'*64))
        with self.assertRaises(UnitActivationError):dispatch_activation_step(pending,ui,self.image,GAME,LABELS,self.emit)
        self.assertEqual(ui.game.inputs,[]);self.assertEqual(pending['phase'],'inspect_unit')
        ui=FakeUI(self.image) # after-click capture unavailable
        with patch('civ2.activation_flow.time.sleep'),self.assertRaises(IndexError):
            dispatch_activation_step(pending,ui,self.image,GAME,LABELS,self.emit)
        self.assertEqual(pending['phase'],'input_uncertain')
        self.assertTrue(self.events[-1]['success_not_inferred'])
        self.assertEqual(self.events[-1]['inputs'],[dict(type='TEST_CLICK',x=264,y=310)])
        self.assertEqual(ui.game.inputs[-1],('rpc','pause'))
        with self.assertRaises(UnitActivationError):activation_step(pending,self.image,GAME,LABELS)

    def test_wrong_popup_cannot_advance_and_unexpected_native_effect_is_explicit(self):
        pending=self.begin();pending['phase']='select_activation';wrong=popup()
        wrong['lines'][1]['text']='TEST Roman Settlers'
        with self.assertRaises(UnitActivationError):activation_step(pending,wrong,GAME,LABELS)
        pending['phase']='checkpoint';after=deepcopy(self.state);after['turn']+=1
        self.assertEqual(complete_activation(pending,after,3,self.emit)['status'],'unexpected_change')
        self.assertEqual(pending['phase'],'failed_readback')


if __name__=='__main__':unittest.main()
