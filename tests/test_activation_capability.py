from types import SimpleNamespace
from unittest import TestCase,mock
from civ2.session import Session
from civ2.unit_activation import CALIBRATION

class ActivationCapabilityTests(TestCase):
    def session(self):
        s=SimpleNamespace(pending_decisions=[],game=mock.Mock(),journal=mock.Mock())
        s.game.rpc.return_value={'paused':True,'heldKeys':[],'buttons':0}
        return s
    def test_explicit_enable_only_records_capability_once(self):
        s=self.session();Session.enable_unit_activation(s);Session.enable_unit_activation(s)
        s.game.rpc.assert_called_once_with('status')
        s.journal.append.assert_called_once_with('unit_activation_enabled',calibration=CALIBRATION,executes_input=False)
        self.assertTrue(s.unit_activation_enabled)
    def test_pending_orders_prevent_enable(self):
        s=self.session();s.pending_decisions=[1]
        with self.assertRaises(RuntimeError):Session.enable_unit_activation(s)
        s.journal.append.assert_not_called();s.game.rpc.assert_not_called()
    def test_unclear_input_state_prevents_enable(self):
        for status in ({},{'paused':False,'heldKeys':[],'buttons':0},
                       {'paused':True,'heldKeys':['KeyA'],'buttons':0},{'paused':True,'heldKeys':[],'buttons':1}):
            s=self.session();s.game.rpc.return_value=status
            with self.assertRaises(RuntimeError):Session.enable_unit_activation(s)
            s.journal.append.assert_not_called()
