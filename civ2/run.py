"""Run observed native-game decisions; pause on a screen requiring new support."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import zipfile
from .dialogs import classify_dialog
from .session import Session


def game_text():
    bundle = Path(__file__).resolve().parents[1]/'engine/game/civ2-win31.zip'
    with zipfile.ZipFile(bundle) as source:
        return source.read('civ2/GAME.TXT').decode('cp1252')


def run_steps(session, *, max_decisions=10000):
    resources = game_text()
    production_reviewed = False
    housekeeping = 0
    reviewed = {'turn':session.state['turn'],'actions':[]}
    pending_empire = None
    pending_city = None
    while session.decisions < max_decisions:
        if session.recorder:
            session.recorder.check()
        session.game.rpc('pause')
        observation = session.ui.observe()
        dialog = classify_dialog(observation, rules=session.rules, game_text=resources, state=session.state)
        session.journal.append('screen_observed', screen=observation['sha256'],
                                classification=dialog['kind'],supported=dialog['supported'],
                                path=Path(observation['path']).relative_to(session.journal.directory).as_posix())
        if not dialog['supported']:
            return {'status':'paused','reason':'Original screen requires a controller update.',
                    'screen':observation['path'],'classification':dialog}
        kind = dialog['kind']
        if kind in ('victory','game_over'):
            return {'status':'paused','reason':'Original end-game screen awaits outcome verification.',
                    'screen':observation['path'],'classification':dialog}
        if dialog['mechanical_action'] in ('acknowledge_information','accept_observed_default_name'):
            housekeeping += 1
            if housekeeping > 20:
                raise RuntimeError('Repeated information screens need inspection')
            session.mechanical(dialog['mechanical_action'])
            continue
        if kind == 'city_screen':
            session.city_report = {'source_image':observation['sha256'],'text':observation['text']}
            # Opening the native production menu exposes the strategic choices;
            # only Jev picks what the city will actually build.
            label = 'Exit' if production_reviewed else 'Change'
            matches = [b for b in dialog['buttons'] if b['text'].casefold() == label.casefold()]
            if len(matches) != 1:
                return {'status':'paused','reason':'City control was not uniquely observed.', 'screen':observation['path']}
            session.game.rpc('resume')
            receipt = session.ui.select_text(observation, matches[0]['text'], exact=True)
            session.journal.append('open_city_control', target=label, receipt=receipt)
            time.sleep(.3)
            continue
        if kind == 'end_turn':
            session.checkpoint()
            if reviewed['turn'] != session.state['turn']:
                reviewed = {'turn':session.state['turn'],'actions':[]}
            elif pending_empire:
                reviewed['actions'].append(pending_empire['id'])
            pending_empire = None
            observation = session.ui.observe()
            dialog = classify_dialog(observation,rules=session.rules,game_text=resources,state=session.state)
            if dialog['kind'] != 'end_turn' or not dialog['supported']:
                return {'status':'paused','reason':'End-turn checkpoint changed the observed screen.', 'screen':observation['path']}
            action,next_screen = session.choose_empire(dialog,reviewed)
            if action['id'] != 'finish_turn':
                pending_empire = action
                pending_city = action['parameters'].get('target_city')
            elif classify_dialog(next_screen,rules=session.rules,game_text=resources,state=session.state)['kind'] == 'end_turn':
                return {'status':'paused','reason':'End-turn input had no confirmed transition.', 'screen':next_screen['path']}
            continue
        if kind == 'city_locator' and pending_city:
            matches = [option for option in dialog['options']
                       if option['text'].casefold() == pending_city['name'].casefold()]
            if len(matches) != 1:
                return {'status':'paused','reason':'Selected city is not uniquely present in the native locator.', 'screen':observation['path']}
            session.game.rpc('resume')
            receipt = session.ui.select_text(observation,matches[0]['text'],exact=True,confirm=True)
            session.journal.append('navigate_selected_city',city=pending_city,receipt=receipt)
            pending_city = None
            continue
        if kind == 'normal_map':
            housekeeping = 0
            production_reviewed = False
            session.checkpoint()
            session.choose_unit()
            continue
        if dialog['requires_model']:
            if len(dialog['options']) == 1:
                return {'status':'paused','reason':'A forced choice needs a verified mechanical handler.', 'screen':observation['path']}
            session.choose_dialog(dialog)
            if kind == 'production_choice':
                production_reviewed = True
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
