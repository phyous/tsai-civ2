"""Bounded HUD history is telemetry, not commands or model context."""
from copy import deepcopy
import unittest
from civ2.session import Session, _primary_decision_snapshot, snapshot
from test_session import session, state


def decision(identifier, stage='command'):
    return dict(id=identifier,model='jev-test',observed_turn=2,stage=stage,
        selected_question='unit_action',action_label='TEST skip',receipt='pending',
        executes_input=stage!='planning',
        answers={'unit_action':{'type':'choice','choice':'skip','probabilities':{'skip':.7,'move':.3}},
                 'empire_strategy':{'type':'choice','choice':'Cities','probabilities':{'Cities':.8,'War':.2}}},
        labels={'unit_action':{'skip':'TEST Skip','move':'TEST Move'},'empire_strategy':{'Cities':'TEST Cities'}})


class DashboardHistoryTests(unittest.TestCase):
    def test_empty_publish_has_no_manufactured_history_or_events(self):
        s=session();Session.publish(s)
        self.assertEqual(s.game.state.call_args.args[0]['recent_decisions'],[])
        s.journal.append.assert_not_called();s.game.rpc.assert_not_called()

    def test_repeated_publish_updates_receipt_without_duplicating_decision(self):
        s=session();s.decision=decision(1);Session.publish(s)
        s.decision['receipt']='dispatched';Session.publish(s)
        self.assertEqual(s.game.state.call_args.args[0]['recent_decisions'],[])
        s.decision=decision(2);Session.publish(s)
        recent=s.game.state.call_args.args[0]['recent_decisions']
        self.assertEqual([d['id'] for d in recent],[1]);self.assertEqual(recent[0]['receipt'],'dispatched')
        self.assertEqual(set(recent[0]['answers']),{'unit_action'})

    def test_bounded_history_preserves_exact_probabilities_without_affecting_gameplay(self):
        s=session();history=deepcopy(s.history);pending=list(s.pending_decisions)
        for identifier in range(1,8):
            s.decision=decision(identifier);Session.publish(s)
        recent=s.game.state.call_args.args[0]['recent_decisions']
        self.assertEqual([d['id'] for d in recent],[4,5,6]);self.assertEqual(len(s._published_decisions),4)
        self.assertEqual(recent[-1]['answers']['unit_action']['probabilities'],{'skip':.7,'move':.3})
        self.assertEqual(s.history,history);self.assertEqual(s.pending_decisions,pending)
        self.assertEqual(s.decisions,1);s.journal.append.assert_not_called();s.game.rpc.assert_not_called()

    def test_mutable_current_response_cannot_change_retained_past_distribution(self):
        s=session();previous=decision(1);s.decision=previous;Session.publish(s)
        s.decision=decision(2);Session.publish(s)
        previous['answers']['unit_action']['probabilities']['skip']=0
        recent=s.game.state.call_args.args[0]['recent_decisions'];recent[0]['labels']['unit_action']['skip']='changed'
        self.assertEqual(s._published_decisions[0]['answers']['unit_action']['probabilities']['skip'],.7)
        self.assertEqual(s._published_decisions[0]['labels']['unit_action']['skip'],'TEST Skip')

    def test_planning_stage_remains_no_input_and_unknown_fields_are_excluded(self):
        d=decision(1,'planning');d['private_test']='do not project'
        saved=_primary_decision_snapshot(d)
        self.assertEqual(saved['stage'],'planning');self.assertFalse(saved['executes_input'])
        self.assertNotIn('private_test',saved)
        for bad in (None,{}, {'id':1,'answers':None}, {**d,'selected_question':'absent'}, {**d,'id':True}):
            self.assertIsNone(_primary_decision_snapshot(bad))


if __name__=='__main__':unittest.main()
