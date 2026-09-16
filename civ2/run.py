"""Run observed native-game decisions; pause on a screen requiring new support."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
import time
import zipfile
from .dialogs import classify_dialog
from .session import Session


def game_text():
    bundle = Path(__file__).resolve().parents[1]/'engine/game/civ2-win31.zip'
    with zipfile.ZipFile(bundle) as source:
        return source.read('civ2/GAME.TXT').decode('cp1252')


def controller_context(session):
    """Keep native menu transactions intact across development pauses."""
    if not hasattr(session, 'controller'):
        session.controller = dict(reviewed={'turn':session.state['turn'],'actions':[]},
            pending_empire=None,pending_empire_confirmed=False,pending_city=None,active_city=None,
            production_reviewed=set(),observed_city_names=set())
    return session.controller


def classification_state(session):
    # A just-founded city's visible name precedes the next native save. This
    # only permits its map label; unit actions still require a fresh checkpoint.
    context = controller_context(session)
    cities = list(session.state.get('cities', []))
    names = {city['name'].casefold() for city in cities}
    cities += [{'name':name} for name in context['observed_city_names'] if name.casefold() not in names]
    return {**session.state,'cities':cities}


def observed_city_identity(dialog):
    # Identity includes the visible year so two cities or later turns cannot
    # share a production-review flag. OCR body resources remain separate.
    match = re.match(r'City of (.+?),\s*(\d+\s*(?:B\.?\s*C\.?|A\.?\s*D\.?))', dialog.get('title',''), re.I)
    return (match[1],re.sub(r'[^0-9A-Z]','',match[2].upper())) if match else None


def observe_ready(session, resources):
    """Wait only for native painting, including the blinking end-turn cue.

    Uneven waits avoid repeatedly sampling the same low-contrast blink phase.
    This issues no keys or mouse input and never repairs an unknown label.
    """
    observation = session.ui.observe()
    dialog = classify_dialog(observation, rules=session.rules, game_text=resources,
                             state=classification_state(session))
    for delay in (.13, .37, .61, .19, .43, .73, .29, .47):
        if dialog['supported']:
            break
        session.game.rpc('resume')
        time.sleep(delay)
        session.game.rpc('pause')
        observation = session.ui.observe()
        dialog = classify_dialog(observation, rules=session.rules, game_text=resources,
                                 state=classification_state(session))
    return observation, dialog


def run_steps(session, *, max_decisions=10000):
    resources = game_text()
    context = controller_context(session)
    housekeeping = 0
    while session.decisions < max_decisions:
        if session.recorder:
            session.recorder.check()
        session.game.rpc('pause')
        session.publish('paused')
        observation, dialog = observe_ready(session, resources)
        session.journal.append('screen_observed', screen=observation['sha256'],
                                classification=dialog['kind'],supported=dialog['supported'],
                                path=Path(observation['path']).relative_to(session.journal.directory).as_posix(),
                                **({'native_rejection':dialog['native_rejection']} if dialog.get('native_rejection') else {}))
        if not dialog['supported']:
            return {'status':'paused','reason':'Original screen requires a controller update.',
                    'screen':observation['path'],'classification':dialog}
        kind = dialog['kind']
        pending = context['pending_empire']
        expected = {'open_tax':{'tax_rate','luxury_rate'},
                    'open_research':{'science_advisor'},
                    'open_diplomacy':{'foreign_minister'},
                    'open_revolution':{'revolution_choice','revolution_offer'}}
        if pending and kind in expected.get(pending['id'],set()):
            context['pending_empire_confirmed'] = True
        if kind in ('victory','game_over'):
            return {'status':'paused','reason':'Original end-game screen awaits outcome verification.',
                    'screen':observation['path'],'classification':dialog}
        if dialog['mechanical_action'] in ('acknowledge_information','accept_observed_default_name'):
            housekeeping += 1
            if housekeeping > 20:
                raise RuntimeError('Repeated information screens need inspection')
            if kind == 'new_city_name':
                context['observed_city_names'].add(dialog['default_name'])
            if kind == 'rule_rejection':
                session.note_native_rejection(dialog)
            session.mechanical(dialog['mechanical_action'])
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
            session.checkpoint()
            if context['reviewed']['turn'] != session.state['turn']:
                context['reviewed'] = {'turn':session.state['turn'],'actions':[]}
                context['production_reviewed'].clear()
            elif context['pending_empire']:
                if not context['pending_empire_confirmed']:
                    return {'status':'paused','reason':'Requested empire menu did not have an observed successful review.', 'screen':observation['path']}
                context['reviewed']['actions'].append(context['pending_empire']['id'])
            context['pending_empire'] = None
            observation, dialog = observe_ready(session, resources)
            if dialog['kind'] != 'end_turn' or not dialog['supported']:
                return {'status':'paused','reason':'End-turn checkpoint changed the observed screen.', 'screen':observation['path']}
            action,next_screen = session.choose_empire(dialog,context['reviewed'])
            if action['id'] != 'finish_turn':
                context['pending_empire'] = action
                context['pending_empire_confirmed'] = False
                context['pending_city'] = action['parameters'].get('target_city')
            elif classify_dialog(next_screen,rules=session.rules,game_text=resources,state=classification_state(session))['kind'] == 'end_turn':
                return {'status':'paused','reason':'End-turn input had no confirmed transition.', 'screen':next_screen['path']}
            continue
        if kind == 'city_locator' and context['pending_city']:
            matches = [option for option in dialog['options']
                       if option['text'].casefold() == context['pending_city']['name'].casefold()]
            if len(matches) != 1:
                return {'status':'paused','reason':'Selected city is not uniquely present in the native locator.', 'screen':observation['path']}
            session.game.rpc('resume')
            receipt = session.ui.select_text(observation,matches[0]['text'],exact=True)
            selected = session.ui.observe()
            selected_dialog = classify_dialog(selected,rules=session.rules,game_text=resources,state=classification_state(session))
            if selected_dialog['kind'] != 'city_locator' or not selected_dialog['supported']:
                return {'status':'paused','reason':'Native city locator changed during selection.', 'screen':selected['path']}
            zoom = [button for button in selected_dialog['buttons'] if button['text'].casefold() == 'zoom to city']
            if len(zoom) != 1:
                return {'status':'paused','reason':'Native Zoom To City control is not uniquely observed.', 'screen':selected['path']}
            zoom_receipt = session.ui.select_text(selected,zoom[0]['text'],exact=True)
            session.journal.append('navigate_selected_city',city=context['pending_city'],receipt=receipt,zoom_receipt=zoom_receipt)
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
            session.choose_dialog(dialog)
            if kind == 'production_choice':
                if context['active_city'] is not None:
                    context['production_reviewed'].add(context['active_city'])
            housekeeping = 0
            continue
        return {'status':'paused','reason':'Original game screen requires inspection.', 'screen':observation['path']}
    return {'status':'paused','reason':'Development decision checkpoint reached.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initial-save', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--env-file')
    parser.add_argument('--max-decisions', type=int, default=10000)
    parser.add_argument('--max-requests', type=int, default=20000)
    parser.add_argument('--fps',type=int,default=4)
    args = parser.parse_args()
    session = Session(args.directory,args.initial_save,env_file=args.env_file,
                      max_requests=args.max_requests,fps=args.fps)
    outcome = None
    try:
        outcome = run_steps(session,max_decisions=args.max_decisions)
        print(json.dumps(outcome))
    finally:
        session.finish(status='paused',reason=(outcome or {}).get('reason','Controller stopped; inspect local evidence.'))


if __name__ == '__main__':
    main()
