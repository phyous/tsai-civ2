from unittest import TestCase,mock
from test_run import session,frame
from civ2.run import controller_context,_await_turn_resolution


class TurnResolutionTests(TestCase):
    def pending(self):
        s=session([]);ctx=controller_context(s)
        ctx['pending_turn']={'decision':1,'source_turn':1}
        s.checkpoint=mock.Mock()
        return s,ctx
    def test_same_turn_stale_map_waits_then_modal_is_handled_normally(self):
        s,ctx=self.pending();end=frame(1,'end_turn');notice=frame(2,'diplomacy')
        with mock.patch('civ2.run.observe_ready',return_value=(notice,notice['classified'])),mock.patch('civ2.run.time.sleep'):
            result=_await_turn_resolution(s,ctx,end,end['classified'],'TEST')
        self.assertIs(result[0],notice);self.assertIsNone(result[2]);self.assertIsNotNone(ctx['pending_turn'])
        self.assertEqual(s.game.rpc.call_args_list,[mock.call('resume'),mock.call('pause')])
        s.ui.key.assert_not_called();s.ui.select_text.assert_not_called();s.choose_dialog.assert_not_called()
    def test_later_native_turn_and_current_map_clears_pending(self):
        s,ctx=self.pending();end=frame(1,'end_turn');normal=frame(2,'normal_map')
        s.checkpoint.side_effect=lambda:s.state.update(turn=2)
        with mock.patch('civ2.run.observe_ready',return_value=(normal,normal['classified'])):
            _,_,error=_await_turn_resolution(s,ctx,end,end['classified'],'TEST')
        self.assertIsNone(error);self.assertIsNone(ctx['pending_turn']);s.game.rpc.assert_not_called()
    def test_later_turn_modal_keeps_pending_until_map(self):
        s,ctx=self.pending();end=frame(1,'end_turn');city=frame(2,'city_screen')
        s.checkpoint.side_effect=lambda:s.state.update(turn=2)
        with mock.patch('civ2.run.observe_ready',return_value=(city,city['classified'])):
            _await_turn_resolution(s,ctx,end,end['classified'],'TEST')
        self.assertIsNotNone(ctx['pending_turn'])
    def test_timeout_keeps_transaction_and_sends_no_input(self):
        s,ctx=self.pending();end=frame(1,'end_turn')
        with mock.patch('civ2.run.observe_ready',return_value=(end,end['classified'])),mock.patch('civ2.run.time.sleep'):
            _,_,error=_await_turn_resolution(s,ctx,end,end['classified'],'TEST')
        self.assertIn('still resolving',error);self.assertIsNotNone(ctx['pending_turn'])
        self.assertEqual(s.checkpoint.call_count,41);self.assertEqual(s.game.rpc.call_count,80)
        s.ui.key.assert_not_called();s.ui.select_text.assert_not_called()
    def test_reload_restores_successful_unfinished_turn_from_history(self):
        s=session([]);del s.controller['pending_turn']
        s.history=[{'decision':8,'turn':1,'action':{'kind':'finish_turn'}}]
        self.assertEqual(controller_context(s)['pending_turn'],{'decision':8,'source_turn':1})
