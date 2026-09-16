"""A real Jev session: stable observations, recorded choices and ordinary inputs."""
from __future__ import annotations
from collections import deque
from copy import deepcopy
import json
from pathlib import Path
import time
from .boot import original_rules, verify_setup
from .city_controls import city_control_candidates, city_control_request_for, validate_city_control
from .engine import Game
from .empire import empire_candidates, empire_request_for, validate_empire_action
from .evidence import Journal
from .policy import unit_candidates, unit_request_for, dialog_request_for, validate_action
from .planning import advance_plan, make_plan, request_for as planning_request_for, task_candidates
from .recording import Recorder
from .save import parse_save, parse_rules
from .typesafe import TypeSafeClient
from .ui import UI


def snapshot(state, *, status='paused', decision=None, recent_decisions=(), chronicle=(), message='', ledger=None):
    player = state.get('player', {})
    cities = state.get('cities', [])
    settings = state.get('settings', {})
    year = state.get('year_raw')
    year_label = (f'{abs(year)} BC' if year < 0 else f'{year} AD') if type(year) is int else None
    research = next((t.get('name') for t in player.get('known_technologies', [])
                     if t.get('id') == player.get('researching_id')), None)
    # The current research is generally not yet an owned technology.
    if research is None:
        research = player.get('researching_name')
    return {'status':status,'mode':'live','runtime_ready':True,'civilization':'Rome',
        'turn':state.get('turn'),'year':year_label,
        'empire':{'cities':len(cities),'treasury':player.get('treasury'),
                  'science':sum(c['science'] for c in cities) if cities else None,
                  'research':research},
        'settings':[{'label':'Map','value':'Small' if state.get('map',{}).get('width') == 40 else 'Observed'},
                    {'label':'Difficulty','value':settings.get('difficulty','')},
                    {'label':'Civilizations','value':str(settings.get('starting_civilizations') or '')},
                    {'label':'Barbarians','value':settings.get('barbarians','')},
                    {'label':'Rules','value':'Standard' if not settings.get('bloodlust') and not settings.get('simplified_combat') else 'Observed'},
                    {'label':'Leader','value':'Male / Rome'}],
        'decision':decision or {},'recent_decisions':list(recent_decisions),
        'chronicle':list(chronicle),'message':message,
        **({'ledger':ledger} if ledger is not None else {})}



def _primary_decision_snapshot(decision):
    """Keep only the actual primary returned vector for historical HUD telemetry."""
    if not isinstance(decision, dict) or type(decision.get('id')) is not int or decision['id'] < 1:
        return None
    question = decision.get('selected_action_question') or decision.get('selected_question')
    answers = decision.get('answers')
    answer = answers.get(question) if isinstance(answers, dict) else None
    if (not isinstance(question, str) or not isinstance(answer, dict)
            or answer.get('type') != 'choice' or not isinstance(answer.get('probabilities'), dict)
            or not 2 <= len(answer['probabilities']) <= 255):
        return None
    keys = ('id','model','latency_ms','observed_turn','observed_revision',
            'stage','executes_input','action_label','receipt')
    result = {key:deepcopy(decision[key]) for key in keys if key in decision}
    labels = decision.get('labels')
    result.update(selected_question=question, answers={question:deepcopy(answer)},
                  labels={question:deepcopy(labels.get(question, {})) if isinstance(labels, dict) else {}})
    return result


