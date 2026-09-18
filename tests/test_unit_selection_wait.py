"""Post-combat actor gaps never synthesize a model decision or native input."""
from copy import deepcopy
from unittest import TestCase,mock

from civ2.run import _await_selected_unit,_selected_living_owned_unit,run_steps
from test_run import session,frame


def actor(identifier=74):
    return dict(id=identifier,owner=1,hp=10,type_id=4,x=10,y=10)


def ready_state():
    return dict(turn=128,year_raw=540,player={'id':1},selected_unit_id=74,units=[actor()],cities=[],
                evidence={'kind':'live_memory','observation_sha256':'a'*64})


def waiting_session(observations):
    s=session(observations);s.state=ready_state();s.state.update(selected_unit_id=None,units=[])
    s.observer=object();s.checkpoint=mock.Mock();s.choose_unit=mock.Mock();s.choose_empire=mock.Mock()
    return s


class UnitSelectionWait(TestCase):
    def invoke(self,s,current):
        with mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kw:o['classified']), \
             mock.patch('civ2.run.time.sleep') as sleep:
            result=_await_selected_unit(s,current,current['classified'],'TEST')
        return result,sleep

    def no_input(self,s):
        s.ui.key.assert_not_called();s.ui.select_text.assert_not_called();s.ui.park_pointer.assert_not_called()
        s.game.key.assert_not_called();s.game.click.assert_not_called();s.game.chord.assert_not_called()
        self.assertTrue(all(call.args[0] in ('resume','pause') for call in s.game.rpc.call_args_list))

    def test_valid_fast_path_has_no_capture_wait_checkpoint_or_extra_decision(self):
        current=frame(1,'normal_map');s=waiting_session([]);s.state=ready_state()
        (seen,dialog,error),sleep=self.invoke(s,current)
        self.assertIs(seen,current);self.assertIs(dialog,current['classified']);self.assertIsNone(error)
        s.ui.observe.assert_not_called();s.checkpoint.assert_not_called();sleep.assert_not_called()
        s.game.rpc.assert_not_called();s.choose_unit.assert_not_called()

    def test_removed_actor_waits_for_fresh_native_actor_and_post_read_frame(self):
        current=frame(1,'normal_map');before=frame(2,'normal_map');after=frame(3,'normal_map')
        s=waiting_session([before,after]);s.checkpoint.side_effect=lambda:s.state.update(ready_state())
        (seen,dialog,error),sleep=self.invoke(s,current)
        self.assertIs(seen,after);self.assertIsNone(error);self.assertTrue(_selected_living_owned_unit(s.state))
        s.checkpoint.assert_called_once();self.assertEqual(s.ui.observe.call_count,2)
        sleep.assert_called_once_with(.25)
        self.assertEqual(s.game.rpc.call_args_list,[mock.call('resume'),mock.call('pause')])
        s.choose_unit.assert_not_called();self.no_input(s)

    def test_modal_endturn_and_unknown_yield_before_any_modal_checkpoint(self):
        for kind,supported in (('diplomacy',True),('end_turn',True),('unknown',False)):
            with self.subTest(kind=kind):
                current=frame(1,'normal_map');next_frame=frame(2,kind,supported=supported)
                s=waiting_session([next_frame]);(seen,dialog,error),_=self.invoke(s,current)
                self.assertIs(seen,next_frame);self.assertIsNone(error)
                s.checkpoint.assert_not_called();s.choose_unit.assert_not_called();self.no_input(s)

    def test_modal_arriving_during_checkpoint_beats_even_a_valid_actor(self):
        current=frame(1,'normal_map');normal=frame(2,'normal_map');modal=frame(3,'diplomacy')
        s=waiting_session([normal,modal]);s.checkpoint.side_effect=lambda:s.state.update(ready_state())
        (seen,dialog,error),_=self.invoke(s,current)
        self.assertIs(seen,modal);self.assertEqual(dialog['kind'],'diplomacy');self.assertIsNone(error)
        s.choose_unit.assert_not_called();self.no_input(s)

    def test_absent_duplicate_foreign_dead_or_unresolved_actor_stops_after_eight(self):
        base=ready_state()
        variants=[{**base,'selected_unit_id':None,'units':[]},
                  {**base,'selected_unit_id':73},
                  {**base,'units':[actor(),actor()]},
                  {**base,'units':[{**actor(),'owner':2}]},
                  {**base,'units':[{**actor(),'hp':0}]},
                  {**base,'units':[{k:v for k,v in actor().items() if k!='hp'}]},
                  {**base,'units':[{**actor(),'hp':True}]},
                  {**base,'units':[{**actor(),'owner':True}]},
                  {**base,'selected_unit_id':True,'units':[actor(True)]}]
        for index,state in enumerate(variants):
            with self.subTest(index=index):
                current=frame(1,'normal_map');s=waiting_session([current]*16);s.state=deepcopy(state)
                (_,_,error),sleep=self.invoke(s,current)
                self.assertIn('no unit decision issued',error)
                self.assertEqual(sleep.call_count,8);self.assertEqual(s.checkpoint.call_count,8)
                self.assertEqual(s.game.rpc.call_args_list,[mock.call('resume'),mock.call('pause')]*8)
                self.assertEqual(s.decisions,0);s.choose_unit.assert_not_called();self.no_input(s)

    def test_save_backed_gap_stops_without_extra_save_or_resume(self):
        current=frame(1,'normal_map');s=waiting_session([]);s.observer=None
        (_,_,error),sleep=self.invoke(s,current)
        self.assertIn('no unit decision issued',error);sleep.assert_not_called()
        s.checkpoint.assert_not_called();s.game.rpc.assert_not_called();self.no_input(s)

    def test_wait_error_still_pauses_and_ocr_error_is_not_hidden(self):
        current=frame(1,'normal_map');s=waiting_session([])
        with mock.patch('civ2.run.time.sleep',side_effect=RuntimeError('TEST interrupted')):
            with self.assertRaisesRegex(RuntimeError,'TEST interrupted'):
                _await_selected_unit(s,current,current['classified'],'TEST')
        self.assertEqual(s.game.rpc.call_args_list,[mock.call('resume'),mock.call('pause')]);self.no_input(s)
        s=waiting_session([]);s.ui.observe.side_effect=ValueError('TEST strict OCR')
        with self.assertRaisesRegex(ValueError,'TEST strict OCR'):self.invoke(s,current)
        s.checkpoint.assert_not_called();self.no_input(s)


