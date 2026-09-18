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

class ProductionReturnTests(TestCase):
    def ready(self):
        s=session([]);ctx=controller_context(s)
        ctx['pending_turn']={'decision':506,'source_turn':122}
        s.decisions=507;s.pending_decisions=[]
        s.state.update(turn=122,evidence={'kind':'live_memory','observation_sha256':'a'*64},
            player={'id':1},selected_unit_id=30,units=[dict(id=30,owner=1,hp=10,
                movement_thirds_spent=0,order_id=255,waiting=False)])
        s.history=[dict(decision=506,turn=122,action={'kind':'finish_turn'}),
            dict(decision=507,turn=122,action=dict(kind='dialog_choice',
                actor={'id':'production_notice'},parameters={'observed_text':'• Continue'},
                preconditions={'image_sha256':'b'*64}))]
        s.checkpoint=mock.Mock()
        return s,ctx

    def test_real_production_continue_can_return_same_turn_to_own_input(self):
        s,ctx=self.ready();normal=frame(4,'normal_map')
        with mock.patch('civ2.run.observe_ready',return_value=(normal,normal['classified'])):
            _,_,error=_await_turn_resolution(s,ctx,normal,normal['classified'],'TEST')
        self.assertIsNone(error);self.assertIsNone(ctx['pending_turn'])
        proof=s.journal.append.call_args.kwargs
        self.assertEqual(proof['finish_decision'],506)
        self.assertEqual(proof['continue_decision'],507)
        self.assertFalse(proof['turn_advanced']);self.assertFalse(proof['executes_input'])
        s.game.rpc.assert_not_called();s.choose_dialog.assert_not_called()

    def test_enemy_dead_spent_busy_waiting_or_ambiguous_unit_cannot_resolve(self):
        from civ2.run import _production_return_to_unit
        for key,value in [('owner',2),('hp',0),('movement_thirds_spent',1),
                          ('order_id',2),('waiting',True)]:
            s,ctx=self.ready();s.state['units'][0][key]=value
            self.assertIsNone(_production_return_to_unit(s,ctx,{'kind':'normal_map','supported':True}))
        s,ctx=self.ready();s.state['units']*=2
        self.assertIsNone(_production_return_to_unit(s,ctx,{'kind':'normal_map','supported':True}))

    def test_stale_map_wrong_dialog_or_intervening_command_cannot_resolve(self):
        from civ2.run import _production_return_to_unit
        for mutation in ('end','unsupported','notice','choice','decision','pending','transaction','revision'):
            s,ctx=self.ready();d={'kind':'normal_map','supported':True}
            if mutation=='end':d['kind']='end_turn'
            elif mutation=='unsupported':d['supported']=False
            elif mutation=='notice':s.history[-1]['action']['actor']['id']='diplomacy'
            elif mutation=='choice':s.history[-1]['action']['parameters']['observed_text']='Zoom to City'
            elif mutation=='decision':s.decisions+=1
            elif mutation=='pending':s.pending_decisions=[507]
            elif mutation=='transaction':ctx['pending_trade']={}
            elif mutation=='revision':s.state['evidence']={}
            self.assertIsNone(_production_return_to_unit(s,ctx,d),mutation)
