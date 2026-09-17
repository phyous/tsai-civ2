"""The final paint frame may get a new proof, never a relaxed classifier."""
from unittest import TestCase, mock
from test_run import frame, session
from civ2.run import observe_ready
from civ2.native_map import LEFT_MAP_REASON


class MapRecheckTests(TestCase):
    def run_case(self, reason, successful):
        pictures=[frame(i,'unknown',supported=False,reason=reason) for i in range(1,22)]
        s=session(pictures);proven=frame(30,'end_turn')
        def fallback(_session,o,d,resources,**kwargs):
            if o is pictures[-1] and successful:return proven,proven['classified']
            return o,d
        with mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kw:o['classified']), \
             mock.patch('civ2.run._native_map_fallback',side_effect=fallback) as verify, \
             mock.patch('civ2.run.time.sleep'):
            result=observe_ready(s,'TEST original resources')
        s.ui.key.assert_not_called();s.ui.select_text.assert_not_called()
        s.choose_dialog.assert_not_called()
        self.assertEqual(s.game.rpc.call_args_list,[mock.call('resume'),mock.call('pause')]*20 if reason==LEFT_MAP_REASON else [mock.call('resume'),mock.call('pause')]*8)
        return result,verify,pictures,proven

    def test_last_map_paint_frame_gets_a_fresh_bounded_proof(self):
        result,verify,pictures,proven=self.run_case(LEFT_MAP_REASON,True)
        self.assertEqual(result,(proven,proven['classified']))
        self.assertEqual(verify.call_count,7)
        self.assertIs(verify.call_args_list[-1].args[1],pictures[-1])
        self.assertEqual([c.kwargs for c in verify.call_args_list[1:]],
                         [dict(attempts=1,phase=i%3) for i in range(6)])

    def test_failed_proof_stays_unknown_without_unbounded_retries(self):
        result,verify,pictures,_=self.run_case(LEFT_MAP_REASON,False)
        self.assertEqual(verify.call_count,7)
        self.assertEqual(result,(pictures[-1],pictures[-1]['classified']))

    def test_foreground_modal_failure_never_gets_final_map_proof(self):
        result,verify,pictures,_=self.run_case('Unrecognized foreground dialog controls',True)
        self.assertEqual(verify.call_count,1)
        self.assertFalse(result[1]['supported'])

    def test_successful_interleaved_proof_stops_paint_waits_immediately(self):
        pictures=[frame(i,'unknown',supported=False,reason=LEFT_MAP_REASON) for i in range(1,6)]
        proven=frame(30,'end_turn');s=session(pictures)
        def fallback(_session,o,d,resources,**kwargs):
            return (proven,proven['classified']) if o is pictures[-1] else (o,d)
        with mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kw:o['classified']), \
             mock.patch('civ2.run._native_map_fallback',side_effect=fallback) as verify, \
             mock.patch('civ2.run.time.sleep') as sleep:
            self.assertEqual(observe_ready(s,'TEST'),(proven,proven['classified']))
        self.assertEqual(verify.call_count,3);self.assertEqual(sleep.call_count,4)
        s.ui.key.assert_not_called();s.choose_dialog.assert_not_called()
