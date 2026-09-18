"""Run observed native-game decisions; pause on a screen requiring new support."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
import time
import zipfile
from copy import deepcopy
from .dates import city_date_match,date_key
from functools import lru_cache
from .city_controls import CityControlError, city_control_candidates, city_labor_result
from .dialogs import classify_dialog
from .preferences import configure_graphics_preferences, configure_throne_presentation
from .session import Session
from .revision import (observation_digest, observation_key, prefixed_revision,
                       revision_digest, RevisionError)


def game_text():
    bundle = Path(__file__).resolve().parents[1]/'engine/game/civ2-win31.zip'
    with zipfile.ZipFile(bundle) as source:
        return source.read('civ2/GAME.TXT').decode('cp1252')


@lru_cache(maxsize=1)
def labels_text():
    """Optional original labels catalog; absent private assets fail closed."""
    bundle=Path(__file__).resolve().parents[1]/'engine/game/civ2-win31.zip'
    if not bundle.is_file():return None
    with zipfile.ZipFile(bundle) as source:
        return source.read('civ2/LABELS.TXT').decode('cp1252')


def controller_context(session):
    """Keep native menu transactions intact across development pauses."""
    if not hasattr(session, 'controller'):
        session.controller = dict(reviewed={'turn':session.state['turn'],'actions':[]},
            pending_empire=None,pending_empire_confirmed=False,pending_city=None,active_city=None,
            production_reviewed=set(),observed_city_names=set())
    # Existing live sessions can adopt these transaction fields when paused.
    session.controller.setdefault('city_controls_reviewed', {})
    session.controller.setdefault('pending_city_control', None)
    session.controller.setdefault('pending_labor_refresh', None)
    session.controller.setdefault('pending_city_navigation', None)
    session.controller.setdefault('city_labor_ready', None)
    session.controller.setdefault('recent_founding_notices', [])
    session.controller.setdefault('throne_presentation_disabled', False)
    session.controller.setdefault('pending_diplomatic_followup', None)
    session.controller.setdefault('pending_trade', None)
    if 'pending_turn' not in session.controller:
        # Also recover this guard when a paused development controller reloads.
        finishes=[r for r in getattr(session,'history',[]) if r.get('action',{}).get('kind')=='finish_turn']
        last=finishes[-1] if finishes else None
        session.controller['pending_turn']=(dict(decision=last.get('decision'),source_turn=last['turn'])
            if last and type(last.get('turn')) is int and last['turn']>=session.state['turn'] else None)
    return session.controller


def classification_state(session):
    # A just-founded city's visible name precedes the next native save. This
    # only permits its map label; unit actions still require a fresh checkpoint.
    context = controller_context(session)
    cities = list(session.state.get('cities', []))
    names = {city['name'].casefold() for city in cities}
    cities += [{'name':name} for name in context['observed_city_names'] if name.casefold() not in names]
    return {**session.state,'cities':cities,
            'recent_founding_notices':deepcopy(context['recent_founding_notices']),
            'pending_trade':deepcopy(context['pending_trade'])}


def observed_city_identity(dialog):
    # Identity includes the visible year so two cities or later turns cannot
    # share a production-review flag. OCR body resources remain separate.
    match = city_date_match(dialog.get('title',''))
    if not match:
        return None
    name = dialog.get('observed_city_name', match[1])
    if not isinstance(name, str):
        return None
    if name.casefold() != match[1].casefold():
        proof = dialog.get('city_name_recovery', {})
        if not isinstance(proof,dict) or proof.get('ocr_text') != match[1] or proof.get('canonical_name') != name:
            return None
        if proof.get('source') == 'Unique same-year original founding notice label; no native actor binding':
            year=date_key
            if (not isinstance(proof.get('year_text'),str) or year(proof['year_text'])!=year(match[2])
                    or not re.fullmatch(r'[a-f0-9]{64}',str(proof.get('notice_image_sha256','')))
                    or type(proof.get('source_line')) is not int or proof['source_line']<0):
                return None
        elif proof.get('source') not in ('Unique one-edit match to owned city in original save',
                                         'Unique one-edit match to owned city in live memory observation'):
            return None
    return name,date_key(match[2])


def city_control_transition(session, context, observation, dialog):
    """Complete a review only after its actual follow-up returns to the city."""
    pending = context['pending_city_control']
    if pending is None:
        return None
    action = pending['action']; identifier = action['id']; kind = dialog['kind']
    expected = {'change_production':'production_choice','open_buy_quote':'buy_quote'}.get(identifier)
    if kind == expected:
        if pending['response_dispatched']:
            return 'City review dialog remained after its response; no repeated input authorized.'
        if kind == 'buy_quote' and dialog.get('resource_tag') not in ('COMPLETE0','COMPLETE1'):
            return 'City purchase quote is not a reviewed original resource.'
        pending['observed_dialog'] = {'kind':kind,'sha256':observation['sha256'],
                                      'resource_tag':dialog.get('resource_tag')}
    elif kind == 'city_screen':
        city = observed_city_identity(dialog)
        if city is None or city[0].casefold()!=pending['city'][0].casefold() or city[1]!=pending['city'][1]:
            return 'City review returned to a different or unreadable city.'
        if identifier == 'exit_city':
            return 'Exit input did not have an observed city-window transition.'
        if not pending['observed_dialog'] or not pending['response_dispatched']:
            return 'City control returned without an observed follow-up and response.'
        record = pending['reviewed']
        if identifier not in record['actions']:
            record['actions'].append(identifier)
        if identifier == 'change_production':
            context['production_reviewed'].add(city)
        session.journal.append('city_control_review_completed', decision=pending['decision'],
            action_id=identifier, reviewed=deepcopy(record),
            observed_dialog=deepcopy(pending['observed_dialog']),
            response_decision=pending['response_decision'], completion_screen=observation['sha256'])
        context['pending_city_control'] = None
    elif kind in ('normal_map','end_turn'):
        if identifier != 'exit_city':
            return 'City review closed without the expected observed completion.'
        record = pending['reviewed']
        session.journal.append('city_control_closed', decision=pending['decision'],action_id=identifier,
            city={'id':record['city_id'],'name':record['city_name'],'year_raw':record['year_raw']},
            completion_screen=observation['sha256'])
        context['pending_city_control'] = None
        context['active_city'] = None
    return None


def city_control_review(session, context, dialog, city):
    """Return the saved city's review ledger; new unsaved cities use legacy flow."""
    matches = [c for c in session.state['cities'] if c.get('name','').casefold()==city[0].casefold()]
    if not matches:
        return None
    if len(matches)!=1 or matches[0].get('owner')!=session.state.get('player',{}).get('id'):
        raise CityControlError('City screen does not identify one saved owned city')
    year = session.state.get('year_raw')
    saved_year = f'{abs(year)}'+('BC' if year<0 else 'AD') if type(year) is int else None
    if city[1] != saved_year:
        # An actual turn advance can open an automatic production window before
        # the next checkpoint. A requested inspection cannot: treating a bad
        # OCR date as a new city would silently force its production menu open.
        pending_ids=set(getattr(session,'pending_decisions',()))
        pending_orders=[item.get('action',{}) for item in getattr(session,'history',())
                        if item.get('decision') in pending_ids]
        if (not context.get('pending_empire') and pending_orders
                and any(a.get('kind')=='finish_turn' for a in pending_orders)
                and all(a.get('kind') in ('finish_turn','dialog_choice') for a in pending_orders)):
            return None
        raise CityControlError('Displayed year of an owned city differs from its current observation; no production menu was authorized')
    saved = matches[0]
    key = (saved['id'],saved['name'],session.state.get('year_raw'))
    record = context['city_controls_reviewed'].get(key)
    if record is None:
        record = {'city_id':saved['id'],'city_name':saved['name'],
                  'year_raw':session.state.get('year_raw'),'actions':[]}
    # A prior production response is only synced once the full city is seen.
    if city in context['production_reviewed'] and 'change_production' not in record['actions']:
        record['actions'].append('change_production')
    city_control_candidates(session.state,dialog,record,session.rules)
    context['city_controls_reviewed'][key] = record
    return record



