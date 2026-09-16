"""A real Jev session: stable observations, recorded choices and ordinary inputs."""
from __future__ import annotations
from collections import deque
import json
from pathlib import Path
import time
from .boot import original_rules, verify_setup
from .engine import Game
from .empire import empire_candidates, empire_request_for, validate_empire_action
from .evidence import Journal
from .policy import unit_candidates, unit_request_for, dialog_request_for, validate_action
from .recording import Recorder
from .save import parse_save, parse_rules
from .typesafe import TypeSafeClient
from .ui import UI


def snapshot(state, *, status='paused', decision=None, chronicle=(), message=''):
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
        'decision':decision or {},'chronicle':list(chronicle),'message':message}


class Session:
    def __init__(self, directory, initial_save, *, env_file=None, max_requests=20000, fps=4,
                 record=True, game=None):
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
                            settings=self.initial_settings, model=self.client.model)
        self.publish('paused', 'Rome, at the beginning.')
        time.sleep(.6)  # Allow the live spectator poll to show the actual start.
        self.recorder = Recorder(self.journal.directory/'video', fps=fps).start() if record else None

    def publish(self, status='paused', message=''):
        state = dict(self.state)
        state['settings'] = {**state['settings'], 'starting_civilizations':self.initial_settings['starting_civilizations']}
        research_id = state['player'].get('researching_id')
        state['player'] = {**state['player'], 'researching_name': next(
            (t['name'] for t in self.rules['advances'] if t['id'] == research_id), None)}
        self.game.state(snapshot(state, status=status, decision=self.decision,
                                 chronicle=self.chronicle, message=message))

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
            if self.history:
                self.history[-1]['outcome'] = ('Observed after pending orders: '+', '.join(changed)
                                               if changed else 'No observed state change after pending orders')
            self.pending_decisions.clear()
        self.state = state
        return state

    def _evaluate(self, request, actions, question):
        if self.recorder:
            self.recorder.check()
        self.game.rpc('pause')
        self.decisions += 1
        decision_id = self.decisions
        input_artifact = self.journal.artifact(f'decisions/{decision_id:06d}-request.json', request)
        self.journal.append('inference_started', decision=decision_id, request=input_artifact)
        result = self.client.evaluate(request['state'], request['questions'])
        output_artifact = self.journal.artifact(f'decisions/{decision_id:06d}-response.json', result)
        choice = result['answers'][question]['choice']
        action = actions[choice]
        self.journal.append('model_decision', decision=decision_id, response=output_artifact,
                            selected_question=question, action=action)
        self.pending_decisions.append(decision_id)
        self.decision = {'id':decision_id,'model':result['model'],
            'latency_ms':result['metadata']['latency_ms'],'observed_turn':self.state['turn'],
            'observed_revision':self.state['evidence']['save_sha256'],
            'input_tokens':self.client.input_tokens_total,'answers':result['answers'],
            'labels':{name:{key:key if name=='empire_strategy' else str(label) for key,label in q['criteria'].items()}
                      for name,q in request['questions'].items()},
            'selected_question':question,'action_label':action['label'],'receipt':'pending'}
        self.publish('paused')
        # Preserve a readable view of the actual decision in the full recording.
        time.sleep(.6)
        return action

    def choose_unit(self):
        actions = unit_candidates(self.state, rules=self.rules)
        action = self._evaluate(unit_request_for(self.state, actions, self.rules,
            recent_actions=list(self.history)), actions, 'unit_action')
        validate_action(action, self.state, self.rules)
        self.game.rpc('resume')
        before = self.ui.observe()
        inputs = self.ui.key(action['parameters']['key'], settle=.4)
        after = self.ui.observe()
        self.journal.append('command_dispatched', decision=self.decisions, action=action,
                            before=before['sha256'],after=after['sha256'],inputs=inputs)
        self.history.append({'turn':self.state['turn'],'actor':action['actor'],
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
        if len(actions) < 2:
            raise RuntimeError('A single forced dialog option needs an explicit mechanical handler')
        action = self._evaluate(request, actions, 'dialog_action')
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
        self.history.append({'turn':self.state['turn'],'order':action['label'],'outcome':'awaiting original game response'})
        self.chronicle.append({'id':str(self.decisions),'turn':self.state['turn'],'label':action['label'],'kind':'dialog'})
        self.publish('running')
        return action, after

    def choose_empire(self, screen, reviewed):
        actions = empire_candidates(self.state,screen,reviewed,self.rules)
        if len(actions) == 1:
            action = next(iter(actions.values()))
            self.journal.append('forced_empire_command',action=action,
                reason='All optional menu reviews were completed; only Finish Turn remains. No model distribution created.')
        else:
            request = empire_request_for(self.state,screen,actions,reviewed,self.rules,
                                           recent_actions=list(self.history))
            action = self._evaluate(request,actions,'empire_action')
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
        self.history.append({'turn':self.state['turn'],'actor':action['actor'],
            'order':action['label'],'outcome':'Awaiting the original game response'})
        self.chronicle.append({'id':str(self.decisions),'turn':self.state['turn'],
                               'label':action['label'],'kind':action['kind']})
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

    def finish(self, *, status='paused', reason='Session paused for inspection.'):
        self.game.rpc('pause')
        self.publish(status, reason)
        self.journal.append('session_stopped',status=status,reason=reason,
            decisions=self.decisions,api_requests=self.client.request_count,
            input_tokens=self.client.input_tokens_total,output_tokens=self.client.output_tokens_total)
        if self.recorder:
            recording = self.recorder.stop()
            recording['path'] = 'video/'+recording['path']
            self.journal.append('recording_finalized', **recording)
        self.journal.close()