def observed_order_outcome(before, after, record, *, pending_count):
    """Bounded checkpoint facts, never command acceptance or guessed slot identity."""
    facts = {'turn': [before['turn'], after['turn']],
             'owned_city_count': [len(before['cities']), len(after['cities'])],
             'actor_binding': 'unavailable'}
    parts = [f"Checkpoint batch, not acceptance: turn {before['turn']}->{after['turn']}",
             f"cities {len(before['cities'])}->{len(after['cities'])}"]
    action = record.get('action', {})
    actor = action.get('actor', {})
    def finish(reason=None):
        if reason:
            facts['actor_binding_reason'] = reason
            parts.append(reason)
        return '; '.join(parts)[:300], facts
    if pending_count != 1:
        return finish('multiple pending commands; actor effects not individually attributed')
    fields = ('id', 'owner', 'type_id', 'x', 'y')
    if not all(type(actor.get(k)) is int for k in fields):
        return finish('no checkpoint-bound unit actor')
    if action.get('preconditions', {}).get('save_sha256') != before['evidence']['save_sha256']:
        return finish('actor revision differs; continuity unknown')
    old = {u['id']:u for u in before['units']}
    new = {u['id']:u for u in after['units']}
    unit = old.get(actor['id'])
    if unit is None or any(unit.get(k) != actor[k] for k in fields):
        return finish('actor differs from prior checkpoint; continuity unknown')
    identity = ('owner', 'type_id', 'home_city_id', 'veteran')
    if not set(old).issubset(new) or any(
            any(u.get(k) != new[identifier].get(k) for k in identity)
            for identifier, u in old.items() if identifier in new):
        return finish('roster removal/replacement or possible compaction; actor continuity unknown')
    positions = {(unit['x'], unit['y'])}
    target = action.get('parameters', {}).get('destination', {})
    if action.get('kind') == 'move' and all(type(target.get(k)) is int for k in ('x', 'y')):
        positions.add((target['x'], target['y']))
    candidates = [u for u in new.values()
                  if all(u.get(k) == unit.get(k) for k in identity)
                  and (u['x'], u['y']) in positions]
    if len(candidates) != 1 or candidates[0]['id'] != unit['id']:
        return finish('actor transition ambiguous or unexplained; continuity unknown')
    fresh = candidates[0]
    facts['actor_binding'] = 'unique_observed_signature'
    facts['position'] = [[unit['x'], unit['y']], [fresh['x'], fresh['y']]]
    if facts['position'][0] == facts['position'][1]:
        parts.append(f"position unchanged ({unit['x']},{unit['y']})")
    else:
        parts.append(f"position ({unit['x']},{unit['y']})->({fresh['x']},{fresh['y']})")
    for field, label in (('movement_thirds_spent', 'spent thirds'), ('order_id', 'order')):
        values = [unit.get(field), fresh.get(field)]
        if all(type(v) is int for v in values):
            facts[field] = values
            parts.append(f'{label} {values[0]}->{values[1]}')
    # Byte13 is a worker counter only for ground worker-role units; for other
    # units it can mean cargo/commodity/role data. Never label it completed work.
    spec = unit.get('specification', {})
    if spec.get('domain') == 0 and spec.get('role') == 5:
        counter = [unit.get('counter_or_commodity'), fresh.get('counter_or_commodity')]
        if all(type(v) is int for v in counter):
            facts['worker_counter'] = counter
            parts.append(f'worker counter {counter[0]}->{counter[1]}')
    parts.append('remaining movement unverified')
    return finish()