def _labor_city(state, actor):
    fields=('id','owner','name','x','y')
    matches=[c for c in state.get('cities',[]) if c.get('id')==actor['id']]
    if len(matches)!=1 or any(matches[0].get(k)!=actor.get(k) for k in fields):
        raise CityControlError('Labor refresh cannot bind the same owned city')
    return {k:matches[0][k] for k in fields}


def start_labor_refresh(session,context,city,*,action=None,decision=None,preparation_action=None):
    if context['pending_labor_refresh'] is not None:raise CityControlError('A labor refresh is already pending')
    signature=_labor_city(session.state,city)
    if preparation_action is not None:
        if (action is not None or type(decision) is not int or decision<1
                or preparation_action.get('kind')!='city_control'
                or preparation_action.get('id')!='review_labor'
                or preparation_action.get('parameters',{}).get('observed_text','').casefold()!='exit'
                or preparation_action.get('parameters',{}).get('expected_screen')!='fresh_city_labor'
                or any(preparation_action.get('actor',{}).get(k)!=v for k,v in signature.items())
                or revision_digest(preparation_action.get('preconditions',{}))!=observation_digest(session.state)):
            raise CityControlError('Labor preparation requires the selected, bound native Exit action')
    pending=dict(phase='await_map' if preparation_action else 'need_close',purpose='verify_labor' if action else 'prepare_labor_choices',
        city=signature,year_raw=session.state['year_raw'],action=deepcopy(action),decision=decision,
        before=deepcopy(session.state),**{'checkpoint_'+observation_key(session.state):None})
    context['pending_labor_refresh']=pending;context['city_labor_ready']=None
    preparation={'preparation_action':deepcopy(preparation_action)} if preparation_action else {}
    session.journal.append('city_labor_refresh_started',decision=decision,purpose=pending['purpose'],
        action=deepcopy(action),city=signature,**prefixed_revision(session.state,'before_'),**preparation)


