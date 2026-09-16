"""HUD dispatch provenance; synthetic TEST observations, no game or API calls."""
from copy import deepcopy
from unittest import mock
import unittest

from civ2.empire import empire_candidates
from civ2.policy import dialog_candidates, unit_candidates
from test_session import session, dialog
from test_session_planning import session as planning_session


def selected(s, action, question):
    s._evaluate=mock.Mock(return_value=action)
    s.decision=dict(id=s.decisions,stage='command',authorizes_input=True,
        selected_question=question,answers={question:{'choice':action['id']}},
        action_label=action['label'],receipt='pending')


def end_turn(s):
    s.state['player']['government_id']=1
    return dict(kind='end_turn',supported=True,title='End of Turn',options=[],
                sha256='b'*64,width=640,height=480)


@mock.patch('civ2.session.time.sleep')
class SessionReceiptTests(unittest.TestCase):
    def test_unit_input_marks_dispatch_even_without_visible_game_change(self, sleep):
        s=session(); action=unit_candidates(s.state,rules=s.rules)['move_e']
        selected(s,action,'unit_action')
        s.ui.observe.return_value={'sha256':'b'*64}
        published=[]; s.publish.side_effect=lambda *args: published.append(deepcopy(s.decision))
        s.choose_unit()
        self.assertEqual(s.decision['receipt'],'dispatched')
        self.assertEqual(published[-1]['receipt'],'dispatched')
        self.assertNotEqual(s.decision['receipt'],'accepted')

    def test_unit_input_failure_leaves_decision_pending(self, sleep):
        s=session(); action=unit_candidates(s.state,rules=s.rules)['move_e']
        selected(s,action,'unit_action'); s.ui.observe.return_value={'sha256':'b'*64}
        s.ui.key.side_effect=RuntimeError('TEST input failed')
        with self.assertRaisesRegex(RuntimeError,'TEST input failed'): s.choose_unit()
        self.assertEqual(s.decision['receipt'],'pending')
        self.assertFalse(any(c.args[0]=='command_dispatched' for c in s.journal.append.call_args_list))

    def test_dialog_buttons_and_confirmed_lists_mark_dispatch(self, sleep):
        for control in ('button','list_item'):
            with self.subTest(control=control):
                s=session(); d=dialog(control); action=dialog_candidates(s.state,d)['option_0']
                selected(s,action,'dialog_action')
                s.ui.observe.side_effect=[{'sha256':d['sha256']},{'sha256':'c'*64}]
                s.choose_dialog(d)
                self.assertEqual(s.decision['receipt'],'dispatched')

    def test_partial_list_selection_does_not_claim_full_command_dispatch(self, sleep):
        s=session(); d=dialog(); action=dialog_candidates(s.state,d)['option_0']
        selected(s,action,'dialog_action'); s.ui.observe.return_value={'sha256':d['sha256']}
        s.ui.key.side_effect=RuntimeError('TEST confirmation failed')
        with self.assertRaisesRegex(RuntimeError,'TEST confirmation failed'): s.choose_dialog(d)
        s.game.click.assert_called_once()
        self.assertEqual(s.decision['receipt'],'pending')

    def test_stale_dialog_does_not_relabel_pending_model_choice(self, sleep):
        s=session(); d=dialog(); action=dialog_candidates(s.state,d)['option_0']
        selected(s,action,'dialog_action'); s.ui.observe.return_value={'sha256':'c'*64}
        with self.assertRaisesRegex(RuntimeError,'changed during inference'): s.choose_dialog(d)
        s.game.click.assert_not_called(); self.assertEqual(s.decision['receipt'],'pending')

    def test_model_empire_key_and_chord_mark_dispatch(self, sleep):
        for identifier in ('finish_turn','open_tax'):
            with self.subTest(identifier=identifier):
                s=session(); screen=end_turn(s); reviewed={'turn':1,'actions':[]}
                action=empire_candidates(s.state,screen,reviewed,s.rules)[identifier]
                selected(s,action,'empire_action')
                s.ui.observe.side_effect=[{'sha256':screen['sha256']},{'sha256':'c'*64}]
                s.game.chord.return_value=[{'type':'key','code':'KeyT','down':True}]
                s.choose_empire(screen,reviewed)
                self.assertEqual(s.decision['receipt'],'dispatched')

    def test_forced_empire_action_does_not_relabel_unrelated_decision(self, sleep):
        s=session(); screen=end_turn(s)
        reviewed={'turn':1,'actions':['open_tax','open_research']}
        self.assertEqual(len(empire_candidates(s.state,screen,reviewed,s.rules)),1)
        selected(s,unit_candidates(s.state,rules=s.rules)['move_e'],'unit_action')
        original=deepcopy(s.decision)
        s.ui.observe.side_effect=[{'sha256':screen['sha256']},{'sha256':'c'*64}]
        s.choose_empire(screen,reviewed)
        s._evaluate.assert_not_called()
        self.assertEqual(s.decision,original)

    def test_planning_stage_has_no_receipt_but_subsequent_unit_dispatch_does(self, sleep):
        s=planning_session()
        views=[]; s.publish.side_effect=lambda *args: views.append(deepcopy(s.decision))
        s.choose_unit()
        self.assertIsNone(views[0]['receipt'])
        self.assertEqual(views[0]['stage'],'planning')
        self.assertEqual(views[-1]['receipt'],'dispatched')
        self.assertEqual(views[-1]['id'],2)
        self.assertEqual(s.pending_decisions,[2])

    def test_mismatched_choice_or_stage_and_missing_receipts_never_mark_dispatch(self, sleep):
        for mutation,inputs in [({'id':99},[{'issued':True}]),
                ({'stage':'planning'},[{'issued':True}]),
                ({'answers':{'unit_action':{'choice':'skip'}}},[{'issued':True}]),
                ({},[]),({},[{'issued':False}])]:
            with self.subTest(mutation=mutation,inputs=inputs):
                s=session(); action=unit_candidates(s.state,rules=s.rules)['move_e']
                selected(s,action,'unit_action'); s.decision.update(mutation)
                s._mark_dispatched(s.decisions,'unit_action',action,inputs)
                self.assertEqual(s.decision['receipt'],'pending')


if __name__ == '__main__': unittest.main()
