"""Native labor close/save/reopen transaction tests with synthetic TEST screens."""
from collections import deque
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock
from civ2.city_controls import city_control_candidates
from civ2.run import controller_context,run_steps,start_labor_refresh,labor_refresh_step
from test_city_labor_controls import inputs


def frame(number,kind='city_screen'):
    _,screen,_=inputs();screen.update(sha256=f'{number:064x}',mechanical_action=None,
        requires_model=False,resource_tag=None)
    if kind!='city_screen':screen.update(kind=kind,title=kind,options=[],buttons=[])
    if kind=='city_locator':screen.update(options=[dict(text='TEST Rome',center=[200,200])],
        buttons=[dict(text='Zoom To City',center=[300,350])])
    return dict(sha256=screen['sha256'],path=f'/tmp/TEST-labor/screens/{number}.png',
                text=screen['title'],classified=screen)


def session(observations,after='expected'):
    state,_,rules=inputs()
    s=SimpleNamespace(state=state,rules=rules,decisions=0,checkpoints=0,recorder=None,
        game=mock.Mock(),ui=mock.Mock(),journal=mock.Mock(),publish=mock.Mock(),history=deque())
    s.journal.directory=Path('/tmp/TEST-labor');s.ui.observe.side_effect=observations
    s.ui.key.return_value=[{'issued':True}];s.game.chord.return_value=[{'issued':True}]
    s.ui.select_text.return_value={'inputs':[{'issued':True}]}
    def checkpoint():
        s.checkpoints+=1;s.state=deepcopy(s.state)
        s.state['evidence']['save_sha256']=str(s.checkpoints+2)*64
        if s.checkpoints==2 and after!='unchanged':
            s.state['cities'][0].update(worked_tiles_bits=[0 if after=='expected' else 64,0,16],
                specialist_count=1,specialists={'entertainer':1})
        return s.state
    s.checkpoint=mock.Mock(side_effect=checkpoint)
    def choose(screen,reviewed,*,labor_ready=False):
        assert labor_ready
        actions=city_control_candidates(s.state,screen,reviewed,rules,labor_ready=labor_ready)
        s.decisions+=1;action=actions['labor_remove_worker_2']
        s.history.append({'decision':s.decisions,'action':deepcopy(action)})
        return action,frame(90)
    s.choose_city_control=mock.Mock(side_effect=choose)
    ctx=controller_context(s);ctx['graphics_configured']=True
    ctx['pending_empire']={'id':'inspect_city_0'};ctx['pending_city']={'name':'TEST Rome'}
    return s


def sequence():
    return [frame(1),frame(2),frame(3,'end_turn'),frame(4,'end_turn'),
            frame(5,'city_locator'),frame(6,'city_locator'),frame(7),
            frame(8),frame(9,'end_turn'),frame(10,'end_turn'),
            frame(11,'city_locator'),frame(12,'city_locator'),frame(13)]


def run(s):
    with mock.patch('civ2.run.game_text',return_value='TEST'), \
         mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kw:o['classified']), \
         mock.patch('civ2.run.time.sleep'):
        return run_steps(s,max_decisions=1)


def events(s,kind):return [c.kwargs for c in s.journal.append.call_args_list if c.args[0]==kind]


class LaborRunTests(unittest.TestCase):
    def test_prepare_and_verify_complete_before_decision_limit_with_outer_context_intact(self):
        s=session(sequence());result=run(s);ctx=controller_context(s)
        self.assertIn('decision checkpoint',result['reason'])
        self.assertEqual(s.choose_city_control.call_count,1);self.assertEqual(s.checkpoints,2)
        self.assertEqual(s.ui.key.call_args_list,[mock.call('Escape'),mock.call('Escape')])
        self.assertEqual(s.game.chord.call_args_list,[mock.call('ShiftLeft','KeyC',hold_ms=120)]*2)
        self.assertEqual(s.ui.select_text.call_count,4)
        self.assertIsNone(ctx['pending_labor_refresh']);self.assertIsNone(ctx['pending_city_control'])
        self.assertEqual(ctx['pending_empire'],{'id':'inspect_city_0'})
        self.assertTrue(ctx['pending_empire_confirmed'])
        self.assertEqual(next(iter(ctx['city_controls_reviewed'].values()))['labor_reassignments'],1)
        checkpoints=events(s,'city_labor_checkpoint')
        self.assertIsNone(checkpoints[0]['result'])
        self.assertEqual(checkpoints[1]['result']['status'],'observed_expected_change')
        self.assertEqual([e['purpose'] for e in events(s,'city_labor_ready')],['prepare_labor_choices','verify_labor'])
        self.assertIn('observed_expected_change',s.history[-1]['outcome'])

    def test_no_effect_is_explicit_counts_against_budget_and_reopens_for_model(self):
        s=session(sequence(),'unchanged');run(s)
        self.assertEqual(events(s,'city_labor_checkpoint')[-1]['result']['status'],'no_observed_change')
        self.assertEqual(next(iter(controller_context(s)['city_controls_reviewed'].values()))['labor_reassignments'],1)
        self.assertEqual(len(events(s,'city_labor_ready')),2)
        self.assertNotIn('accepted',str(events(s,'city_labor_checkpoint')))

    def test_wrong_native_bit_pauses_after_save_without_reopening_or_new_choice(self):
        s=session(sequence(),'wrong');result=run(s)
        self.assertIn('differed',result['reason'])
        self.assertEqual(events(s,'city_labor_checkpoint')[-1]['result']['status'],'unexpected_change')
        self.assertEqual(controller_context(s)['pending_labor_refresh']['phase'],'failed')
        self.assertIsNone(controller_context(s)['city_labor_ready'])
        self.assertEqual(s.choose_city_control.call_count,1);self.assertEqual(s.game.chord.call_count,1)

    def test_wrong_city_after_refresh_cannot_authorize_labor(self):
        observations=sequence();observations[6]['classified']['title']='City of TEST Veii, 3700 B.C.'
        s=session(observations);result=run(s)
        self.assertIn('different city',result['reason']);s.choose_city_control.assert_not_called()
        self.assertEqual(events(s,'city_labor_ready'),[])

    def test_failed_locator_cannot_fall_through_to_unit_or_empire_decision(self):
        observations=sequence();observations[4]=frame(5,'normal_map')
        s=session(observations);result=run(s)
        self.assertIn('no observed transition',result['reason']);s.choose_city_control.assert_not_called()
        self.assertEqual(s.checkpoint.call_count,1)

    def test_refresh_state_cannot_be_overwritten_or_reopen_after_turn_change(self):
        s=session([]);ctx=controller_context(s);actor=s.state['cities'][0]
        start_labor_refresh(s,ctx,actor)
        with self.assertRaises(ValueError):start_labor_refresh(s,ctx,actor)
        ctx['pending_labor_refresh']['phase']='await_map'
        def changed():s.state['turn']+=1;s.checkpoints+=1
        s.checkpoint.side_effect=changed;o=frame(1,'end_turn')
        handled,error=labor_refresh_step(s,ctx,o,o['classified'],'TEST')
        self.assertTrue(handled);self.assertIn('advanced',error);s.game.chord.assert_not_called()


if __name__=='__main__':unittest.main()