def labor_refresh_step(session,context,observation,dialog,resources):
    """Mechanical close/observe/reopen only; no inferred success or labor selection."""
    pending=context['pending_labor_refresh']
    if pending is None:return False,None
    phase=pending['phase'];kind=dialog['kind'];city=pending['city']
    if phase=='failed':return True,pending['failure']
    year=pending['year_raw'];expected_year=f'{abs(year)}'+('BC' if year<0 else 'AD')
    def failed(message):
        pending.update(phase='failed',failure=message)
        session.journal.append('city_labor_refresh_failed',decision=pending['decision'],
            purpose=pending['purpose'],reason=message)
        return True,message
    information=dialog.get('mechanical_action')=='acknowledge_information'
    if phase in ('need_close','await_reopened'):
        if kind!='city_screen':
            return (False,None) if information else failed('Labor refresh requires the same complete city screen')
        identity=observed_city_identity(dialog)
        if identity is None or identity[0].casefold()!=city['name'].casefold() or identity[1]!=expected_year:
            return failed('Labor refresh observed a different city or year')
        if phase=='await_reopened':
            if observation_digest(session.state)!=revision_digest(pending,'checkpoint_'):
                return failed('Labor refresh observation changed before reopening')
            context['city_labor_ready']={'city':deepcopy(city),**prefixed_revision(session.state)}
            session.journal.append('city_labor_ready',decision=pending['decision'],purpose=pending['purpose'],
                city=deepcopy(city),**prefixed_revision(session.state),screen=observation['sha256'])
            context['pending_labor_refresh']=None
            return False,None
        exits=[b for b in dialog['buttons'] if b['text'].casefold()=='exit']
        if len(exits)!=1:return failed('Labor refresh requires a uniquely observed city Exit')
        session.game.rpc('resume');inputs=session.ui.key('Escape')
        session.journal.append('city_labor_refresh_input',decision=pending['decision'],purpose=pending['purpose'],
            step='close_city',before=observation['sha256'],inputs=inputs)
        pending['phase']='await_map';time.sleep(.4)
        return True,None
    if phase=='await_map':
        if kind=='city_screen':return failed('Labor refresh Exit did not close the city window')
        if kind not in ('normal_map','end_turn'):
            return (False,None) if information else failed('Labor refresh requires the original map before observing state')
        session.checkpoint();pending['phase']='checkpointed'
        try:
            _labor_city(session.state,city)
            if session.state['turn']!=pending['before']['turn'] or session.state['year_raw']!=year:
                return failed('Labor refresh unexpectedly advanced the original turn')
            result=city_labor_result(pending['action'],pending['before'],session.state) if pending['action'] else None
        except (CityControlError,ValueError) as error:return failed(str(error))
        pending.update(prefixed_revision(session.state,'checkpoint_'))
        session.journal.append('city_labor_checkpoint',decision=pending['decision'],purpose=pending['purpose'],
            checkpoint=session.checkpoints,**prefixed_revision(session.state),result=result)
        if result:
            for record in reversed(session.history):
                if record.get('decision')==pending['decision']:
                    record['outcome']='Native labor checkpoint: '+result['status']
                    record['observed_labor']=deepcopy(result);break
            if result['status']=='unexpected_change':return failed('Native labor bitmap or specialist result differed from the selected change')
        # Reobserve the original pixels before any locator input.
        observation,dialog=observe_ready(session,resources);kind=dialog['kind']
        session.journal.append('screen_observed',screen=observation['sha256'],classification=kind,
            supported=dialog['supported'],path=Path(observation['path']).relative_to(session.journal.directory).as_posix())
        if not dialog['supported']:return True,'Original screen after labor checkpoint requires inspection.'
        phase='checkpointed'
    if phase=='checkpointed':
        if kind not in ('normal_map','end_turn'):
            return (False,None) if information else failed('Labor refresh requires the original map before reopening')
        session.game.rpc('resume');inputs=session.game.chord('ShiftLeft','KeyC',hold_ms=120)
        session.journal.append('city_labor_refresh_input',decision=pending['decision'],purpose=pending['purpose'],
            step='open_locator',before=observation['sha256'],inputs=inputs)
        context['pending_city']=deepcopy(city);pending['phase']='await_locator';time.sleep(.4)
        return True,None
    if phase=='await_locator':
        if kind=='city_locator' or information:return False,None
        return failed('Labor refresh locator input had no observed transition')
    return failed('Unknown labor refresh phase')


def _native_map_fallback(session, observation, dialog, resources, _attempt=0, *, attempts=3, phase=0):
    """Bounded read-only attempts for a map proof still visible on the canvas."""
    from .native_map import LEFT_MAP_REASON, archive_read
    from .observe import recognize
    if (getattr(session, 'observer', None) is None or dialog.get('supported')
            or dialog.get('kind') != 'unknown' or dialog.get('reason') != LEFT_MAP_REASON):
        return observation, dialog
    trigger = session.journal.artifact(f'screens/native-map-trigger-{session.journal.sequence+1:06d}-'+observation['sha256']+'.png',
                                       Path(observation['path']).read_bytes())
    if trigger['sha256'] != observation['sha256']:
        raise ValueError('Native map trigger image changed')
    changed_frame=False
    try:
        value = session.observer.read(rules_text=session.rules_text,
                                      middle_settle=(0.0,.25,.5)[(_attempt+phase)%3])
        status = session.game.rpc('status')
        if status.get('paused') is not True or status.get('heldKeys') or status.get('buttons'):
            raise ValueError('Native map context must return paused with no held input')
        state, context, artifact, receipt = archive_read(session.journal,value,status['inputSequence'])
        middle = session.journal.directory/receipt['source_images'][1]
        fresh = recognize(middle);fresh['path'] = str(middle)
        classified = classify_dialog(fresh,rules=session.rules,game_text=resources,labels_text=labels_text(),
                                     state=state,native_map_context=context)
        # The observer's middle image is bracketed by its native snapshots,
        # but later frames can finish a blink or helper-window repaint before
        # pause. Never send an already stale middle image to inference.
        current_png=session.game.request('/bridge/capture/game',binary=True)
        current_hash=hashlib.sha256(current_png).hexdigest()
        final_status=session.game.rpc('status')
        if (final_status.get('paused') is not True or final_status.get('inputSequence') != status['inputSequence']
                or final_status.get('heldKeys') or final_status.get('buttons')):
            raise ValueError('Ordinary input changed during native map classification')
        if current_hash != fresh['sha256']:
            session.journal.artifact(f'screens/native-map-current-{session.journal.sequence+1:06d}-{current_hash}.png',current_png)
            changed_frame=True
            raise ValueError('Bracketed native map image is no longer the paused canvas')
        if not classified.get('supported') or classified.get('kind') not in ('normal_map','end_turn'):
            raise ValueError('Native map proof did not establish original map/status cues')
        session.journal.append('native_map_observed',trigger_image=trigger,trigger_reason=LEFT_MAP_REASON,
            artifact=artifact,receipt=receipt,input_sequence=status['inputSequence'],
            observation={k:deepcopy(fresh[k]) for k in ('width','height','sha256','lines')},
            classification={k:classified[k] for k in ('kind','supported','reason')})
        return fresh, classified
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        session.journal.append('native_map_observation_failed',trigger_image=trigger,
            trigger_reason=LEFT_MAP_REASON,error_type=type(error).__name__)
        if changed_frame and _attempt+1<attempts:
            return _native_map_fallback(session,observation,dialog,resources,_attempt+1,attempts=attempts,phase=phase)
        return observation, dialog


