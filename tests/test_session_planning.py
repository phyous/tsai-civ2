"""Offline planning integration; all saves, Jev replies and inputs are TEST data."""
from collections import deque
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
import unittest

from civ2.policy import unit_candidates
from civ2.session import Session


def observation():
    spec = dict(id=0, name='TEST Settlers', domain=0, role=5, attack=0)
    return dict(turn=1, year_raw=-4000, selected_unit_id=0,
        player=dict(id=1, treasury=50, known_technologies=[], known_technology_ids=[]),
        settings=dict(difficulty='Prince', barbarians='Restless Tribes', bloodlust=False,
            simplified_combat=False, round_world=True, scenario=False,
            starting_civilizations=5, restart_eliminated=True),
        units=[dict(id=0, owner=1, type_id=0, type='TEST Settlers', x=8, y=8,
                    order_id=255, movement_thirds_spent=0, specification=spec)],
        cities=[], known_cities=[], visible_units=[], diplomacy=[],
        map=dict(width=40, coordinate_width=80, height=50,
            tiles=[dict(x=x, y=8, terrain_id=2, terrain='Grassland',
                        river=False, known_improvements=[]) for x in (6, 8, 10)]),
        evidence=dict(save_sha256='a'*64))


class TestClient:
    """In-memory exact Choice fixture; never connects to a model service."""
    __test__ = False
    model = 'TEST model'
    request_count = 0
    input_tokens_total = 0
    output_tokens_total = 0

    def __init__(self, task='settle_10_8'):
        self.task = task
        self.requests = []

    def evaluate(self, state, questions):
        self.requests.append(deepcopy(dict(state=state, questions=questions)))
        self.request_count += 1
        self.input_tokens_total += 100
        answers = {}
        for name, question in questions.items():
            choice = {'task_choice':self.task, 'unit_action':'move_e'}.get(name)
            choice = choice or next(iter(question['criteria']))
            answers[name] = dict(choice=choice, confidence=1.0,
                probabilities={key:float(key==choice) for key in question['criteria']})
        return dict(model=self.model, answers=answers, metadata=dict(latency_ms=1), usage={})


def session(planning=True, task='settle_10_8'):
    s = object.__new__(Session)
    s.planning=planning; s.plans={}; s.plan_actions=[]
    s.planning_decisions=0; s.command_decisions=0
    s.state=observation(); s.initial_settings=deepcopy(s.state['settings'])
    s.rules=dict(units=[s.state['units'][0]['specification']], terrain=[], advances=[])
    s.rules_text='TEST rules'; s.game=mock.Mock(); s.ui=mock.Mock(); s.journal=mock.Mock()
    s.client=TestClient(task); s.decisions=0; s.checkpoints=0; s.decision=None
    s.recorder=None; s.pending_decisions=[]; s.history=deque(); s.chronicle=deque()
    s.publish=mock.Mock(); s.artifacts={}
    def artifact(name, value):
        s.artifacts[name]=deepcopy(value)
        return dict(path=name, sha256='f'*64)
    s.journal.artifact.side_effect=artifact
    s.ui.observe.return_value=dict(sha256='d'*64)
    s.ui.key.return_value=[dict(issued=True)]
    s.ui.save_native.return_value=(b'TEST SAVE', dict(operation='TEST native save'))
    return s


def events(s, kind):
    return [call.kwargs for call in s.journal.append.call_args_list if call.args[0]==kind]


