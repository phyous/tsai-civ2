"""Enter the requested new-game settings through the original Civilization II UI."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import zipfile
from .engine import Game
from .save import parse_save
from .ui import UI


def original_rules():
    bundle = Path(__file__).resolve().parents[1] / 'engine/game/civ2-win31.zip'
    with zipfile.ZipFile(bundle) as archive:
        names = [n for n in archive.namelist() if n.lower() == 'civ2/rules.txt']
        if len(names) != 1:
            raise RuntimeError('Expected one original rules file')
        return archive.read(names[0]).decode('cp1252')


def verify_setup(state):
    settings = state['settings']
    checks = {
        'Prince': settings['difficulty'] == 'Prince',
        'Restless Tribes': settings['barbarians'] == 'Restless Tribes',
        'five civilizations': settings['starting_civilizations'] == 5,
        'small map': state['map']['width'] == 40 and state['map']['height'] == 50
                     and state['map']['coordinate_width'] == 80,
        'standard rules': not settings['bloodlust'] and not settings['simplified_combat']
                          and settings['restart_eliminated'] and settings['round_world']
                          and not settings['scenario'],
        'male Rome': state['player']['tribe_id'] == 0 and state['player']['gender'] == 'male',
        'untouched start': state['turn'] == 1 and state['year_raw'] == -4000 and not state['cities'],
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError('Original save does not match requested setup: ' + ', '.join(failed))
    return checks


def new_game(ui, *, from_startup=True, checkpoint='initial.sav'):
    receipts = []
    if from_startup:
        observation = ui.wait(lambda o: 'CD-ROM' in o['text'] or 'Start a New Game' in o['text'], timeout=80)
        if 'CD-ROM' in observation['text']:
            ui.key('Enter', settle=.5)  # Original supported non-CD gameplay option.
        observation = ui.wait_text('Start a New Game', timeout=30)
    else:
        raise ValueError('Start a fresh emulator profile before creating a new game')
    receipts.append({'target':'Start a New Game','inputs':ui.key('Enter'),
                     'before':observation['sha256'],'method':'original default startup selection'})
    sequence = [
        ('Small (', 'Small', ['ArrowUp']),
        ('Prince', 'Prince', ['ArrowDown','ArrowDown']),
        ('5 Civilizations', '5 Civilizations', ['ArrowDown','ArrowDown']),
        ('Restless Tribes', 'Restless Tribes', []),
        ('Use Standard Rules', 'Use Standard Rules', []),
        ('Female', 'Male', []),
        ('Romans', 'Romans', []),
    ]
    for screen, choice, keys in sequence:
        observation = ui.wait_text(screen, timeout=15)
        inputs = []
        for key in keys:
            inputs += ui.key(key)
        selected = ui.observe()
        inputs += ui.key('Enter')
        receipts.append({'target':choice,'before':observation['sha256'],
            'selected_frame':selected['sha256'],'inputs':inputs,
            'method':'keyboard from original startup defaults; native save must verify all settings'})
    ui.wait(lambda o: 'Caesar' in o['text'] and 'Name:' in o['text'])
    ui.key('Enter')  # Keep the original male Roman leader name, Caesar.
    observation = ui.wait_text('Classical Forum')
    receipts.append({'target':'original Roman city style','before':observation['sha256'],
                     'inputs':ui.key('Enter')})
    observation = ui.wait_text('In the Beginning', timeout=80)
    ui.key('Enter')
    # The bundled game enables informational tutorial tips, even in a new game.
    for _ in range(8):
        time.sleep(.3)
        observation = ui.observe()
        if ui.acknowledge_information(observation):
            continue
        if 'moving' in observation['text'].casefold() or 'moves:' in observation['text'].casefold():
            break
    data, save_receipt = ui.save_native(checkpoint)
    output = ui.directory / checkpoint
    output.write_bytes(data)
    state = parse_save(data, rules_text=original_rules())
    checks = verify_setup(state)
    (ui.directory / 'setup.json').write_text(json.dumps({'checks': checks, 'receipts': receipts,
        'save_receipt': save_receipt, 'initial_save_sha256': state['evidence']['save_sha256'],
        'settings': state['settings'], 'player': state['player'], 'map_dimensions':
        [state['map']['width'], state['map']['height']]}, indent=2))
    ui.game.rpc('pause')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default='.runtime/setup')
    parser.add_argument('--profile', default='campaign-01')
    args = parser.parse_args()
    game = Game()
    if not game.rpc('status')['started']:
        game.rpc('boot', {'profile': args.profile})
    state = new_game(UI(game, args.directory))
    print(json.dumps({'settings':state['settings'],'turn':state['turn'],'year':state['year_raw'],
                      'map_dimensions':[state['map']['width'],state['map']['height']],
                      'player':state['player']['leader']}))

if __name__ == '__main__':
    main()