def observe_ready(session, resources):
    """Wait only for native painting, including the blinking end-turn cue.

    Uneven waits avoid repeatedly sampling the same low-contrast blink phase.
    It may park the pointer off the playfield, without clicks or keys.
    """
    observation = session.ui.observe()
    dialog = classify_dialog(observation, rules=session.rules, game_text=resources, labels_text=labels_text(),
                             state=classification_state(session))
    cursor = observation.get('cursor_hotspot')
    if not dialog['supported'] and cursor and max(abs(cursor[0]-2),abs(cursor[1]-1)) > 1:
        session.game.rpc('resume')
        receipt = session.ui.park_pointer()
        session.game.rpc('pause')
        session.journal.append('pointer_park_for_observation',before=observation['sha256'],receipt=receipt)
        observation = session.ui.observe()
        dialog = classify_dialog(observation, rules=session.rules, game_text=resources, labels_text=labels_text(),
                                 state=classification_state(session))
    observation, dialog = _native_map_fallback(session, observation, dialog, resources)
    delays = (.13, .37, .61, .19, .43, .73, .29, .47)
    # These failures already passed the original Roman map/menu/pane guards.
    # A blinking cue or animated city artwork may need a longer paint window.
    # Merely wait and reobserve: the same strict classifier must still succeed.
    map_paint_reasons = {
        'Native moving-unit or end-of-turn status is not uniquely observed',
        'Unexpected text over the native map playfield; possible unrecognized modal',
    }
    extended = (.83, .31, .67, .23, .89, .41, .59, .17, .79, .53, .71, .37)
    proof_waits=(0,3,6,10,14,19)
    for index, delay in enumerate(delays + extended):
        if dialog['supported']:
            break
        if index >= len(delays) and (dialog.get('kind') != 'unknown'
                or dialog.get('reason') not in map_paint_reasons):
            break
        session.game.rpc('resume')
        time.sleep(delay)
        session.game.rpc('pause')
        observation = session.ui.observe()
        dialog = classify_dialog(observation, rules=session.rules, game_text=resources, labels_text=labels_text(),
                                 state=classification_state(session))
        # Map artwork will not vanish during painting. Interleave at most six
        # fresh single proofs with these waits instead of only checking the
        # last blink phase. Never reuse an earlier topology or screenshot.
        if (index in proof_waits and not dialog.get('supported') and dialog.get('kind') == 'unknown'
                and dialog.get('reason') == 'Unexpected text over the native map playfield; possible unrecognized modal'):
            observation, dialog = _native_map_fallback(session, observation, dialog, resources,
                attempts=1,phase=proof_waits.index(index)%3)
    return observation, dialog


def _await_diplomatic_followup(session, context, observation, dialog, resources):
    """An agreed audience can briefly expose the map while its herald loads.

    No input or checkpoint is permitted in that gap. Only a separately observed
    supported emissary follow-up completes this pending transaction.
    """
    pending=context['pending_diplomatic_followup']
    if pending is None:return observation,dialog,None
    for attempt in range(21):
        if (dialog.get('supported') and isinstance(dialog.get('resource_tag'),str)
                and dialog['resource_tag'] and dialog['resource_tag']!='EMISSARY'
                and re.search(r'\bemissary$',dialog.get('title',''),re.I)):
            session.journal.append('diplomatic_followup_observed',decision=pending['decision'],
                source_hash=pending['source_hash'],screen=observation['sha256'],
                resource_tag=dialog.get('resource_tag'),title=dialog.get('title'))
            context['pending_diplomatic_followup']=None
            return observation,dialog,None
        if dialog.get('kind') not in ('normal_map','end_turn') or not dialog.get('supported'):
            error='Agreed diplomatic audience follow-up is not yet identified; no further input issued.' if dialog.get('supported') else None
            return observation,dialog,error
        if attempt==20:
            return observation,dialog,'Agreed diplomatic audience has no observed follow-up yet; no map input issued.'
        session.game.rpc('resume')
        try:time.sleep(.5)
        finally:session.game.rpc('pause')
        observation=session.ui.observe()
        dialog=classify_dialog(observation,rules=session.rules,game_text=resources, labels_text=labels_text(),state=classification_state(session))
    raise AssertionError('Bounded diplomatic wait exhausted')


def _checkpoint_token(session):
    """A fresh observation can be reused once, only inside this running loop."""
    state = session.state
    try:
        digest = observation_digest(state)
    except RevisionError:
        return None
    checkpoint = getattr(session, 'checkpoints', None)
    sequence = getattr(session.journal, 'sequence', None)
    if (not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
            or type(checkpoint) is not int or checkpoint < 1 or type(sequence) is not int
            or type(state.get('turn')) is not int or type(state.get('year_raw')) is not int
            or getattr(session, 'pending_decisions', None) != []):
        return None
    return dict(checkpoint=checkpoint, **prefixed_revision(state), turn=state['turn'],
                year=state['year_raw'], journal_sequence=sequence)


