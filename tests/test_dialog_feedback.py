"""Synthetic completed-click observations; no inferred effects or disabled state."""
from copy import deepcopy
import unittest
from unittest import mock
from civ2.policy import dialog_panel_signature,repeated_dialog_feedback,dialog_request_for,dialog_candidates
from civ2.revision import revision
from test_session import session,dialog


def panel():
    d=dialog('button')
    d.update(supported=True,requires_model=True,kind='test_dialog',resource_tag='TEST',
             visible_text='TEST title\nTEST original terms\nTEST first option\nTEST second option')
    d['buttons']=deepcopy(d['options'])
    return d


class DialogFeedbackTests(unittest.TestCase):
    def click(self,s,d,decision=1):
        s.decisions=decision;s._evaluate=mock.Mock(return_value=dialog_candidates(s.state,d)['option_0'])
        s.ui.observe.side_effect=[dict(sha256=d['sha256']),dict(sha256='c'*64)]
        with mock.patch('civ2.session.time.sleep'):s.choose_dialog(d)

    def test_counts_only_completed_clicks_followed_by_same_observed_panel(self):
        s=session();d=panel();self.click(s,d)
        self.assertEqual(s._dialog_repeat_records,[])
        self.assertIsNotNone(s._pending_dialog_repeat)
        s.observe_dialog_feedback(d)
        feedback=repeated_dialog_feedback(s.state,d,s._dialog_repeat_records)
        self.assertEqual(feedback['completed_click_count'],1)
        self.assertEqual(feedback['previous_choices'],[{'decision':1,'option':'TEST first option'}])
        self.assertIn('consequences are unknown',feedback['limits'])
        calls=s.game.method_calls[:];s.observe_dialog_feedback(d)
        self.assertEqual(s.game.method_calls,calls)
        self.assertEqual(len(s._dialog_repeat_records),1)  # observation is not a click
        self.click(s,d,2);s.observe_dialog_feedback(d)
        self.assertEqual(repeated_dialog_feedback(s.state,d,s._dialog_repeat_records)['completed_click_count'],2)

    def test_each_different_or_unknown_intervening_panel_resets(self):
        for case in ('title','resource','body','option','button','unknown','revision'):
            s=session();d=panel();self.click(s,d);other=deepcopy(d)
            if case=='title':other['title']='TEST changed title'
            elif case=='resource':other['resource_tag']='OTHER'
            elif case=='body':other['visible_text']+='\nDifferent terms'
            elif case=='option':other['options'][0]['text']='Different choice'
            elif case=='button':other['buttons'][0]['center'][0]+=5
            elif case=='unknown':other['supported']=False
            else:s.state['evidence']['save_sha256']='d'*64
            with self.subTest(case=case):
                s.observe_dialog_feedback(other);s.observe_dialog_feedback(d)
                self.assertEqual(s._dialog_repeat_records,[])

    def test_failed_click_never_creates_completed_observation(self):
        s=session();d=panel();s._evaluate=mock.Mock(return_value=dialog_candidates(s.state,d)['option_0'])
        s.ui.observe.return_value=dict(sha256=d['sha256']);s.game.click.side_effect=RuntimeError('TEST interrupted')
        with self.assertRaises(RuntimeError):s.choose_dialog(d)
        s.observe_dialog_feedback(d)
        self.assertEqual(s._dialog_repeat_records,[])

    def test_request_retains_all_choices_and_has_only_factual_feedback(self):
        s=session();d=panel();self.click(s,d);s.observe_dialog_feedback(d)
        original,actions=dialog_request_for(s.state,d,s.rules)
        request,after=dialog_request_for(s.state,d,s.rules,completed_dialog_clicks=s._dialog_repeat_records)
        self.assertEqual(actions,after)
        self.assertEqual(original['questions'],request['questions'])
        self.assertEqual(request['state']['mandatory_dialog']['options'],original['state']['mandatory_dialog']['options'])
        self.assertEqual(request['state']['mandatory_dialog']['previous_click_observations']['completed_click_count'],1)

    def test_incomplete_forged_or_cross_revision_records_are_not_projected(self):
        s=session();d=panel();record=dict(panel=dialog_panel_signature(d),revision=revision(s.state),
            decision=1,option='TEST first option',completed=True,observed_again=True)
        for change in ({'completed':False},{'observed_again':False},{'option':'Unknown'},
                       {'revision':{'turn':2,'save_sha256':'a'*64}},{'decision':True}):
            self.assertIsNone(repeated_dialog_feedback(s.state,d,[{**record,**change}]))
        self.assertIsNone(repeated_dialog_feedback(s.state,d,[record,record]))
        self.assertIsNone(repeated_dialog_feedback(s.state,d,[record]*25))
