"""Offline runner-contract tests. All observations and inputs are synthetic TEST data."""
from collections import deque
import copy
import hashlib
from unittest import mock
import unittest

from civ2.policy import dialog_candidates, unit_candidates, _recent_actions
from civ2.session import Session, snapshot, observed_order_outcome


def state():
    spec = dict(id=0,name='TEST Settlers',domain=0,role=5,attack=0)
    return dict(turn=1,year_raw=-4000,selected_unit_id=0,
        player=dict(id=1,treasury=50,known_technologies=[],known_technology_ids=[]),
        settings=dict(difficulty='Prince',barbarians='Restless Tribes',bloodlust=False,
                      simplified_combat=False,round_world=True,scenario=False,starting_civilizations=5,
                      restart_eliminated=True),
        units=[dict(id=0,type_id=0,owner=1,type='TEST Settlers',x=8,y=8,
                    order_id=255,movement_thirds_spent=0,specification=spec)],
        cities=[],known_cities=[],visible_units=[],diplomacy=[],
        map=dict(width=40,coordinate_width=80,height=50,tiles=[dict(x=8,y=8,
                 terrain_id=2,terrain='Grassland',river=False,known_improvements=[])]),
        evidence=dict(save_sha256='a'*64))


def dialog(control='list_item'):
    return dict(id='test_dialog',title='TEST original options',sha256='b'*64,width=640,height=480,
        options=[dict(text='TEST first option',center=[180,150],control=control),
                 dict(text='TEST second option',center=[180,175],control=control)])


def session():
    s=object.__new__(Session)
    s.state=state();s.initial_settings=copy.deepcopy(s.state['settings'])
    s.rules=dict(units=[s.state['units'][0]['specification']],terrain=[],advances=[])
    s.rules_text='TEST rules';s.game=mock.Mock();s.ui=mock.Mock();s.journal=mock.Mock()
    s.checkpoints=0;s.decisions=1;s.decision=None;s.recorder=None
    s.pending_decisions=[];s.game.click.return_value=[dict(issued=True)]
    s.ui.key.return_value=[dict(issued=True)]
    s.history=deque();s.chronicle=deque();s.publish=mock.Mock()
    return s