def _await_turn_resolution(session,context,observation,dialog,resources):
    """FinishTurn stays pending through combat, diplomacy and production.

    A stale End of Turn caption during enemy movement cannot authorize another
    command. Let the original game run, handling real modal choices in the
    ordinary controller, until a later native turn reaches a supported map.
    """
    pending=context['pending_turn']
    if pending is None:return observation,dialog,None
    for attempt in range(41):
        if not dialog.get('supported') or dialog.get('kind') not in ('normal_map','end_turn'):
            return observation,dialog,None
        session.checkpoint()
        turn=session.state['turn']
        if turn>pending['source_turn']:
            observation,dialog=observe_ready(session,resources)
            if dialog.get('supported') and dialog.get('kind') in ('normal_map','end_turn'):
                context['pending_turn']=None
            return observation,dialog,None
        if turn<pending['source_turn']:
            return observation,dialog,'Native turn moved backward while resolving FinishTurn.'
        if attempt==40:
            return observation,dialog,'Original turn is still resolving; no further map command issued.'
        session.game.rpc('resume')
        try:time.sleep(.25)
        finally:session.game.rpc('pause')
        observation,dialog=observe_ready(session,resources)
    raise AssertionError('Bounded turn-resolution wait exhausted')


def navigate_city(session,context,observation,dialog,resources):
    """Retain each completed locator step; never replay an uncertain navigation."""
    if context['pending_city_navigation'] is not None:
        return 'City navigation is incomplete; deliberate reviewed recovery is required.'
    city=context['pending_city']
    matches=[option for option in dialog['options'] if option['text'].casefold()==city['name'].casefold()]
    if len(matches)!=1:return 'Selected city is not uniquely present in the native locator.'
    pending=dict(city=deepcopy(city),source_hash=observation['sha256'],phase='select_city',
        receipt=None,zoom_receipt=None,blocked=False)
    context['pending_city_navigation']=pending

    def failed(reason,error=None):
        pending['blocked']=True
        pending['reason']=reason[:500]
        session.journal.append('city_navigation_incomplete',
            **{k:deepcopy(pending[k]) for k in ('city','source_hash','phase','receipt','zoom_receipt')},
            reason=pending['reason'],error_type=type(error).__name__[:80] if error is not None else None)
        session.game.rpc('pause')
        return pending['reason']

    failure_reason=None
    try:
        session.game.rpc('resume')
        pending['receipt']=session.ui.select_text(observation,matches[0]['text'],exact=True,
            source_line=matches[0]['source_line'],center=matches[0]['center'])
        pending['phase']='observe_selection'
        # This is a fresh BEFORE-Zoom check and deliberately remains strict.
        selected=session.ui.observe()
        selected_dialog=classify_dialog(selected,rules=session.rules,game_text=resources,
            labels_text=labels_text(),state=classification_state(session))
        if selected_dialog['kind']!='city_locator' or not selected_dialog['supported']:
            failure_reason='Native city locator changed during selection.'
        else:
            zoom=[button for button in selected_dialog['buttons'] if button['text'].casefold()=='zoom to city']
            if len(zoom)!=1:
                failure_reason='Native Zoom To City control is not uniquely observed.'
            else:
                pending['phase']='zoom_city'
                pending['zoom_receipt']=session.ui.select_text(selected,zoom[0]['text'],exact=True,
                    source_line=zoom[0]['source_line'],center=zoom[0]['center'])
    except Exception as error:
        partial=getattr(error,'selection_receipt',None)
        if isinstance(partial,dict) and pending['phase'] in ('select_city','zoom_city'):
            pending['receipt' if pending['phase']=='select_city' else 'zoom_receipt']=deepcopy(partial)
        return failed('Native city navigation failed during '+pending['phase']+'.',error)
    if failure_reason:return failed(failure_reason)
    session.journal.append('navigate_selected_city',city=city,
        receipt=pending['receipt'],zoom_receipt=pending['zoom_receipt'])
    context['pending_city_navigation']=None
    if context['pending_labor_refresh'] and context['pending_labor_refresh']['phase']=='await_locator':
        context['pending_labor_refresh']['phase']='await_reopened'
    return None