class Session:
    def __init__(self, directory, initial_save, *, env_file=None, max_requests=20000, fps=4,
                 record=True, game=None, planning=False):
        if type(planning) is not bool:
            raise ValueError('planning must be a boolean')
        self.planning = planning
        self.plans = {}
        self.plan_actions = []
        self.planning_decisions = 0
        self.command_decisions = 0
        self.game = game or Game()
        self.rules_text = original_rules()
        self.rules = parse_rules(self.rules_text)
        self.state = parse_save(Path(initial_save).read_bytes(), rules_text=self.rules_text)
        self.initial_checks = verify_setup(self.state)
        self.client = TypeSafeClient(env_file=env_file, max_requests=max_requests)
        self.journal = Journal(directory)
        self.ui = UI(self.game, self.journal.directory/'screens')
        self.history = deque(maxlen=20)
        self.chronicle = deque(maxlen=20)
        self.decision = None
        self.decisions = 0
        self.checkpoints = 0
        self.pending_decisions = []
        self.initial_settings = self.state['settings'].copy()
        initial = self.journal.artifact('initial.sav', Path(initial_save).read_bytes())
        self.journal.append('begin', checks=self.initial_checks, initial_save=initial,
                            settings=self.initial_settings, model=self.client.model,
                            planning_enabled=self.planning)
        self.publish('paused', 'Rome, at the beginning.')
        time.sleep(.6)  # Allow the live spectator poll to show the actual start.
        self.recorder = Recorder(self.journal.directory/'video', game=self.game, fps=fps).start() if record else None

    def publish(self, status='paused', message=''):
        state = dict(self.state)
        state['settings'] = {**state['settings'], 'starting_civilizations':self.initial_settings['starting_civilizations']}
        research_id = state['player'].get('researching_id')
        state['player'] = {**state['player'], 'researching_name': next(
            (t['name'] for t in self.rules['advances'] if t['id'] == research_id), None)}
        # Publishing the same response again only updates its dispatch label.
        # This telemetry never enters model context, commands or effect evidence.
        published = getattr(self, '_published_decisions', deque(maxlen=4))
        latest = _primary_decision_snapshot(self.decision)
        if latest is not None:
            published = deque((item for item in published if item['id'] != latest['id']), maxlen=4)
            published.append(latest)
        self._published_decisions = published
        recent = [deepcopy(item) for item in published if latest and item['id'] < latest['id']][-3:]
        self.game.state(snapshot(state, status=status, decision=self.decision, recent_decisions=recent,
                                 chronicle=self.chronicle, message=message, ledger=self.ledger()))

    def ledger(self):
        """Returned choices are counted by stage; plans never enter effect batches."""
        return {'planning_enabled':getattr(self, 'planning', False),
                'model_calls_started':self.decisions,
                'command_decisions':getattr(self, 'command_decisions', 0),
                'planning_decisions':getattr(self, 'planning_decisions', 0),
                'active_plans':sum(p['status']=='active' for p in getattr(self, 'plans', {}).values())}

    def _record_plan_status(self, plan, previous_status=None):
        self.journal.append('plan_status', planning_decision=plan.get('decision_id'),
            previous_status=previous_status, plan=deepcopy(plan), executes_input=False,
            checkpoint=self.checkpoints)

    def _advance_plans(self, state):
        # Only a single recorded unit command can explain a one-step actor
        # transition. Dialog inputs are not unit actions or identity evidence.
        actions = self.plan_actions
        for identifier, old in list(self.plans.items()):
            if old['status'] != 'active':
                continue
            if len(actions) > 1:
                new = {**deepcopy(old), 'status':'invalidated',
                       'reason':'Multiple unit commands occurred without an intervening checkpoint'}
            else:
                new = advance_plan(old, self.state, state,
                                   action=actions[0] if actions else None, rules=self.rules)
            self.plans[identifier] = new
            self._record_plan_status(new, old['status'])
        self.plan_actions.clear()

    def _unit_plan(self):
        """Choose context only; even a Hold plan authorizes no native input."""
        identifier = self.state['selected_unit_id']
        unit = next(u for u in self.state['units'] if u['id']==identifier)
        plan = self.plans.get(identifier)
        if plan and plan['status'] == 'active':
            if (plan['current_save_sha256'] == self.state['evidence']['save_sha256']
                    and all(unit.get(k)==v for k,v in plan['actor'].items())):
                return plan
            plan = {**deepcopy(plan), 'status':'invalidated',
                    'reason':'Selected actor does not match the current checkpoint-bound plan'}
            self.plans[identifier] = plan
            self._record_plan_status(plan, 'active')
        candidates, _ = task_candidates(self.state, self.rules)
        if len(candidates) < 2:
            self.journal.append('plan_status', status='unavailable', executes_input=False,
                actor=identifier, reason='Only Hold is available; no singleton model choice fabricated')
            return None
        request, candidates = planning_request_for(self.state, self.rules,
                                                   recent_actions=list(self.history))
        task = self._evaluate(request, candidates, 'task_choice', stage='planning')
        plan = make_plan(task, self.state, self.rules)
        plan['decision_id'] = self.decisions
        self.plans[identifier] = plan
        self._record_plan_status(plan)
        return plan

    def checkpoint(self):
        self.checkpoints += 1
        name = f'd{self.checkpoints:06d}.sav'
        data, receipt = self.ui.save_native(name)
        self.game.rpc('pause')
        state = parse_save(data, rules_text=self.rules_text)
        for key in ('difficulty','barbarians','bloodlust','simplified_combat','round_world','scenario','restart_eliminated'):
            if state['settings'][key] != self.initial_settings[key]:
                raise RuntimeError('Campaign settings changed unexpectedly')
        if (state['map']['width'],state['map']['height']) != (40,50):
            raise RuntimeError('Campaign map changed unexpectedly')
        artifact = self.journal.artifact('saves/'+name, data)
        self.journal.append('checkpoint', artifact=artifact, receipt=receipt,
                            turn=state['turn'],year=state['year_raw'])
        if self.pending_decisions:
            fields = ('turn','selected_unit_id','units','cities','player','diplomacy')
            changed = [key for key in fields if self.state[key] != state[key]]
            self.journal.append('batch_observed_effect', decisions=list(self.pending_decisions),
                changed_fields=changed, attribution='Changes since the previous native checkpoint; not individual command acceptance')
            records = [r for r in self.history if r.get('decision') in self.pending_decisions]
            # Older live sessions retain flat history without decision IDs.
            # Preserve them, but never infer a unit identity from that alone.
            if not records and self.history:
                records = [self.history[-1]]
            for record in records:
                record['outcome'], record['observed_delta'] = observed_order_outcome(
                    self.state, state, record, pending_count=len(self.pending_decisions))
            self.pending_decisions.clear()
        if getattr(self, 'planning', False):
            self._advance_plans(state)
        self.state = state
        return state

    def _evaluate(self, request, actions, question, *, stage='command'):
        if stage not in ('command', 'planning'):
            raise ValueError('Unknown model decision stage')
        if self.recorder:
            self.recorder.check()
        self.game.rpc('pause')
        self.decisions += 1
        decision_id = self.decisions
        input_artifact = self.journal.artifact(f'decisions/{decision_id:06d}-request.json', request)
        self.journal.append('inference_started', decision=decision_id, request=input_artifact, stage=stage)
        result = self.client.evaluate(request['state'], request['questions'])
        output_artifact = self.journal.artifact(f'decisions/{decision_id:06d}-response.json', result)
        choice = result['answers'][question]['choice']
        action = actions[choice]
        if stage == 'planning':
            self.planning_decisions = getattr(self, 'planning_decisions', 0)+1
            self.journal.append('model_plan', decision=decision_id, response=output_artifact,
                selected_question=question, task=action, executes_input=False)
        else:
            self.command_decisions = getattr(self, 'command_decisions', 0)+1
            self.journal.append('model_decision', decision=decision_id, response=output_artifact,
                                selected_question=question, action=action)
            self.pending_decisions.append(decision_id)
        self.decision = {'id':decision_id,'model':result['model'],
            'latency_ms':result['metadata']['latency_ms'],'observed_turn':self.state['turn'],
            'observed_revision':self.state['evidence']['save_sha256'],
            'input_tokens':self.client.input_tokens_total,'answers':result['answers'],
            'labels':{name:{key:key if name=='empire_strategy' else str(label) for key,label in q['criteria'].items()}
                      for name,q in request['questions'].items()},
            'selected_question':question,'stage':stage,'authorizes_input':stage=='command',
            'action_label':('Plan only · ' if stage=='planning' else '')+action['label'],
            'receipt':None if stage=='planning' else 'pending'}
        if stage == 'planning':
            self.decision['executes_input'] = False
        self.publish('paused')
        # Preserve a readable view of the actual decision in the full recording.
        time.sleep(.6)
        return action

    def _mark_dispatched(self, decision_id, question, action, inputs):
        """A matching input receipt establishes dispatch, never game acceptance."""
        decision = getattr(self, 'decision', None)
        if (not isinstance(decision, dict) or decision.get('id') != decision_id
                or decision.get('stage', 'command') != 'command'
                or decision.get('authorizes_input') is False
                or decision.get('selected_question') != question
                or decision.get('answers', {}).get(question, {}).get('choice') != action['id']
                or not isinstance(inputs, list) or not inputs
                or any(not isinstance(item, dict) or item.get('issued') is False for item in inputs)):
            return
        self.decision = {**decision, 'receipt':'dispatched'}

    def choose_unit(self):
        actions = unit_candidates(self.state, rules=self.rules)
        plan = self._unit_plan() if getattr(self, 'planning', False) else None
        request = unit_request_for(self.state, actions, self.rules, recent_actions=list(self.history))
        if plan:
            request['state']['persistent_plan'] = {
                'planning_decision':plan['decision_id'], 'task':plan['candidate']['task'],
                'target':deepcopy(plan['candidate']['target']), 'label':plan['candidate']['label'],
                'actor':deepcopy(plan['actor']), 'status':plan['status'],
                'created_turn':plan['created_turn'], 'expires_turn':plan['expires_turn'],
                'note':'A prior independent Jev task choice; context only. This call alone chooses the next native command.'}
            request['questions']['unit_action']['instructions'] += (
                ' Consider the persistent Jev-selected task and observed target when choosing this next step.'
                ' No path is supplied or executed automatically. You may detour, wait or choose another legal'
                ' action when current circumstances warrant; the task is reviewed after completion, invalidation or expiry.')
        action = self._evaluate(request, actions, 'unit_action')
        decision_id = self.decisions
        validate_action(action, self.state, self.rules)
        self.game.rpc('resume')
        before = self.ui.observe()
        inputs = self.ui.key(action['parameters']['key'], settle=.4)
        after = self.ui.observe()
        self.journal.append('command_dispatched', decision=self.decisions, action=action,
                            before=before['sha256'],after=after['sha256'],inputs=inputs)
        self._mark_dispatched(decision_id, 'unit_action', action, inputs)
        if getattr(self, 'planning', False):
            self.plan_actions.append(deepcopy(action))
        self.history.append({'turn':self.state['turn'],'actor':action['actor'],
                             'decision':decision_id,'action':deepcopy(action),
                             'order':action['label'],'outcome':'awaiting next game observation'})
        self.chronicle.append({'id':str(self.decisions),'turn':self.state['turn'],
                               'label':action['label'],'kind':action['kind']})
        self.publish('running')
        return action, after

    def choose_dialog(self, dialog):
        request, actions = dialog_request_for(self.state, dialog, self.rules,
                                             recent_actions=list(self.history))
        request['state']['checkpoint_freshness'] = {
            'pending_decisions_since_native_save':list(self.pending_decisions),
            'note':'Empire and unit data are from the last native save. The mandatory dialog is current; pending orders may have changed the empire.'}
        if getattr(self,'city_report',None):
            request['state']['latest_observed_city_report'] = self.city_report
        if dialog.get('kind') == 'buy_quote':
            quote = dialog.get('quote')
            if (dialog.get('resource_tag') != 'COMPLETE1' or not isinstance(quote, dict)
                    or quote.get('purchase_executed') is not False
                    or any(type(quote.get(k)) is not int or quote[k] < 0 for k in ('cost','treasury'))):
                raise RuntimeError('A purchase choice requires its actual original quote and treasury')
            request['state']['mandatory_dialog']['quote'] = deepcopy(quote)
        if len(actions) < 2:
            raise RuntimeError('A single forced dialog option needs an explicit mechanical handler')
        action = self._evaluate(request, actions, 'dialog_action')
        decision_id = self.decisions
        validate_action(action, self.state, self.rules, dialog=dialog)
        current = self.ui.observe()
        if current['sha256'] != dialog['sha256']:
            raise RuntimeError('Original dialog changed during inference')
        self.game.rpc('resume')
        option = dialog['options'][action['parameters']['option_index']]
        # The classifier may join a wrapped option across several OCR lines.
        # Its center is already bound to this exact image; don't re-find a
        # joined label as if it were one native OCR line.
        inputs = self.game.click(*action['parameters']['center'])
        time.sleep(.25)
        if option.get('control') != 'button':
            inputs += self.ui.key('Enter')
        receipt = {'target':action['parameters']['observed_text'],
                   'point':action['parameters']['center'],'before':current['sha256'],'inputs':inputs}
        after = self.ui.observe()
        self.journal.append('dialog_dispatched',decision=self.decisions,action=action,receipt=receipt,
                            after=after['sha256'])
        self._mark_dispatched(decision_id, 'dialog_action', action, inputs)
        self.history.append({'turn':self.state['turn'],'decision':decision_id,'action':deepcopy(action),
                             'order':action['label'],'outcome':'awaiting original game response'})
        self.chronicle.append({'id':str(self.decisions),'turn':self.state['turn'],'label':action['label'],'kind':'dialog'})
        self.publish('running')
        return action, after

    def choose_empire(self, screen, reviewed):
        actions = empire_candidates(self.state,screen,reviewed,self.rules)
        decision_id = None
        if len(actions) == 1:
            action = next(iter(actions.values()))
            self.journal.append('forced_empire_command',action=action,
                reason='All optional menu reviews were completed; only Finish Turn remains. No model distribution created.')
        else:
            request = empire_request_for(self.state,screen,actions,reviewed,self.rules,
                                           recent_actions=list(self.history))
            action = self._evaluate(request,actions,'empire_action')
            decision_id = self.decisions
        validate_empire_action(action,self.state,screen,reviewed,self.rules)
        current = self.ui.observe()
        if current['sha256'] != screen['sha256']:
            raise RuntimeError('End-turn screen changed before the empire command')
        self.game.rpc('resume')
        parameters = action['parameters']
        if parameters['modifiers']:
            inputs = self.game.chord(*parameters['modifiers'],parameters['key'],hold_ms=120)
            time.sleep(.3)
        else:
            inputs = self.ui.key(parameters['key'],settle=.4)
        after = self.ui.observe()
        self.journal.append('empire_command_dispatched',action=action,inputs=inputs,
                             before=current['sha256'],after=after['sha256'])
        if decision_id is not None:
            self._mark_dispatched(decision_id, 'empire_action', action, inputs)
        self.history.append({'turn':self.state['turn'],'actor':action['actor'],
            'decision':decision_id,'action':deepcopy(action),
            'order':action['label'],'outcome':'Awaiting the original game response'})
        self.chronicle.append({'id':str(self.decisions),'turn':self.state['turn'],
                               'label':action['label'],'kind':action['kind']})
        self.publish('running')
        return action, after

    def choose_city_control(self, screen, reviewed, *, labor_ready=False):
        actions = city_control_candidates(self.state, screen, reviewed, self.rules, labor_ready=labor_ready)
        decision_id = None
        if len(actions) == 1:
            action = actions['exit_city']
            self.journal.append('forced_city_control', action=action, reviewed=deepcopy(reviewed),
                reason='Only observed Exit remains after city review. No model distribution created.')
        else:
            request = city_control_request_for(self.state, screen, actions, reviewed, self.rules,
                                               recent_actions=list(self.history), labor_ready=labor_ready)
            request['state']['checkpoint_freshness'] = {
                'pending_decisions_since_native_save':list(self.pending_decisions),
                'note':'Saved city statistics may precede pending orders; this city window and its control labels are current.'}
            if getattr(self, 'city_report', None):
                request['state']['latest_observed_city_report'] = deepcopy(self.city_report)
            action = self._evaluate(request, actions, 'city_action')
            decision_id = self.decisions
        validate_city_control(action, self.state, screen, reviewed, self.rules, labor_ready=labor_ready)
        current = self.ui.observe()
        if current['sha256'] != screen['sha256']:
            raise RuntimeError('Native city screen changed before the chosen control')
        self.game.rpc('resume')
        inputs = self.game.click(*action['parameters']['center'])
        time.sleep(.4)
        after = self.ui.observe()
        self.journal.append('city_control_dispatched', decision=decision_id, action=action,
            reviewed=deepcopy(reviewed), before=current['sha256'], after=after['sha256'], inputs=inputs)
        if decision_id is not None:
            self._mark_dispatched(decision_id, 'city_action', action, inputs)
        self.history.append({'turn':self.state['turn'],'actor':action['actor'],
            'decision':decision_id,'action':deepcopy(action),'order':action['label'],
            'outcome':('Labor click dispatched; awaiting a native save comparison' if action['kind']=='city_labor'
                       else 'Native city control dispatched; awaiting its observed follow-up, no purchase inferred')})
        self.chronicle.append({'id':str(decision_id) if decision_id is not None else f'city-exit-{self.checkpoints}',
            'turn':self.state['turn'],'label':action['label'],'kind':'city_control'})
        self.publish('running')
        return action, after

    def mechanical(self, label, code='Enter'):
        self.game.rpc('resume')
        before = self.ui.observe()
        inputs = self.ui.key(code, settle=.4)
        after = self.ui.observe()
        self.journal.append('mechanical_input', label=label, before=before['sha256'],
                            after=after['sha256'],inputs=inputs)
        return after

    def note_native_rejection(self, dialog):
        """Retain a proven rule notice and retire its pending task context.

        A rejected command remains in the decision/effect ledger. It cannot
        serve as a movement explanation for persistent actor continuity.
        """
        rejection = dialog.get('native_rejection')
        if dialog.get('kind') != 'rule_rejection' or not isinstance(rejection, dict):
            raise ValueError('A classified original rule rejection is required')
        actions = getattr(self, 'plan_actions', [])
        action = actions[0] if len(actions) == 1 else None
        self.journal.append('native_rule_rejection', screen=dialog['sha256'],
            rejection=deepcopy(rejection), pending_decisions=list(self.pending_decisions),
            pending_unit_action=deepcopy(action))
        if action is not None:
            plan = self.plans.get(action['actor']['id'])
            if plan and plan['status'] == 'active':
                updated = {**deepcopy(plan), 'status':'invalidated',
                    'reason':'The original game rejected the pending unit order: '+rejection.get('body', 'native rule notice')}
                self.plans[action['actor']['id']] = updated
                self._record_plan_status(updated, 'active')
            self.plan_actions.clear()

    def finish(self, *, status='paused', reason='Session paused for inspection.'):
        self.game.rpc('pause')
        self.publish(status, reason)
        self.journal.append('session_stopped',status=status,reason=reason,
            decisions=self.decisions,api_requests=self.client.request_count,
            input_tokens=self.client.input_tokens_total,output_tokens=self.client.output_tokens_total,
            ledger=self.ledger())
        if self.recorder:
            recording = self.recorder.stop()
            recording['path'] = 'video/'+recording['path']
            self.journal.append('recording_finalized', **recording)
        self.journal.close()