@mock.patch('civ2.session.time.sleep')
class SessionPlanningTests(unittest.TestCase):
    def test_native_rejection_keeps_attempt_and_effect_evidence_but_retires_plan(self, sleep):
        s=session();s.choose_unit()
        pending=list(s.pending_decisions);input_count=s.ui.key.call_count
        notice=dict(kind='rule_rejection',sha256='e'*64,
            native_rejection={'body':'TEST original rule rejection','template':'TEST'})
        s.note_native_rejection(notice)
        self.assertEqual(s.plans[0]['status'],'invalidated')
        self.assertEqual(s.plan_actions,[])
        self.assertEqual(s.pending_decisions,pending)
        self.assertEqual(s.ui.key.call_count,input_count)
        proof=events(s,'native_rule_rejection')[0]
        self.assertEqual(proof['screen'],'e'*64)
        self.assertEqual(proof['pending_unit_action']['kind'],'move')
        with mock.patch('civ2.planning.validate_action',side_effect=AssertionError('Historical action must not be revalidated')):
            s._advance_plans(deepcopy(s.state))

    def test_planning_is_opt_in_and_supplied_runtime_reaches_recorder(self, sleep):
        with TemporaryDirectory() as directory:
            source=Path(directory)/'TEST.sav'; source.write_bytes(b'TEST')
            game=mock.Mock(); state=observation()
            journal=mock.Mock(directory=Path(directory))
            rules=dict(units=[], terrain=[], advances=[])
            with mock.patch('civ2.session.original_rules',return_value='TEST'), \
                 mock.patch('civ2.session.parse_rules',return_value=rules), \
                 mock.patch('civ2.session.parse_save',return_value=state), \
                 mock.patch('civ2.session.verify_setup',return_value={}), \
                 mock.patch('civ2.session.TypeSafeClient',return_value=TestClient()), \
                 mock.patch('civ2.session.Journal',return_value=journal), \
                 mock.patch('civ2.session.UI'), mock.patch('civ2.session.Recorder') as recorder:
                result=Session(directory,source,game=game)
            self.assertFalse(result.planning)
            recorder.assert_called_once_with(Path(directory)/'video',game=game,fps=4)
        with self.assertRaises(ValueError): Session('unused','unused',planning='false')

    def test_disabled_mode_keeps_single_original_action_request(self, sleep):
        s=session(False)
        with mock.patch.object(s, '_unit_plan') as planner:
            s.choose_unit()
        planner.assert_not_called()
        self.assertEqual(len(s.client.requests),1)
        self.assertNotIn('persistent_plan',s.client.requests[0]['state'])
        self.assertEqual(s.pending_decisions,[1])
        self.assertEqual(events(s,'model_plan'),[])
        self.assertEqual(s.plan_actions,[])

    def test_plan_only_choice_never_dispatches_or_enters_effect_batch(self, sleep):
        s=session(); plan=s._unit_plan()
        self.assertEqual(plan['status'],'active')
        self.assertEqual(plan['decision_id'],1)
        s.ui.key.assert_not_called(); s.game.click.assert_not_called()
        self.assertEqual(s.pending_decisions,[])
        self.assertEqual(events(s,'model_decision'),[])
        self.assertEqual(events(s,'command_dispatched'),[])
        event=events(s,'model_plan')[0]
        self.assertNotIn('action',event)
        self.assertFalse(event['executes_input'])
        self.assertEqual(s.decision['stage'],'planning')
        self.assertFalse(s.decision['authorizes_input'])
        self.assertIsNone(s.decision['receipt'])
        self.assertTrue(s.decision['action_label'].startswith('Plan only'))
        self.assertEqual(s.ledger()['planning_decisions'],1)
        self.assertEqual(s.ledger()['command_decisions'],0)
        self.assertEqual(s.decision['answers'],s.artifacts['decisions/000001-response.json']['answers'])

    def test_independent_action_choice_receives_plan_and_only_it_authorizes_input(self, sleep):
        # A Hold task does not force Skip: the second, genuine model choice is Move.
        s=session(task='hold_one_turn'); action,_=s.choose_unit()
        self.assertEqual(action['kind'],'move')
        self.assertEqual(len(s.client.requests),2)
        context=s.client.requests[1]['state']['persistent_plan']
        self.assertEqual(context['task'],'hold')
        self.assertEqual(context['planning_decision'],1)
        self.assertEqual(s.pending_decisions,[2])
        self.assertEqual([e['decision'] for e in events(s,'model_plan')],[1])
        self.assertEqual([e['decision'] for e in events(s,'model_decision')],[2])
        self.assertEqual([e['decision'] for e in events(s,'command_dispatched')],[2])
        s.ui.key.assert_called_once_with(action['parameters']['key'],settle=.4)
        self.assertEqual(s.plan_actions,[action])
        self.assertEqual(s.ledger()['command_decisions'],1)
        self.assertEqual(s.ledger()['planning_decisions'],1)
        self.assertEqual(s.ledger()['model_calls_started'],2)
        self.assertEqual(set(s.artifacts),{f'decisions/{i:06d}-{part}.json'
            for i in (1,2) for part in ('request','response')})

    def test_single_held_task_never_fabricates_a_planning_distribution(self, sleep):
        s=session()
        with mock.patch('civ2.session.task_candidates',return_value=({'hold_one_turn':{}},{})):
            s.choose_unit()
        self.assertEqual(len(s.client.requests),1)
        self.assertNotIn('persistent_plan',s.client.requests[0]['state'])
        self.assertEqual(events(s,'model_plan'),[])
        self.assertEqual(events(s,'plan_status')[0]['status'],'unavailable')

    def test_unique_recorded_movement_retains_plan_without_another_planning_call(self, sleep):
        s=session(); s.choose_unit()
        after=deepcopy(s.state); after['evidence']['save_sha256']='b'*64
        after['units'][0]['x']=10
        with mock.patch('civ2.session.parse_save',return_value=after): s.checkpoint()
        self.assertEqual(s.plans[0]['status'],'active')
        self.assertEqual(s.plans[0]['actor']['x'],10)
        self.assertEqual(s.plan_actions,[])
        self.assertEqual(events(s,'batch_observed_effect')[0]['decisions'],[2])
        s.choose_unit()
        self.assertEqual(len(events(s,'model_plan')),1)
        self.assertEqual(len(events(s,'model_decision')),2)
        self.assertEqual(s.client.requests[2]['state']['persistent_plan']['actor']['x'],10)
        self.assertEqual(s.client.requests[2]['state']['persistent_plan']['target_geometry']['current_geometric_steps_to_target'],0)
        self.assertEqual(s.pending_decisions,[3])

    def test_unexplained_actor_movement_invalidates_instead_of_guessing_identity(self, sleep):
        s=session(); s._unit_plan()
        after=deepcopy(s.state); after['evidence']['save_sha256']='b'*64
        after['units'][0]['x']=10
        with mock.patch('civ2.session.parse_save',return_value=after): s.checkpoint()
        self.assertEqual(s.plans[0]['status'],'invalidated')
        self.assertIn('not unique',s.plans[0]['reason'])
        self.assertEqual(events(s,'batch_observed_effect'),[])

    def test_consumed_settler_goal_completes_only_as_observation_not_acceptance(self, sleep):
        s=session(); s._unit_plan()
        after=deepcopy(s.state); after['evidence']['save_sha256']='b'*64
        after['cities']=[dict(id=0,name='TEST City',x=10,y=8,size=1)]
        after['units']=[]; after['selected_unit_id']=None
        with mock.patch('civ2.session.parse_save',return_value=after): s.checkpoint()
        self.assertEqual(s.plans[0]['status'],'complete')
        self.assertIn('causal attribution is not inferred',s.plans[0]['reason'])
        self.assertEqual(events(s,'batch_observed_effect'),[])
        self.assertFalse(events(s,'plan_status')[-1]['executes_input'])

    def test_compacted_roster_invalidates_surviving_numeric_slot(self, sleep):
        s=session(); other=deepcopy(s.state['units'][0]); other.update(id=1,x=12)
        s.state['units'].append(other); s._unit_plan()
        after=deepcopy(s.state); after['evidence']['save_sha256']='b'*64
        after['units']=[{**deepcopy(other),'id':0}]
        with mock.patch('civ2.session.parse_save',return_value=after): s.checkpoint()
        self.assertEqual(s.plans[0]['status'],'invalidated')
        self.assertIn('compaction',s.plans[0]['reason'])

    def test_multiple_uncheckpointed_unit_actions_refuse_transition_attribution(self, sleep):
        s=session(); s._unit_plan()
        action=unit_candidates(s.state,rules=s.rules)['move_e']
        s.plan_actions=[action,deepcopy(action)]
        after=deepcopy(s.state); after['evidence']['save_sha256']='b'*64
        with mock.patch('civ2.session.parse_save',return_value=after): s.checkpoint()
        self.assertEqual(s.plans[0]['status'],'invalidated')
        self.assertIn('Multiple unit commands',s.plans[0]['reason'])
        self.assertEqual(s.plan_actions,[])

    def test_failed_planning_inference_never_reaches_action_call_or_inputs(self, sleep):
        s=session(); s.client.evaluate=mock.Mock(side_effect=RuntimeError('TEST failure'))
        with self.assertRaisesRegex(RuntimeError,'TEST failure'): s.choose_unit()
        s.ui.key.assert_not_called(); self.assertEqual(s.pending_decisions,[])
        self.assertEqual(s.plans,{})
        self.assertEqual(s.ledger()['planning_decisions'],0)
        self.assertEqual(s.ledger()['command_decisions'],0)
        self.assertEqual(s.ledger()['model_calls_started'],1)


if __name__ == '__main__': unittest.main()