def run_steps(session, *, max_decisions=10000):
    resources = game_text()
    context = controller_context(session)
    if context['pending_city_navigation'] is not None:
        session.game.rpc('pause')
        return {'status':'paused','reason':'City navigation is incomplete; deliberate reviewed recovery is required.'}
    housekeeping = 0
    verified_endturn_checkpoint = None
    while (session.decisions < max_decisions or context['pending_labor_refresh'] is not None
           or getattr(session,'pending_unit_activation',None) is not None):
        if session.recorder:
            session.recorder.check()
        session.game.rpc('pause')
        session.publish('paused')
        reuse_checkpoint = (verified_endturn_checkpoint is not None
                            and _checkpoint_token(session) == verified_endturn_checkpoint)
        observation, dialog = observe_ready(session, resources)
        observation,dialog,audience_wait_error=_await_diplomatic_followup(session,context,observation,dialog,resources)
        observation,dialog,turn_wait_error=_await_turn_resolution(session,context,observation,dialog,resources)
        Session.observe_dialog_feedback(session,dialog)
        # Pointer movement is harmless to strategy but still an ordinary input.
        # Its observation-recovery event invalidates the strict no-input token.
        reuse_checkpoint = reuse_checkpoint and _checkpoint_token(session) == verified_endturn_checkpoint
        source_checkpoint, verified_endturn_checkpoint = verified_endturn_checkpoint, None
        session.journal.append('screen_observed', screen=observation['sha256'],
                                classification=dialog['kind'],supported=dialog['supported'],
                                path=Path(observation['path']).relative_to(session.journal.directory).as_posix(),
                                **({'native_rejection':dialog['native_rejection']} if dialog.get('native_rejection') else {}),
                                **({'quote':dialog['quote'],'resource_tag':dialog.get('resource_tag')} if dialog.get('quote') else {}))
        if audience_wait_error:
            return {'status':'paused','reason':audience_wait_error,'screen':observation['path']}
        if turn_wait_error:
            return {'status':'paused','reason':turn_wait_error,'screen':observation['path']}
        if getattr(session,'pending_unit_activation',None) is not None:
            session.advance_unit_activation(observation,dialog,resources,labels_text())
            continue
        if not dialog['supported']:
            return {'status':'paused','reason':'Original screen requires a controller update.',
                    'screen':observation['path'],'classification':dialog}
        kind = dialog['kind']
        handled,labor_error = labor_refresh_step(session,context,observation,dialog,resources)
        if labor_error:return {'status':'paused','reason':labor_error,'screen':observation['path']}
        if handled:continue
        if session.decisions >= max_decisions and context['pending_labor_refresh'] is None:return {'status':'paused','reason':'Development decision checkpoint reached.'}
        city_error = city_control_transition(session, context, observation, dialog)
        if city_error:
            return {'status':'paused','reason':city_error,'screen':observation['path']}
        if kind in ('normal_map','end_turn') and not context.get('graphics_configured', False):
            receipt = configure_graphics_preferences(session.ui)
            session.journal.append('graphics_preferences_configured', receipt=receipt)
            context['graphics_configured'] = True
            continue  # Reobserve after the verified presentation-only setup.
        if kind in ('normal_map','end_turn') and not context['throne_presentation_disabled']:
            receipt = configure_throne_presentation(session.ui)
            session.journal.append('graphics_preferences_configured', receipt=receipt)
            context['throne_presentation_disabled'] = True
            continue  # Reobserve after the independently verified cosmetic toggle.
        if dialog.get('observed_city_name'):
            context['observed_city_names'].add(dialog['observed_city_name'])
        founded = dialog.get('founded_city')
        if (dialog.get('resource_tag') == 'FOUNDED' and isinstance(founded, dict)
                and isinstance(founded.get('name'), str) and isinstance(founded.get('year_text'), str)
                and founded.get('source') == 'Original founding notice text'):
            notices = context['recent_founding_notices']
            if not any(item['name'] == founded['name'] and item['year_text'] == founded['year_text']
                       for item in notices):
                notices.append({'name':founded['name'], 'year_text':founded['year_text'],
                                'source_tag':'FOUNDED', 'image_sha256':observation['sha256']})
                del notices[:-4]
        pending = context['pending_empire']
        expected = {'open_tax':{'tax_rate','luxury_rate','tax_allocation'},
                    'open_research':{'science_advisor'},
                    'open_diplomacy':{'foreign_minister'},
                    'open_revolution':{'revolution_choice','revolution_offer'}}
        if pending and kind in expected.get(pending['id'],set()):
            context['pending_empire_confirmed'] = True
        if pending and pending['id']=='open_diplomacy' and dialog.get('resource_tag')=='NOFOREIGN':
            context['pending_empire_confirmed'] = True
        if kind in ('victory','game_over'):
            return {'status':'paused','reason':'Original end-game screen awaits outcome verification.',
                                'screen':observation['path'],'classification':dialog}
        if dialog['mechanical_action']=='accept_single_trade_advance':
            pending=context['pending_trade']
            if (pending is None or pending!=dialog.get('prior_trade')
                    or session.decisions!=pending['decision']):
                return {'status':'paused','reason':'Trade continuation has no current accepted model exchange.'}
            current=session.ui.observe()
            if current['sha256']!=observation['sha256']:
                return {'status':'paused','reason':'Trade continuation changed before confirmation.'}
            # Consume first: an uncertain input must never authorize a retry.
            context['pending_trade']=None
            session.game.rpc('resume')
            inputs=session.ui.key('Enter',settle=.15)
            after=session.ui.observe(retain_unreadable=True)
            session.journal.append('trade_advance_dispatched',prior_trade=pending,
                advance=dialog['advance'],before=observation['sha256'],after=after['sha256'],
                resource_tag='TAKECIV',evidence=dialog['evidence'],inputs=inputs,
                scope='Confirm sole already-selected advance in the immediately preceding Jev-accepted trade; no new model choice')
            continue
        if dialog['mechanical_action'] == 'acknowledge_presentation':
            housekeeping += 1
            if housekeeping > 20:
                raise RuntimeError('Repeated presentation screens need inspection')
            buttons = dialog.get('buttons', [])
            if len(buttons) != 1:
                return {'status':'paused','reason':'Native presentation prompt was not uniquely observed.',
                        'screen':observation['path']}
            point = dialog.get('acknowledgement_point')
            if (not isinstance(point, list) or len(point) != 2 or any(type(v) is not int for v in point)
                    or not 0 <= point[0] <= 627 or not 0 <= point[1] <= 460):
                return {'status':'paused','reason':'Native presentation narrative point was not observed.',
                        'screen':observation['path']}
            session.game.rpc('resume')
            inputs = session.game.click(*point)
            after = session.ui.observe(retain_unreadable=True)
            receipt = {'target':buttons[0]['text'], 'point':point, 'before':observation['sha256'],
                'selected_frame':after['sha256'], 'inputs':inputs,
                'method':'Original full-screen click-to-continue prompt; clicked observed narrative'}
            session.journal.append('native_presentation_acknowledged', receipt=receipt,
                source_hash=observation['sha256'], resource_tag=dialog.get('resource_tag'),
                acknowledgement_point=point, template_sha256=dialog.get('evidence', {}).get('template_sha256'))
            time.sleep(1.2)
            continue
        if dialog['mechanical_action'] == 'close_reference':
            exits = [button for button in dialog['buttons'] if button['text'].casefold() == 'exit']
            if len(exits) != 1:
                return {'status':'paused','reason':'Reference exit was not uniquely observed.', 'screen':observation['path']}
            session.game.rpc('resume')
            receipt = session.ui.select_text(observation, exits[0]['text'], exact=True, timeout=120)
            session.journal.append('close_native_reference', screen=observation['sha256'], receipt=receipt)
            time.sleep(1.2)
            continue
        if dialog['mechanical_action'] in ('acknowledge_information','accept_observed_default_name'):
            housekeeping += 1
            if housekeeping > 20:
                raise RuntimeError('Repeated information screens need inspection')
            if kind == 'new_city_name' and dialog.get('default_name'):
                context['observed_city_names'].add(dialog['default_name'])
            if kind == 'rule_rejection':
                session.note_native_rejection(dialog)
            Session.remember_public_notice(session, observation, dialog, resources)
            session.mechanical(dialog['mechanical_action'])
            pending_control = context['pending_city_control']
            if (pending_control and kind=='buy_quote' and dialog.get('resource_tag')=='COMPLETE0'
                    and pending_control['observed_dialog']):
                pending_control['response_dispatched'] = True
                pending_control['response_decision'] = None
            # The founded-city notice can return to the map while the city
            # window is still being created. Let its original repaint finish.
            session.game.rpc('resume')
            time.sleep(1.2)
            continue
        if kind == 'city_screen':
            city = observed_city_identity(dialog)
            if city is None:
                return {'status':'paused','reason':'Original city identity is unreadable.', 'screen':observation['path']}
            if context['pending_city'] and city[0].casefold() != context['pending_city']['name'].casefold():
                return {'status':'paused','reason':'Native city screen does not match the requested city.', 'screen':observation['path']}
            if context['pending_city']:
                context['pending_empire_confirmed'] = True
            context['pending_city'] = None
            context['active_city'] = city
            context['observed_city_names'].add(city[0])
            session.city_report = {'source_image':observation['sha256'],'city_name':city[0],'text':observation['text']}
            try:
                review = city_control_review(session, context, dialog, city)
            except CityControlError as error:
                return {'status':'paused','reason':str(error),'screen':observation['path']}
            if review is not None:
                actions=city_control_candidates(session.state,dialog,review,session.rules)
                actor=actions['exit_city']['actor']
                ready=context['city_labor_ready']=={'city':_labor_city(session.state,actor),
                    **prefixed_revision(session.state)}
                previous_decisions = session.decisions
                if ready and getattr(session,'unit_activation_enabled',False):
                    action,_=session.choose_city_control(dialog,review,labor_ready=True,
                        observation=observation,activation_ready=True)
                else:
                    action, _ = session.choose_city_control(dialog, review, labor_ready=True) if ready else session.choose_city_control(dialog,review)
                decision=session.decisions if session.decisions>previous_decisions else None
                if action['kind']=='unit_activation':
                    context['city_labor_ready']=None
                elif action['id']=='review_labor':
                    start_labor_refresh(session,context,action['actor'],decision=decision,preparation_action=action)
                elif action['kind']=='city_labor':
                    review['labor_reassignments']=review.get('labor_reassignments',0)+1
                    start_labor_refresh(session,context,action['actor'],action=action,decision=decision)
                else:
                    context['city_labor_ready']=None
                    context['pending_city_control'] = {'action':action,'city':city,'reviewed':review,
                        'decision':decision,'observed_dialog':None,'response_dispatched':False,'response_decision':None}
                housekeeping = 0
                time.sleep(1.2)
                continue
            # Opening the native production menu exposes the strategic choices;
            # only Jev picks what the city will actually build.
            label = 'Exit' if city in context['production_reviewed'] else 'Change'
            matches = [b for b in dialog['buttons'] if b['text'].casefold() == label.casefold()]
            if len(matches) != 1:
                return {'status':'paused','reason':'City control was not uniquely observed.', 'screen':observation['path']}
            session.game.rpc('resume')
            if label == 'Exit':
                inputs = session.ui.key('Escape')
                receipt = {'target':'Exit','before':observation['sha256'],'inputs':inputs,
                           'method':'Native city-window Escape shortcut, verified on original Rome screen'}
            else:
                receipt = session.ui.select_text(observation, matches[0]['text'], exact=True)
            session.journal.append('open_city_control', target=label, receipt=receipt)
            time.sleep(1.2)
            continue
        if kind == 'end_turn':
            if reuse_checkpoint:
                reuse_checkpoint = session.journal.sequence == source_checkpoint['journal_sequence'] + 1
            if reuse_checkpoint:
                session.journal.append('checkpoint_reused',
                    **{key:value for key,value in source_checkpoint.items() if key!='journal_sequence'},
                    screen=observation['sha256'], ordinary_inputs_since_checkpoint=False,
                    reason='Immediately preceding end-turn verification saved the advanced native turn; observation only since that save')
            else:
                session.checkpoint()
            if context['reviewed']['turn'] != session.state['turn']:
                context['reviewed'] = {'turn':session.state['turn'],'actions':[]}
                year = session.state['year_raw']
                year_text = f'{abs(year)}'+('BC' if year<0 else 'AD')
                context['production_reviewed'] = {c for c in context['production_reviewed'] if c[1]==year_text}
                context['city_controls_reviewed'] = {key:value for key,value in context['city_controls_reviewed'].items()
                                                    if value['year_raw']==year}
            elif context['pending_empire']:
                if not context['pending_empire_confirmed']:
                    return {'status':'paused','reason':'Requested empire menu did not have an observed successful review.', 'screen':observation['path']}
                context['reviewed']['actions'].append(context['pending_empire']['id'])
            context['pending_empire'] = None
            if not reuse_checkpoint:
                observation, dialog = observe_ready(session, resources)
            if dialog['kind'] != 'end_turn' or not dialog['supported']:
                return {'status':'paused','reason':'End-turn checkpoint changed the observed screen.', 'screen':observation['path']}
            previous_turn = session.state['turn']
            action,next_screen = session.choose_empire(dialog,context['reviewed'])
            if action['id']=='finish_turn':
                context['pending_turn']=dict(decision=session.decisions,source_turn=previous_turn)
            if action['id'] != 'finish_turn':
                context['pending_empire'] = action
                context['pending_empire_confirmed'] = False
                context['pending_city'] = action['parameters'].get('target_city')
            elif classify_dialog(next_screen,rules=session.rules,game_text=resources, labels_text=labels_text(),state=classification_state(session))['kind'] == 'end_turn':
                # With every unit fortified, busy or consumed, the next turn
                # can immediately reach the same indicator. Verify the actual
                # original save rather than treating an unchanged kind as a
                # failed turn or blindly sending Enter again.
                session.checkpoint()
                if session.state['turn'] > previous_turn:
                    context['pending_turn']=None
                    verified_endturn_checkpoint = _checkpoint_token(session)
            continue
        if kind == 'city_locator' and context['pending_city']:
            error=navigate_city(session,context,observation,dialog,resources)
            if error:return {'status':'paused','reason':error,'screen':observation['path']}
            time.sleep(1.2)
            continue
        if kind == 'normal_map':
            context['active_city'] = None
            housekeeping = 0
            session.checkpoint()
            session.choose_unit()
            continue
        if dialog['requires_model']:
            if len(dialog['options']) == 1:
                return {'status':'paused','reason':'A forced choice needs a verified mechanical handler.', 'screen':observation['path']}
            choice=session.choose_dialog(dialog)
            if isinstance(choice,tuple) and len(choice)==2:
                from .exchange_picker import accepted_trade_context
                context['pending_trade']=accepted_trade_context(dialog,choice[0],session.decisions,session.rules)
                if context['pending_trade'] is not None:
                    session.journal.append('trade_followup_pending',prior_trade=context['pending_trade'])
            if dialog.get('resource_tag')=='EMISSARY' and isinstance(choice,tuple) and len(choice)==2:
                action=choice[0]
                if (action.get('kind')=='dialog_choice' and action.get('parameters',{}).get('option_index')==0
                        and action['parameters'].get('observed_text')==dialog['options'][0]['text']):
                    context['pending_diplomatic_followup']={'decision':session.decisions,
                        'source_hash':observation['sha256'],'title':dialog['title']}
                    session.journal.append('diplomatic_followup_pending',**context['pending_diplomatic_followup'])
            pending_control = context['pending_city_control']
            if pending_control and pending_control['observed_dialog'] and kind==pending_control['observed_dialog']['kind']:
                pending_control['response_dispatched'] = True
                pending_control['response_decision'] = session.decisions
            elif kind == 'production_choice':
                if context['active_city'] is not None:
                    context['production_reviewed'].add(context['active_city'])
            housekeeping = 0
            continue
        return {'status':'paused','reason':'Original game screen requires inspection.', 'screen':observation['path']}
    return {'status':'paused','reason':'Development decision checkpoint reached.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    backend=parser.add_mutually_exclusive_group(required=True)
    backend.add_argument('--initial-save')
    backend.add_argument('--no-saves',action='store_true',help='Observe live original memory; never create native game saves')
    parser.add_argument('--setup-directory',help='Retained fresh no-save setup evidence (required with --no-saves)')
    parser.add_argument('--directory', required=True)
    parser.add_argument('--env-file')
    parser.add_argument('--max-decisions', type=int, default=10000)
    parser.add_argument('--max-requests', type=int, default=20000)
    parser.add_argument('--fps',type=int,default=4)
    parser.add_argument('--port',type=int,default=3920)
    parser.add_argument('--planning',action='store_true',help='Ask Jev for persistent unit objectives before independent action choices')
    parser.add_argument('--unit-activation',action='store_true',help='Offer verified fortified-unit activation after a fresh city review')
    args = parser.parse_args()
    if args.no_saves and not args.setup_directory:
        parser.error('--no-saves requires --setup-directory')
    if not args.no_saves and args.setup_directory:
        parser.error('--setup-directory is only used with --no-saves')
    from .engine import Game
    game=Game(port=args.port)
    observer=None
    if args.no_saves:
        from .memory import LiveMemoryObserver
        import uuid
        observer=LiveMemoryObserver(game,Path('.runtime/observers')/uuid.uuid4().hex)
    session = Session(args.directory,args.initial_save,env_file=args.env_file,
                      max_requests=args.max_requests,fps=args.fps,
                      game=game,planning=args.planning,observer=observer,setup_directory=args.setup_directory)
    outcome = None
    try:
        if args.unit_activation:
            session.enable_unit_activation()
        outcome = run_steps(session,max_decisions=args.max_decisions)
        print(json.dumps(outcome))
    finally:
        session.finish(status='paused',reason=(outcome or {}).get('reason','Controller stopped; inspect local evidence.'))


if __name__ == '__main__':
    main()
