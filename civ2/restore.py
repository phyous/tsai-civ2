"""Restore a verified untouched start through a fresh original-game instance.

Only setup/load/preferences/save inputs are issued. No model, turn, unit order,
recording, guessed modal dismissal or overwriting an existing guest save occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

from .boot import original_rules, verify_setup
from .engine import Game
from .preferences import configure_preferences
from .save import parse_save
from .ui import UI


GAMEPLAY_FIELDS = ('turn','year_raw','selected_unit_id','player','units','cities',
                   'visible_units','known_cities','diplomacy','wonders','map')


def _normal(text):
    return re.sub(r'[^a-z0-9]', '', text.casefold())


def _startup(observation):
    labels = {row['text'].strip().casefold() for row in observation['lines']}
    return {'start a new game','load a game'} <= labels


def _cd_notice(observation):
    text = observation['text'].casefold()
    return 'cd-rom' in text and 'civilization' in text and 'repeat search' in text


def _load_confirmation(observation, leader):
    text = _normal(observation['text'])
    labels = {row['text'].strip().casefold() for row in observation['lines']}
    return ('prince' in text and '4000bc' in text
            and _normal(leader+' of the Romans') in text and 'ok' in labels)


def _wait_startup(ui, timeout=80):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        # DOS startup is 640x400 and may put OCR glyphs on an image boundary.
        # Wait without input until the original Windows startup dialog appears.
        if ui.game.rpc('status').get('height') != 480:
            time.sleep(.25)
            continue
        try:
            observation = ui.observe()
        except ValueError as error:
            if str(error) != 'Invalid normalized OCR geometry':
                raise
            time.sleep(.25)
            continue
        if _startup(observation) or _cd_notice(observation):
            return observation
        time.sleep(.25)
    raise RuntimeError('Original startup dialog did not appear; no input sent')


def restore_start(ui, source_save, *, profile, guest_name='restore.sav',
                  checkpoint='initial.sav', rules_text=None):
    """Return (state, setup_report), leaving the separate instance paused.

    The caller must reload/create its own browser tab first. A fresh profile and
    empty UI artifact directory prevent accidental continuation or overwrites.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', profile):
        raise ValueError('A simple isolated runtime profile is required')
    if any(not re.fullmatch(r'[A-Za-z0-9_]{1,8}\.sav', name, re.I) for name in (guest_name,checkpoint)):
        raise ValueError('Use ordinary DOS 8.3 save filenames')
    if guest_name.casefold() == checkpoint.casefold():
        raise ValueError('Imported start and native checkpoint need distinct filenames')
    if any(ui.directory.iterdir()):
        raise ValueError('Restore requires a new empty UI artifact directory')
    data = Path(source_save).read_bytes()
    rules_text = original_rules() if rules_text is None else rules_text
    source = parse_save(data, rules_text=rules_text)
    verify_setup(source)
    if ui.game.rpc('status').get('started'):
        raise RuntimeError('Reload the isolated runtime tab before restoring a fresh start')
    report = {'profile':profile,'source_save_sha256':hashlib.sha256(data).hexdigest(),
              'receipts':[],'strategic_inputs':False,'model_calls':0}
    try:
        ui.game.rpc('boot', {'profile':profile})
        observation = _wait_startup(ui)
        if _cd_notice(observation):
            report['receipts'].append({'label':'original non-CD multimedia notice',
                'before':observation['sha256'],'inputs':ui.key('Enter',settle=1.2)})
            observation = ui.wait(_startup,timeout=30)
        report['import'] = ui.game.import_save(guest_name,data)
        report['receipts'].append({'label':'refresh DOSBox mounted-file cache',
            'inputs':ui.game.chord('ControlLeft','F4',hold_ms=120)})
        observation = ui.observe()
        if not _startup(observation):
            raise RuntimeError('Original startup menu changed before Load a Game')
        report['receipts'].append({'label':'Load a Game',
            'receipt':ui.select_text(observation,'Load a Game',exact=True,confirm=True)})
        load = ui.wait_text('Select Game To Load',timeout=20)
        # The original file dialog opens with its *.sav edit text selected.
        # Reset selection explicitly using its observed File Name edit context.
        if not any(_normal(row['text']) == 'filename' for row in load['lines']):
            raise RuntimeError('Original load filename field was not observed')
        inputs = ui.key('Home',settle=.05)
        inputs += ui.game.chord('ShiftLeft','End',hold_ms=80)
        inputs += ui.game.type_text(guest_name)
        typed = ui.observe()
        inputs += ui.key('Enter',settle=1.2)
        confirmed = ui.wait(lambda o:_load_confirmation(o,source['player']['leader']),timeout=20)
        report['receipts'].append({'label':'load verified untouched save',
            'before':load['sha256'],'typed':typed['sha256'],'confirmation':confirmed['sha256'],'inputs':inputs})
        report['receipts'].append({'label':'acknowledge original load confirmation',
            'before':confirmed['sha256'],'inputs':ui.key('Enter',settle=1.2)})
        report['preferences'] = configure_preferences(ui)
        native, receipt = ui.save_native(checkpoint)
        ui.game.rpc('pause')
        state = parse_save(native,rules_text=rules_text)
        report['checks'] = verify_setup(state)
        unchanged = {key:source[key] == state[key] for key in GAMEPLAY_FIELDS}
        report['unchanged_gameplay_fields'] = unchanged
        if not all(unchanged.values()):
            raise RuntimeError('Gameplay state changed during native setup restoration')
        report['initial_save_sha256'] = hashlib.sha256(native).hexdigest()
        report['save_receipt'] = receipt
        (ui.directory/checkpoint).write_bytes(native)
        ui.game.capture(ui.directory/'ready.png')
        report['ready'] = True
        (ui.directory/'setup.json').write_text(json.dumps(report,indent=2)+'\n')
        return state,report
    except Exception as error:
        # Preserve the original failure screen; never guess a dismissal or retry
        # an input whose native effect is unknown.
        try:
            ui.game.rpc('pause')
            ui.game.capture(ui.directory/'restore-failed.png')
        except Exception:
            pass
        report.update(ready=False,error_type=type(error).__name__)
        (ui.directory/'setup-failed.json').write_text(json.dumps(report,indent=2)+'\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--profile',required=True)
    parser.add_argument('--source-save',required=True)
    parser.add_argument('--directory',required=True)
    args = parser.parse_args()
    state,report = restore_start(UI(Game(port=args.port),args.directory),
        args.source_save,profile=args.profile)
    print(json.dumps({'ready':report['ready'],'checks':report['checks'],
        'turn':state['turn'],'cities':len(state['cities']),
        'initial_save_sha256':report['initial_save_sha256']}))


if __name__=='__main__':
    main()