class UnitSelectionLoop(TestCase):
    no_input=UnitSelectionWait.no_input
    def run_loop(self,s):
        with mock.patch('civ2.run.game_text',return_value='TEST'), \
             mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kw:o['classified']), \
             mock.patch('civ2.run.time.sleep'):
            return run_steps(s,max_decisions=1)

    def test_loop_only_chooses_unit_after_fresh_actor_and_current_normal_map(self):
        normal=frame(1,'normal_map');s=waiting_session([normal]*3);checks=0
        def checkpoint():
            nonlocal checks
            checks+=1
            if checks==2:s.state.update(ready_state())
        s.checkpoint.side_effect=checkpoint
        def choose():
            self.assertEqual(checks,2);self.assertTrue(_selected_living_owned_unit(s.state))
            s.decisions+=1
        s.choose_unit.side_effect=choose
        self.run_loop(s);s.choose_unit.assert_called_once();s.choose_dialog.assert_not_called();self.no_input(s)

    def test_loop_yields_real_modal_to_independent_dialog_choice(self):
        normal=frame(1,'normal_map');modal=frame(2,'diplomacy',requires_model=True,options=[{},{}])
        s=waiting_session([normal,modal,modal])
        self.run_loop(s)
        s.choose_dialog.assert_called_once_with(modal['classified']);s.choose_unit.assert_not_called()
        s.checkpoint.assert_called_once();self.no_input(s)

    def test_loop_yields_real_endturn_to_independent_empire_choice(self):
        normal=frame(1,'normal_map');end=frame(2,'end_turn')
        s=waiting_session([normal,end,end,end])
        def choose(dialog,reviewed):
            self.assertEqual(dialog['kind'],'end_turn')
            self.assertEqual(s.checkpoint.call_count,2)
            s.decisions+=1
            return {'id':'finish_turn'},normal
        s.choose_empire.side_effect=choose
        self.run_loop(s)
        s.choose_empire.assert_called_once();s.choose_unit.assert_not_called();s.choose_dialog.assert_not_called()
        self.no_input(s)

    def test_loop_stops_on_unknown_and_never_enters_pointer_recovery(self):
        normal=frame(1,'normal_map');unknown=frame(2,'unknown',supported=False)
        s=waiting_session([normal,unknown]);result=self.run_loop(s)
        self.assertFalse(result['classification']['supported']);self.assertEqual(s.decisions,0)
        s.choose_unit.assert_not_called();s.choose_dialog.assert_not_called();self.no_input(s)
