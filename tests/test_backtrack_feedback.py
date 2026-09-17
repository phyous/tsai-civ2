"""Native movement history is context, not legality or a durable unit ID."""
from copy import deepcopy
import unittest
from civ2.policy import unit_candidates,unit_request_for,_backtrack_feedback
from civ2.session import observed_order_outcome
from test_policy import fixture,rules


def move(before,identifier,decision):
    a=unit_candidates(before,rules=rules())[identifier]
    after=deepcopy(before);u=after['units'][0];u.update(a['parameters']['destination'])
    u['movement_thirds_spent']=3;after['evidence']['save_sha256']=f'{decision:064x}'
    record=dict(turn=before['turn'],decision=decision,action=a)
    record['outcome'],record['observed_delta']=observed_order_outcome(before,after,record,pending_count=1)
    after['units'][0]['movement_thirds_spent']=0
    return after,record


def oscillation():
    state=fixture(1);rows=[]
    for index,direction in enumerate(('move_e','move_w','move_e'),1):
        state,record=move(state,direction,index);rows.append(record)
        state['turn']+=1
        rows.append(dict(turn=state['turn']-1,action=dict(id='finish_turn',kind='empire',actor={})))
    return state,rows


class BacktrackFeedbackTests(unittest.TestCase):
    def test_exact_endpoint_chain_counts_visits_and_reversal_without_filtering(self):
        state,rows=oscillation();a=unit_candidates(state,rules=rules());old=deepcopy((state,rows,a))
        r=unit_request_for(state,a,rules(),recent_actions=rows);f=r['state']['unit_movement_history_feedback']
        self.assertEqual(f['by_candidate']['move_w'],dict(destination=dict(x=8,y=8),prior_observed_visits=2,
            last_observed_visit_turn=2,reverses_most_recent_observed_move=True))
        self.assertEqual([m['turn'] for m in f['observed_moves']],[1,2,3]);self.assertEqual(f['current_turn'],4)
        self.assertTrue(f['intervening_other_commands']);self.assertIn('not a persistent-ID claim',f['scope'])
        self.assertEqual(r['questions']['unit_action']['criteria'],{k:v['label'] for k,v in a.items()})
        self.assertEqual((state,rows,a),old)

    def test_identity_endpoint_ambiguity_and_inferred_success_break_the_chain(self):
        for mode in ('owner','type','slot','endpoint','ambiguous','missing','string_only','future','before','destination'):
            state,rows=oscillation();target=rows[2]
            if mode in ('owner','type','slot'):target['action']['actor'][{'type':'type_id','slot':'id'}.get(mode,mode)]+=1
            elif mode=='endpoint':target['observed_delta']['position'][1][0]+=2
            elif mode=='ambiguous':target['observed_delta']['actor_binding']='unavailable'
            elif mode=='missing':target.pop('observed_delta')
            elif mode=='string_only':target['observed_delta']='Moved west successfully'
            elif mode=='future':target['observed_delta']['turn']=[50,50];target['turn']=50
            elif mode=='before':target['observed_delta']['position'][0][0]+=2
            else:target['action']['parameters']['destination']['x']+=2
            with self.subTest(mode=mode):
                f=_backtrack_feedback(state,unit_candidates(state,rules=rules()),rows)
                self.assertIsNone(f)

    def test_no_change_is_not_an_arrival_and_only_actual_offered_destinations_get_feedback(self):
        state,rows=oscillation();a=unit_candidates(state,rules=rules())
        nochange=dict(turn=state['turn'],decision=9,action=deepcopy(a['move_w']))
        nochange['outcome'],nochange['observed_delta']=observed_order_outcome(state,deepcopy(state),nochange,pending_count=1)
        f=_backtrack_feedback(state,a,rows+[nochange])
        self.assertEqual(f['by_candidate']['move_w']['prior_observed_visits'],2)
        self.assertEqual(len(f['observed_moves']),3)
        del a['move_w']
        self.assertIsNone(_backtrack_feedback(state,a,rows+[nochange]))

    def test_changed_current_position_and_new_type_cannot_reuse_path(self):
        for key,value in (('x',12),('owner',2),('type_id',0)):
            state,rows=oscillation();state['units'][0][key]=value
            self.assertIsNone(_backtrack_feedback(state,{},rows))

    def test_one_move_or_only_text_does_not_trigger_backtrack_instruction(self):
        state,record=move(fixture(1),'move_e',1)
        a=unit_candidates(state,rules=rules())
        self.assertNotIn('unit_movement_history_feedback',unit_request_for(state,a,rules(),[record])['state'])
        self.assertIsNone(_backtrack_feedback(state,a,[{'outcome':'Position changed (8,8)->(10,8)'}]))


if __name__=='__main__':unittest.main()
