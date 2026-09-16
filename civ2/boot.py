"""Enter the requested new-game settings through the original Civilization II UI."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time
import zipfile
from .engine import Game
from .save import parse_save
from .revision import observation_digest, prefixed_revision
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


def _image_references(value):
    found=set()
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ('before','after','opening','selected_frame','verified_image') and isinstance(item,str) and re.fullmatch('[a-f0-9]{64}',item):
                found.add(item)
            if key=='image_sha256' and isinstance(item,list):
                found.update(digest for digest in item if isinstance(digest,str) and re.fullmatch('[a-f0-9]{64}',digest))
            found.update(_image_references(item))
    elif isinstance(value,list):
        for item in value:found.update(_image_references(item))
    return found


def _setup_images(directory, report):
    expected=_image_references(report);found={};seen=set()
    required=set(report.get('observation_receipt',{}).get('source_images',[]))
    for path in sorted(Path(directory).glob('*.png')):
        data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
        if digest in expected and (digest not in seen or path.name in required):
            found[path.name]={'path':path.name,'bytes':len(data),'sha256':digest}
            seen.add(digest)
    if expected-seen or required-set(found):raise RuntimeError('An original setup image is missing')
    return list(found.values())


def load_setup_report(directory, *, require_no_saves=False):
    """Return setup evidence whose relative artifacts remain intact on disk.

    Consumers still independently verify the original pixels and snapshot. This
    validates packaging and the explicit selected backend before copying it into
    a campaign journal; it does not upgrade a receipt into visual proof.
    """
    directory=Path(directory).resolve()
    report=json.loads((directory/'setup.json').read_text())
    if not isinstance(report,dict) or not isinstance(report.get('images'),list):
        raise ValueError('Setup report has no image evidence manifest')
    references=_image_references(report);seen=set()
    descriptors=list(report['images'])
    if report.get('observation_kind')=='live_memory':
        descriptors.append(report.get('initial_observation'))
    for item in descriptors:
        if not isinstance(item,dict) or set(item)!={'path','bytes','sha256'}:
            raise ValueError('Invalid setup artifact descriptor')
        path=Path(item['path']) if isinstance(item['path'],str) else None
        if path is None or path.is_absolute() or len(path.parts)!=1 or path.name in ('.','..'):
            raise ValueError('Setup artifact must remain inside its setup directory')
        target=(directory/path).resolve()
        if target.parent!=directory or type(item['bytes']) is not int or not 0<item['bytes']<=16_000_000:
            raise ValueError('Invalid setup artifact bounds')
        data=target.read_bytes()
        if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise ValueError('Setup artifact hash or length changed')
        if path.suffix=='.png':seen.add(item['sha256'])
    if references!=seen:raise ValueError('Setup image manifest differs from actual receipt references')
    image_paths={item['path'] for item in report['images']}
    if not set(report.get('observation_receipt',{}).get('source_images',[])).issubset(image_paths):
        raise ValueError('Initial observer image is missing from setup evidence')
    if require_no_saves:
        preferences=report.get('preferences',{})
        if (report.get('save_policy')!='no_saves_during_playthrough' or report.get('observation_kind')!='live_memory'
                or 'save_receipt' in report or 'initial_save_sha256' in report
                or preferences.get('autosave_disabled') is not True
                or preferences.get('checkbox_after',{}).get('Autosave each turn') is not False):
            raise ValueError('Setup did not establish the no-save route and disabled native autosave')
        from .preferences import GAME_LABELS
        before,after=preferences.get('checkbox_before'),preferences.get('checkbox_after')
        wanted={'Always wait at end of turn':True,'Instant advice':False,'Autosave each turn':False}
        if (not isinstance(before,dict) or not isinstance(after,dict)
                or set(before)!=set(GAME_LABELS) or set(after)!=set(GAME_LABELS)
                or any(type(v) is not bool for v in (*before.values(),*after.values()))
                or any(after[label]!=wanted.get(label,before[label]) for label in GAME_LABELS)
                or preferences.get('other_checkboxes_unchanged') is not True):
            raise ValueError('Setup game-option readback is incomplete or changed an unrelated preference')
        changes=preferences.get('changes')
        if (not isinstance(changes,list) or len(changes)!=3
                or {change.get('label') for change in changes if isinstance(change,dict)}!=set(wanted)
                or any(change.get('before') is not before[change['label']]
                       or change.get('after') is not wanted[change['label']]
                       or change.get('verified_image') not in seen for change in changes)):
            raise ValueError('Setup game-option receipts do not bind all three intended preferences')
        from .memory import parse_memory
        initial=report['initial_observation']
        data=(directory/initial['path']).read_bytes()
        # Audit structural native facts without requiring proprietary runtime
        # assets. Optional display names from RULES.TXT are not identity proof.
        state=parse_memory(data)
        campaign=report.get('campaign_start')
        capsule=json.loads(data)
        preferences_digest=hashlib.sha256(json.dumps(preferences,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if (not isinstance(campaign,dict) or capsule.get('proof',{}).get('campaign_start')!=campaign
                or report.get('observation_receipt',{}).get('campaign_start')!=campaign
                or campaign.get('preferences_sha256')!=preferences_digest):
            raise ValueError('Setup preferences do not bind the original campaign inventory boundary')
        structural_player=lambda player:{key:value for key,value in player.items()
            if key not in ('leader','tribe','known_technologies')}
        if (report.get('checks')!=verify_setup(state)
                or report.get('settings')!=state['settings']
                or not isinstance(report.get('player'),dict)
                or structural_player(report['player'])!=structural_player(state['player'])
                or report.get('map_dimensions')!=[state['map']['width'],state['map']['height']]
                or report.get('initial_observation_sha256')!=observation_digest(state)
                or initial['sha256']!=observation_digest(state)):
            raise ValueError('Setup report claims differ from its initial live snapshot')
    return report


def new_game(ui, *, from_startup=True, checkpoint='initial.sav', observer=None):
    """Create one original random map and verify it using the selected observer.

    Passing a read-only observer prohibits even the initial native Save command.
    The captured initial-observation.json is a host evidence artifact, not a game
    save. Legacy debugging without an observer retains its original save route.
    """
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
            'method':('keyboard from original startup defaults; read-only observation must verify all settings'
                      if observer is not None else
                      'keyboard from original startup defaults; native save must verify all settings')})
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
    from .preferences import configure_preferences
    preferences = configure_preferences(ui)
    if observer is None:
        data, save_receipt = ui.save_native(checkpoint)
        output = ui.directory / checkpoint
        output.write_bytes(data)
        state = parse_save(data, rules_text=original_rules())
        provenance = {'save_receipt':save_receipt,
                      'initial_save_sha256':state['evidence']['save_sha256']}
    else:
        if (preferences.get('autosave_disabled') is not True
                or preferences.get('checkbox_after',{}).get('Autosave each turn') is not False):
            raise RuntimeError('No-save setup requires verified original autosave disabling')
        campaign_start=observer.begin_campaign(preferences)
        if not isinstance(campaign_start,dict):
            raise ValueError('Observer did not declare the post-setup campaign inventory')
        result = observer.read(rules_text=original_rules())
        if not isinstance(result,dict) or set(result)!={'state','data','receipt'}:
            raise ValueError('Invalid live setup observation')
        state,data,receipt = result['state'],result['data'],result['receipt']
        if (not isinstance(state,dict) or not isinstance(data,bytes) or not isinstance(receipt,dict)
                or state.get('evidence',{}).get('kind')!='live_memory'
                or observation_digest(state)!=hashlib.sha256(data).hexdigest()):
            raise ValueError('Initial live observation is not bound to its recorded snapshot')
        if receipt.get('campaign_start')!=campaign_start or receipt.get('proof',{}).get('campaign_start')!=campaign_start:
            raise ValueError('Initial observation does not bind the declared post-setup inventory')
        receipt=deepcopy(receipt)
        image_paths=receipt.get('source_images')
        image_hashes=receipt.get('proof',{}).get('image_sha256')
        if not isinstance(image_paths,list) or not isinstance(image_hashes,list) or len(image_paths)!=3 or len(image_hashes)!=3:
            raise ValueError('Initial observer requires three bound original frame images')
        copied=[]
        for index,(source,digest) in enumerate(zip(image_paths,image_hashes)):
            frame=Path(source).read_bytes()
            if not frame.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(frame).hexdigest()!=digest:
                raise ValueError('Initial observer image differs from its recorded proof')
            name=f'initial-observer-{index}.png'
            (ui.directory/name).write_bytes(frame)
            copied.append(name)
        receipt['source_images']=copied
        output = ui.directory / 'initial-observation.json'
        output.write_bytes(data)
        provenance = {'observation_kind':'live_memory','save_policy':'no_saves_during_playthrough',
                      'initial_observation':{'path':output.name,'bytes':len(data),
                                             'sha256':observation_digest(state)},
                      'observation_receipt':receipt,'campaign_start':campaign_start,
                      **prefixed_revision(state,'initial_')}
    checks = verify_setup(state)
    report={'checks': checks, 'receipts': receipts,
        **provenance, 'preferences':preferences,
        'settings': state['settings'], 'player': state['player'], 'map_dimensions':
        [state['map']['width'], state['map']['height']]}
    report['images']=_setup_images(ui.directory,report)
    (ui.directory / 'setup.json').write_text(json.dumps(report, indent=2))
    ui.game.rpc('pause')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default='.runtime/setup')
    parser.add_argument('--profile', default='campaign-01')
    parser.add_argument('--port',type=int,default=3920)
    parser.add_argument('--no-saves',action='store_true',
                        help='Verify setup through the read-only native observer; issue no game Save command')
    args = parser.parse_args()
    game = Game(port=args.port)
    if not game.rpc('status')['started']:
        game.rpc('boot', {'profile': args.profile, 'observer':args.no_saves})
    observer = None
    if args.no_saves:
        from .memory import LiveMemoryObserver
        observer = LiveMemoryObserver(game, Path(args.directory)/'observer')
    state = new_game(UI(game, args.directory), observer=observer)
    print(json.dumps({'settings':state['settings'],'turn':state['turn'],'year':state['year_raw'],
                      'map_dimensions':[state['map']['width'],state['map']['height']],
                      'player':state['player']['leader']}))

if __name__ == '__main__':
    main()
