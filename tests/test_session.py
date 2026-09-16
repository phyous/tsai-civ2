"""Offline runner-contract tests. All observations and inputs are synthetic TEST data."""
from collections import deque
import copy
from unittest import mock
import unittest

from civ2.policy import dialog_candidates, unit_candidates
from civ2.session import Session, snapshot


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


if __name__ == '__main__':
    unittest.main()