class SessionTests(unittest.TestCase):
    def test_live_checkpoint_never_calls_save_or_save_parser(self):
        s=session(); data=b'TEST live snapshot capsule'
        after=state();after['evidence']={'kind':'live_memory',
            'observation_sha256':hashlib.sha256(data).hexdigest()}
        s.observer=mock.Mock()
        s.observer.read.return_value={'state':after,'data':data,'receipt':{'nonce':'TEST'}}
        s._archive_observer_frames=mock.Mock(side_effect=lambda receipt:receipt)
        with mock.patch('civ2.session.parse_save') as parser:
            self.assertEqual(s.checkpoint(),after)
        s.observer.read.assert_called_once_with(rules_text=s.rules_text)
        s.ui.save_native.assert_not_called();parser.assert_not_called()
        s.game.rpc.assert_not_called()
        s.journal.artifact.assert_called_once_with('observations/d000001.json',data)
        event=s.journal.append.call_args
        self.assertEqual(event.kwargs['observation_kind'],'live_memory')
        self.assertNotIn('save_sha256',s.state['evidence'])

    def test_live_observer_failure_has_no_save_fallback(self):
        s=session();s.observer=mock.Mock()
        s.observer.read.side_effect=RuntimeError('TEST unstable original map')
        with self.assertRaisesRegex(RuntimeError,'unstable'):
            s.checkpoint()
        s.ui.save_native.assert_not_called();s.game.rpc.assert_not_called()
        s.journal.artifact.assert_not_called()

    def test_live_snapshot_rejects_hash_mismatch_and_save_alias(self):
        data=b'TEST capsule'; digest=hashlib.sha256(data).hexdigest()
        for evidence in ({'kind':'live_memory','observation_sha256':'a'*64},
                         {'kind':'live_memory','save_sha256':digest},
                         {'kind':'live_memory','observation_sha256':digest,'save_sha256':digest}):
            s=session();s.observer=mock.Mock()
            after=state();after['evidence']=evidence
            s.observer.read.return_value={'state':after,'data':data,'receipt':{}}
            with self.subTest(evidence=evidence),self.assertRaises(ValueError):
                s.checkpoint()
            s.ui.save_native.assert_not_called();s.journal.artifact.assert_not_called()

    def test_button_dispatch_does_not_confirm_again_but_list_dispatch_does(self):
        for control,confirm in [('button',False),('list_item',True),('option',True)]:
            with self.subTest(control=control):
                s=session();d=dialog(control);a=dialog_candidates(s.state,d)['option_1']
                s._evaluate=mock.Mock(return_value=a)
                current=dict(sha256=d['sha256'])
                s.ui.observe.side_effect=[current,dict(sha256='c'*64)]
                s.choose_dialog(d)
                s.game.click.assert_called_once_with(180,175)
                if confirm:s.ui.key.assert_called_once_with('Enter')
                else:s.ui.key.assert_not_called()
                s.ui.select_text.assert_not_called()
                self.assertEqual(s.history[-1]['order'],'TEST second option')

    def test_wrapped_option_uses_its_bound_center_not_single_line_text_lookup(self):
        s=session();d=dialog();d['options'][1].update(text='TEST wrapped first line and second line',source_lines=[2,3])
        a=dialog_candidates(s.state,d)['option_1'];s._evaluate=mock.Mock(return_value=a)
        s.ui.observe.side_effect=[dict(sha256=d['sha256'],lines=[dict(text='TEST wrapped first line'),dict(text='and second line')]),dict(sha256='c'*64)]
        with mock.patch('civ2.session.time.sleep'):
            s.choose_dialog(d)
        s.game.click.assert_called_once_with(180,175);s.ui.select_text.assert_not_called()

    def test_changed_dialog_image_refuses_before_any_resume_or_click(self):
        s=session();d=dialog();s._evaluate=mock.Mock(return_value=dialog_candidates(s.state,d)['option_0'])
        s.ui.observe.return_value=dict(sha256='c'*64)
        with self.assertRaisesRegex(RuntimeError,'changed during inference'):
            s.choose_dialog(d)
        s.ui.select_text.assert_not_called();s.game.rpc.assert_not_called()

    def test_noncanonical_dialog_choice_refuses_before_ui_dispatch(self):
        s=session();d=dialog();action=dialog_candidates(s.state,d)['option_0']
        action['parameters']['center']=[400,350]
        s._evaluate=mock.Mock(return_value=action)
        with self.assertRaises(ValueError):s.choose_dialog(d)
        s.ui.observe.assert_not_called();s.game.rpc.assert_not_called()

    def test_checkpoint_replaces_consumed_settler_and_compacted_slot_before_next_unit(self):
        s=session();after=state();after['evidence']['save_sha256']='c'*64
        after['cities']=[dict(id=0,name='TEST Rome',x=8,y=8,size=1)]
        after['units']=[dict(id=0,type_id=1,owner=1,type='TEST Warriors',x=10,y=8,
            order_id=255,movement_thirds_spent=0,
            specification=dict(id=1,name='TEST Warriors',domain=0,role=1,attack=1))]
        s.ui.save_native.return_value=(b'TEST SAVE BYTES',dict(mechanical_operation='native-save'))
        with mock.patch('civ2.session.parse_save',return_value=after):s.checkpoint()
        action=unit_candidates(s.state,rules=s.rules)['move_e']
        self.assertEqual(action['actor'],dict(id=0,type_id=1,owner=1,x=10,y=8))
        self.assertEqual(action['preconditions']['save_sha256'],'c'*64)
        self.assertNotIn('settle',unit_candidates(s.state,rules=s.rules))

    def test_combined_checkpoint_delta_does_not_claim_individual_acceptance(self):
        s=session();after=state();after['cities']=[dict(id=0,name='TEST Rome',x=8,y=8,size=1)]
        s.pending_decisions=[1,2];s.decision=dict(id=2,receipt='pending')
        s.history.append(dict(order='TEST choose production',outcome='awaiting original response'))
        s.ui.save_native.return_value=(b'TEST SAVE BYTES',{})
        with mock.patch('civ2.session.parse_save',return_value=after):s.checkpoint()
        events=[call for call in s.journal.append.call_args_list if call.args[0]=='batch_observed_effect']
        self.assertEqual(len(events),1);self.assertEqual(events[0].kwargs['decisions'],[1,2])
        self.assertEqual(events[0].kwargs['changed_fields'],['cities'])
        self.assertIn('not individual command acceptance',events[0].kwargs['attribution'])
        self.assertEqual(s.decision['receipt'],'pending');self.assertEqual(s.pending_decisions,[])

    def test_snapshot_does_not_invent_population_income_or_win(self):
        s=state();s['player']['researching_name']='TEST Alphabet'
        view=snapshot(s)
        self.assertEqual(view['status'],'paused')
        self.assertEqual(view['empire']['research'],'TEST Alphabet')
        self.assertNotIn('population',view['empire']);self.assertNotIn('net_income',view['empire'])
        self.assertEqual(view['decision'],{})

    def test_skip_checkpoint_reports_unchanged_position_and_spent_bookkeeping(self):
        s=session();before=copy.deepcopy(s.state)
        action=unit_candidates(before,rules=s.rules)['skip']
        s.history.append(dict(decision=1,action=action,order=action['label']))
        s.pending_decisions=[1]
        after=copy.deepcopy(before)
        after['units'][0].update(movement_thirds_spent=3,order_id=255)
        s.ui.save_native.return_value=(b'TEST SAVE BYTES',{})
        with mock.patch('civ2.session.parse_save',return_value=after):s.checkpoint()
        record=s.history[0]
        self.assertIn('position unchanged (8,8)',record['outcome'])
        self.assertIn('spent thirds 0->3',record['outcome'])
        self.assertIn('remaining movement unverified',record['outcome'])
        self.assertEqual(record['observed_delta']['movement_thirds_spent'],[0,3])
        self.assertIn('not acceptance',_recent_actions(s.history)[0]['reported_outcome'])
        self.assertNotIn('progress',record['outcome'])

    def test_move_and_worker_counter_are_observations_not_completion_claims(self):
        before=state();before['units'][0]['counter_or_commodity']=0
        action=unit_candidates(before)['move_e']
        after=copy.deepcopy(before)
        after['units'][0].update(x=10,movement_thirds_spent=3,counter_or_commodity=1)
        outcome,facts=observed_order_outcome(before,after,{'action':action},pending_count=1)
        self.assertEqual(facts['position'],[[8,8],[10,8]])
        self.assertEqual(facts['worker_counter'],[0,1])
        self.assertIn('position (8,8)->(10,8)',outcome)
        self.assertIn('worker counter 0->1',outcome)
        self.assertNotIn('completed',outcome)
        self.assertLessEqual(len(outcome),300)
        before['units'][0]['specification'].update(domain=2,role=4)
        _,facts=observed_order_outcome(before,after,{'action':action},pending_count=1)
        self.assertNotIn('worker_counter',facts)

    def test_compaction_does_not_relabel_surviving_slot_as_old_actor(self):
        before=state()
        before['units'].append({**copy.deepcopy(before['units'][0]),'id':1,'x':10})
        action=unit_candidates(before)['settle']
        after=copy.deepcopy(before)
        after['units']=[{**copy.deepcopy(before['units'][1]),'id':0}]
        after['cities']=[dict(id=0,name='TEST Rome',x=8,y=8,size=1)]
        outcome,facts=observed_order_outcome(before,after,{'action':action},pending_count=1)
        self.assertEqual(facts['owned_city_count'],[0,1])
        self.assertEqual(facts['actor_binding'],'unavailable')
        self.assertIn('possible compaction',outcome)
        self.assertNotIn('position',facts)

    def test_ambiguous_or_unexplained_transition_stays_unbound(self):
        before=state();action=unit_candidates(before)['move_e']
        for mode in ('duplicate','unexpected'):
            after=copy.deepcopy(before)
            if mode=='duplicate':after['units'].append({**copy.deepcopy(after['units'][0]),'id':1})
            else:after['units'][0]['x']=14
            with self.subTest(mode=mode):
                outcome,facts=observed_order_outcome(before,after,{'action':action},pending_count=1)
                self.assertEqual(facts['actor_binding'],'unavailable')
                self.assertIn('continuity unknown',outcome)
                self.assertNotIn('movement_thirds_spent',facts)

    def test_all_pending_records_share_batch_limits_not_just_last_order(self):
        s=session();action=unit_candidates(s.state)['skip']
        s.pending_decisions=[1,2]
        s.history.extend([dict(decision=1,action=action),dict(decision=2,order='TEST choose production')])
        after=state();after['cities']=[dict(id=0,name='TEST Rome',x=8,y=8,size=1)]
        s.ui.save_native.return_value=(b'TEST SAVE BYTES',{})
        with mock.patch('civ2.session.parse_save',return_value=after):s.checkpoint()
        for record in s.history:
            self.assertIn('cities 0->1',record['outcome'])
            self.assertIn('not individually attributed',record['outcome'])
            self.assertEqual(record['observed_delta']['actor_binding'],'unavailable')

    def test_stale_revision_and_legacy_history_do_not_guess_actor(self):
        before=state();after=copy.deepcopy(before);action=unit_candidates(before)['skip']
        action['preconditions']['save_sha256']='f'*64
        for record in ({'action':action},{'actor':action['actor'],'order':'TEST old skip'}):
            with self.subTest(record=record):
                _,facts=observed_order_outcome(before,after,record,pending_count=1)
                self.assertEqual(facts['actor_binding'],'unavailable')
                self.assertNotIn('position',facts)


if __name__ == '__main__':
    unittest.main()
