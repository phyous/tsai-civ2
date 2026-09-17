"""Observed repetition is factual model context, never an action-space filter."""
from copy import deepcopy
import unittest

from civ2.policy import unit_candidates, unit_request_for, RECENT_ACTION_LIMIT
from civ2.session import observed_order_outcome
from test_policy import fixture, rules


def attempted(state, identifier='move_e', decision=1):
    action = unit_candidates(state, rules=rules())[identifier]
    record = dict(turn=state['turn'], decision=decision, action=action)
    record['outcome'], record['observed_delta'] = observed_order_outcome(
        state, deepcopy(state), record, pending_count=1)
    return record


class MoveFeedbackTests(unittest.TestCase):
    def request(self, state, records):
        actions = unit_candidates(state, rules=rules())
        original = deepcopy((state, actions, records))
        result = unit_request_for(state, actions, rules(), recent_actions=records)
        self.assertEqual((state, actions, records), original)
        self.assertEqual(result['questions']['unit_action']['criteria'],
                         {key:value['label'] for key,value in actions.items()})
        return result

    def test_actual_checkpoint_delta_is_prominent_and_bounded(self):
        state = fixture(1)
        rows = [attempted(state, decision=i+1) for i in range(40)]
        request = self.request(state, rows)
        feedback = request['state']['unit_action_feedback']
        self.assertEqual(feedback['by_candidate'], {'move_e':dict(
            no_observed_change_count=RECENT_ACTION_LIMIT,
            destination=dict(x=10,y=8),most_recent_decision=40)})
        self.assertEqual(feedback['observed_fields'],
                         ['position','movement_thirds_spent','order_id'])
        self.assertTrue(request['questions']['unit_action']['instructions'].startswith(
            'Observed feedback for these exact offered moves: move_e: 24 attempts with no observed change.'))
        self.assertNotIn('illegal', request['questions']['unit_action']['instructions'])

    def test_no_free_text_success_flag_or_ambiguous_identity_can_supply_count(self):
        state = fixture(1)
        original = attempted(state)
        variants = []
        text_only = deepcopy(original);text_only.pop('observed_delta')
        text_only.update(outcome='No observed state change',receipt={'state_changed':False})
        variants.append(text_only)
        for field,value in [('actor_binding','unavailable'),('turn',[1,2]),
                ('position',[[8,8],[10,8]]),('movement_thirds_spent',[0,1]),('order_id',[255,2])]:
            changed=deepcopy(original);changed['observed_delta'][field]=value;variants.append(changed)
        for bad in variants:
            with self.subTest(bad=bad):
                self.assertNotIn('unit_action_feedback',self.request(state,[original,bad])['state'])

    def test_actor_turn_target_and_pending_record_break_tail(self):
        state = fixture(1)
        for mutation in ('owner','type_id','id','position','turn','target','pending','unoffered'):
            bad = attempted(state)
            if mutation in ('owner','type_id','id'):bad['action']['actor'][mutation]+=1
            elif mutation=='position':bad['action']['actor']['x']+=2
            elif mutation=='turn':bad['turn']=0
            elif mutation=='target':bad['action']['parameters']['destination']['x']+=2
            elif mutation=='pending':bad.pop('observed_delta')
            else:bad['action']['id']='move_unoffered'
            with self.subTest(mutation=mutation):
                result = self.request(state,[attempted(state),bad,attempted(state,decision=3)])
                self.assertEqual(result['state']['unit_action_feedback']['by_candidate']['move_e']['no_observed_change_count'],1)

    def test_changed_current_native_fields_do_not_reuse_old_counts(self):
        state = fixture(1);record=attempted(state)
        for key,value in [('turn',2),('movement_thirds_spent',1),('order_id',2)]:
            changed=deepcopy(state)
            if key=='turn':changed[key]=value
            else:changed['units'][0][key]=value
            self.assertNotIn('unit_action_feedback',self.request(changed,[record])['state'])

    def test_multiple_directions_count_independently_and_nonmoves_are_not_failures(self):
        state = fixture(1)
        request=self.request(state,[attempted(state,'move_w',1),attempted(state,'move_e',2)])
        self.assertEqual(set(request['state']['unit_action_feedback']['by_candidate']),{'move_e','move_w'})
        self.assertNotIn('unit_action_feedback',self.request(state,[attempted(state,'fortify')])['state'])
        worker=fixture(0)
        self.assertNotIn('unit_action_feedback',self.request(worker,[attempted(worker,'settle')])['state'])

    def test_old_slot_type_does_not_transfer_feedback_and_generator_is_supported(self):
        state=fixture(1);record=attempted(state)
        changed=fixture(0)
        self.assertNotIn('unit_action_feedback',self.request(changed,[record])['state'])
        result=unit_request_for(state,unit_candidates(state,rules=rules()),rules(),
                                recent_actions=(r for r in [record]))
        self.assertEqual(result['state']['unit_action_feedback']['by_candidate']['move_e']['no_observed_change_count'],1)


if __name__=='__main__':unittest.main()
