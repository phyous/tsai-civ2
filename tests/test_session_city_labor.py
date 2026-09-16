"""Exact Jev-selected labor click dispatch, without actual UI/API calls."""
from unittest import mock
import unittest
from civ2.city_controls import city_control_candidates
from test_city_labor_controls import inputs
from test_city_controls import reviewed
from test_session_planning import session,TestClient,events


class LaborClient(TestClient):
    def evaluate(self,state,questions):
        result=super().evaluate(state,questions);keys=questions['city_action']['criteria']
        result['answers']['city_action']=dict(type='choice',choice='labor_remove_worker_2',confidence=1.,
            probabilities={k:float(k=='labor_remove_worker_2') for k in keys})
        return result


class SessionLaborTests(unittest.TestCase):
    @mock.patch('civ2.session.time.sleep')
    def test_selected_labor_dispatches_one_calibrated_click_without_auto_reallocation(self,sleep):
        s=session(False);s.state,screen,s.rules=inputs();s.client=LaborClient()
        s.ui.observe.side_effect=[{'sha256':screen['sha256']},{'sha256':'c'*64}]
        s.game.click.return_value=[{'issued':True}]
        action,_=s.choose_city_control(screen,reviewed(),labor_ready=True)
        self.assertEqual(action['kind'],'city_labor');s.game.click.assert_called_once_with(56,192)
        s.ui.key.assert_not_called();self.assertEqual(s.pending_decisions,[1])
        self.assertEqual(s.decision['receipt'],'dispatched');self.assertEqual(s.decision['selected_question'],'city_action')
        request=s.client.requests[0]
        self.assertTrue(request['state']['city_control_review']['labor_checkpoint_ready'])
        self.assertEqual(request['state']['city_control_review']['labor_review']['remaining'],2)
        self.assertEqual(events(s,'city_control_dispatched')[0]['action'],action)
        self.assertNotIn('accepted',s.history[-1]['outcome'])

    @mock.patch('civ2.session.time.sleep')
    def test_labor_without_ready_flag_or_after_changed_image_cannot_dispatch(self,sleep):
        for ready,changed in ((False,False),(True,True)):
            s=session(False);s.state,screen,s.rules=inputs()
            action=city_control_candidates(s.state,screen,rules=s.rules,labor_ready=True)['labor_remove_worker_2']
            s._evaluate=mock.Mock(return_value=action)
            s.ui.observe.return_value={'sha256':'c'*64 if changed else screen['sha256']}
            with self.assertRaises((ValueError,RuntimeError)):
                s.choose_city_control(screen,reviewed(),labor_ready=ready)
            s.game.click.assert_not_called()


if __name__=='__main__':unittest.main()
