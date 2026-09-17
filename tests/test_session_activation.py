from collections import deque
from copy import deepcopy
import tempfile
from unittest import TestCase,mock
from civ2.session import Session
from civ2.dialogs import classify_dialog
from test_unit_activation import fixture,popup,GAME,LABELS
from test_activation_flow import FakeUI,with_radio


class SessionActivationTests(TestCase):
    def session(self):
        s=Session.__new__(Session);s.state,self.image,s.rules=fixture()
        self.dialog=classify_dialog(self.image,state=s.state,rules=s.rules)
        s.unit_activation_enabled=True;s.decisions=6;s.pending_decisions=[]
        s.history=deque();s.chronicle=deque();s.journal=mock.Mock();s.publish=mock.Mock()
        s.ui=FakeUI(self.image);s.game=s.ui.game;s._mark_dispatched=mock.Mock()
        def evaluate(request,actions,question):
            self.request=request;s.decisions+=1;return actions['activate_city_unit_6']
        s._evaluate=mock.Mock(side_effect=evaluate)
        return s
    def choose(self,s):
        return s.choose_city_control(self.dialog,None,labor_ready=True,
            observation=self.image,activation_ready=True)
    def test_real_candidate_selection_starts_intent_without_claiming_dispatch(self):
        s=self.session();action,_=self.choose(s)
        self.assertEqual(action['kind'],'unit_activation');self.assertEqual(s.pending_unit_activation['phase'],'inspect_unit')
        self.assertIn(action['id'],self.request['questions']['city_action']['criteria'])
        self.assertEqual(s.game.inputs,[]);s._mark_dispatched.assert_not_called();self.assertEqual(len(s.history),0)
    def test_capability_and_fresh_review_required_before_inference(self):
        for enabled,ready in ((False,True),(True,False)):
            s=self.session();s.unit_activation_enabled=enabled
            with self.assertRaises(RuntimeError):s.choose_city_control(self.dialog,None,labor_ready=ready,
                observation=self.image,activation_ready=True)
            s._evaluate.assert_not_called()
    def test_confirmation_then_actual_readback_records_order_only(self):
        s=self.session();self.choose(s);pending=s.pending_unit_activation;pending['phase']='confirm_activation'
        with tempfile.TemporaryDirectory() as directory:
            radio=with_radio(popup(),directory);end=deepcopy(self.image)
            s.ui=FakeUI(radio,end);s.game=s.ui.game
            with mock.patch('civ2.activation_flow.time.sleep'):
                s.advance_unit_activation(radio,{'kind':'unknown','supported':False},GAME,LABELS)
        self.assertEqual(pending['phase'],'checkpoint');s._mark_dispatched.assert_called_once()
        self.assertEqual(s.history[-1]['action']['kind'],'unit_activation')
        self.assertNotIn('Native activation checkpoint',s.history[-1]['outcome'])
        after=deepcopy(s.state);after['selected_unit_id']=6
        next(u for u in after['units'] if u['id']==6)['order_id']=255
        after['evidence']['save_sha256']='f'*64
        def checkpoint():s.state=after;s.checkpoints=1
        s.checkpoint=mock.Mock(side_effect=checkpoint)
        result=s.advance_unit_activation(end,{'kind':'normal_map','supported':True},GAME,LABELS)
        self.assertEqual(result['status'],'observed_expected_change')
        self.assertIsNone(s.pending_unit_activation)
        self.assertIn('observed_expected_change',s.history[-1]['outcome'])
    def test_no_checkpoint_until_original_map_returns(self):
        s=self.session();self.choose(s);s.pending_unit_activation['phase']='checkpoint';s.checkpoint=mock.Mock()
        with self.assertRaises(RuntimeError):s.advance_unit_activation(self.image,{'kind':'city_screen','supported':True},GAME,LABELS)
        s.checkpoint.assert_not_called()
