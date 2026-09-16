"""Offline integrity checks for a local original-Civ-II evidence directory.

No emulator, network, credential, OCR, or game-control calls occur here. A valid
local hash chain is not an independent attestation of how its data was created.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess

from .boot import verify_setup
from .evidence import canonical
from .save import parse_save
from .typesafe import _validate_questions, validate_response


class VerificationError(ValueError):
    """Messages are fixed diagnostics, never raw evidence or remote output."""


SHA = re.compile(r'[0-9a-f]{64}')
SCREEN_KEYS = {'screen', 'before', 'after', 'dialog', 'typed', 'saved',
               'selected_frame', 'source_image', 'image_sha256'}
DISPATCHES = {'command_dispatched': 'unit_action', 'dialog_dispatched': 'dialog_action',
              'empire_command_dispatched': 'empire_action'}
KNOWN_EVENTS = {'begin', 'checkpoint', 'inference_started', 'model_decision',
                'screen_observed', 'mechanical_input', 'open_city_control',
                'navigate_selected_city', 'batch_observed_effect',
                'forced_empire_command', 'session_stopped', 'recording_finalized',
                'dialog_keyboard_recovery',
                'model_plan', 'plan_status',
                *DISPATCHES}


def _require(condition, message):
    if not condition:
        raise VerificationError(message)


def _int(value, minimum=0):
    return type(value) is int and value >= minimum


def _sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        _require(key not in out, 'Duplicate JSON key in evidence')
        out[key] = value
    return out


def _loads(data):
    try:
        return json.loads(data, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise VerificationError('Invalid JSON evidence') from None


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class Files:
    def __init__(self, root):
        self.root = Path(root).resolve()
        _require(self.root.is_dir(), 'Evidence directory is missing')
        self.checked = {}
        self.screens = {}

    def path(self, name):
        _require(isinstance(name, str) and name and '\\' not in name,
                 'Artifact path is invalid')
        relative = PurePosixPath(name)
        _require(not relative.is_absolute() and '..' not in relative.parts
                 and str(relative) == name, 'Artifact path is not a confined relative path')
        path = (self.root / name).resolve()
        _require(path.is_relative_to(self.root) and path.is_file(),
                 'Referenced artifact is missing or escapes the evidence directory')
        return path

    def inspect(self, name, digest=None, size=None):
        path = self.path(name)
        actual = {'path': name, 'sha256': _hash(path), 'bytes': path.stat().st_size}
        if digest is not None:
            _require(_sha(digest) and actual['sha256'] == digest, 'Referenced artifact SHA-256 differs')
        if size is not None:
            _require(_int(size) and actual['bytes'] == size, 'Referenced artifact byte count differs')
        self.checked[name] = actual
        return actual

    def descriptor(self, descriptor):
        _require(isinstance(descriptor, dict) and {'path', 'sha256'} <= descriptor.keys(),
                 'Artifact descriptor is incomplete')
        return self.inspect(descriptor['path'], descriptor['sha256'], descriptor.get('bytes'))

    def json(self, name):
        return _loads(self.path(name).read_bytes())

    def screen(self, digest):
        _require(_sha(digest), 'Image reference is not a SHA-256')
        if digest not in self.screens:
            folder = self.root / 'screens'
            if folder.is_dir():
                for candidate in folder.rglob('*.png'):
                    name = candidate.relative_to(self.root).as_posix()
                    path = self.path(name)  # Reject symlinks outside the run.
                    self.screens[_hash(path)] = name
        _require(digest in self.screens, 'A referenced original screenshot is missing')
        name = self.screens[digest]
        self.inspect(name, digest)
        return name

    def references(self, value):
        if isinstance(value, list):
            for child in value:
                self.references(child)
        elif isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                self.descriptor(value)
            if 'path' in value and 'screen' in value:
                info = self.inspect(value['path'], value['screen'])
                self.screens[info['sha256']] = info['path']
            for key, child in value.items():
                if key in SCREEN_KEYS and isinstance(child, str) and _sha(child):
                    self.screen(child)
                self.references(child)


def _journal(files):
    path = files.path('events.jsonl')
    events, previous, elapsed = [], '0' * 64, -1
    with path.open(encoding='utf-8') as source:
        for line in source:
            record = _loads(line)
            _require(isinstance(record, dict) and set(record) ==
                     {'sequence', 'elapsed_ms', 'kind', 'previous_sha256', 'payload', 'sha256'},
                     'Journal event schema is invalid')
            digest = record['sha256']
            event = {k: v for k, v in record.items() if k != 'sha256'}
            _require(_int(record['sequence'], 1) and record['sequence'] == len(events)+1
                     and _int(record['elapsed_ms']) and record['elapsed_ms'] >= elapsed
                     and record['previous_sha256'] == previous and _sha(digest)
                     and hashlib.sha256(canonical(event)).hexdigest() == digest,
                     'Journal hash chain or sequence is invalid')
            _require(isinstance(record['kind'], str) and isinstance(record['payload'], dict),
                     'Journal payload is invalid')
            previous, elapsed = digest, record['elapsed_ms']
            events.append(record)
    _require(events and events[0]['kind'] == 'begin', 'Journal must start with one begin event')
    _require(sum(e['kind'] == 'begin' for e in events) == 1, 'Journal has multiple begin events')
    files.inspect('events.jsonl')
    return events, {'events': len(events), 'last_sha256': previous, 'duration_ms': elapsed}


def _inputs(value):
    """Flatten only recorded ordinary inputs; visual cursor wrappers are checked."""
    _require(isinstance(value, list) and value, 'Dispatch has no ordinary input receipt')
    result = []
    for row in value:
        if isinstance(row, list):
            result.extend(_inputs(row))
            continue
        _require(isinstance(row, dict), 'Input receipt is malformed')
        if 'inputs' in row:
            _require(row.get('issued') is True and isinstance(row.get('target'), list)
                     and len(row['target']) == 2, 'Cursor receipt did not confirm an issued target')
            cursor, target, tolerance = row.get('observed_cursor'), row['target'], row.get('tolerance')
            _require(isinstance(cursor, list) and len(cursor) == 2
                     and all(_int(v) for v in cursor+target) and _int(tolerance)
                     and tolerance <= 4 and max(abs(a-b) for a, b in zip(cursor, target)) <= tolerance,
                     'Cursor target was not acknowledged within its recorded tolerance')
            result.extend(_inputs(row['inputs']))
            continue
        kind = row.get('type')
        _require(_int(row.get('sequence'), 1), 'Input receipt sequence is missing')
        if kind == 'key':
            _require(isinstance(row.get('code'), str) and type(row.get('down')) is bool
                     and row.get('repeat') is False, 'Keyboard receipt is invalid or repeated')
        elif kind == 'mouse':
            _require(row.get('event') in ('mousemove', 'mousedown', 'mouseup')
                     and _int(row.get('x')) and row['x'] < 640
                     and _int(row.get('y')) and row['y'] < 480
                     and type(row.get('button')) is int and row['button'] in (0, 1, 2),
                     'Mouse receipt is not an ordinary original-canvas event')
        elif kind == 'relativeMouse':
            # Retain earlier SDL receipts and accept only the current bridge's
            # original DOSBox relative host-input handler (not a guest write).
            backend_ok = (
                row.get('via') == 'SDL_SendMouseMotion' and row.get('queued') is True
                or row.get('via') == 'DOSBox Mouse_CursorMoved'
                and row.get('dispatched') is True and row.get('emulate') is True
            )
            _require(all(type(row.get(k)) is int and -32 <= row[k] <= 32 for k in ('dx', 'dy'))
                     and (row['dx'] or row['dy']) and backend_ok,
                     'Relative mouse receipt is invalid')
        else:
            raise VerificationError('Dispatch contains an unsupported input operation')
        result.append(row)
    _require(all(a['sequence'] < b['sequence'] for a, b in zip(result, result[1:])),
             'Input receipt sequence is not strictly increasing')
    held, buttons = set(), set()
    for row in result:
        if row['type'] == 'key':
            code = row['code']
            _require((code not in held) if row['down'] else (code in held),
                     'Keyboard receipt is not a balanced press/release')
            (held.add if row['down'] else held.remove)(code)
        if row['type'] == 'mouse' and row['event'] != 'mousemove':
            button = row['button']; down = row['event'] == 'mousedown'
            _require((button not in buttons) if down else (button in buttons),
                     'Mouse receipt is not a balanced press/release')
            (buttons.add if down else buttons.remove)(button)
    _require(not held and not buttons, 'Input receipt leaves a key or mouse button held')
    return result


def _action_binding(action, request, question, saves):
    _require(isinstance(action, dict) and set(action) ==
             {'id', 'kind', 'label', 'actor', 'preconditions', 'parameters'}, 'Selected action schema is invalid')
    pre, actor, params = action['preconditions'], action['actor'], action['parameters']
    _require(all(isinstance(v, dict) for v in (pre, actor, params)), 'Selected action binding is malformed')
    digest = pre.get('save_sha256')
    _require(digest in saves, 'Selected action does not reference an earlier native save')
    state = saves[digest]
    model = request.get('state')
    _require(isinstance(model, dict) and model.get('turn') == pre.get('turn') == state['turn'],
             'Selected action and request do not share the native save turn')
    labor_revision = model.get('city_labor', {}).get('revision')
    if labor_revision is not None:
        _require(labor_revision == {'turn': state['turn'], 'save_sha256': digest},
                 'Model observation revision differs from the bound native save')
    if question == 'unit_action':
        fields = ('id', 'type_id', 'owner', 'x', 'y')
        units = [u for u in state['units'] if u['id'] == actor.get('id')]
        _require(len(units) == 1 and all(actor.get(k) == units[0].get(k) for k in fields)
                 and actor['id'] == state['selected_unit_id'] == pre.get('selected_unit_id'),
                 'Unit actor differs from the selected owned unit in its native save')
        selected = model.get('selected_unit', {})
        _require(isinstance(selected, dict) and all(selected.get(k) == actor[k] for k in fields),
                 'Unit actor differs from the model observation')
        keys = {'skip': 'Space', 'fortify': 'KeyF', 'sentry': 'KeyS', 'settle': 'KeyB', 'unload': 'KeyU',
                'road': 'KeyR', 'railroad': 'KeyR', 'irrigate': 'KeyI', 'farmland': 'KeyI', 'mine': 'KeyM'}
        moves = {'n': (0, -2, 'Numpad8'), 'ne': (1, -1, 'Numpad9'), 'e': (2, 0, 'Numpad6'),
                 'se': (1, 1, 'Numpad3'), 's': (0, 2, 'Numpad2'), 'sw': (-1, 1, 'Numpad1'),
                 'w': (-2, 0, 'Numpad4'), 'nw': (-1, -1, 'Numpad7')}
        identifier = action['id']
        if identifier.startswith('move_') and identifier[5:] in moves:
            dx, dy, key = moves[identifier[5:]]
            x, y = actor['x']+dx, actor['y']+dy
            if state['settings']['round_world']:
                x %= state['map']['coordinate_width']
            _require(action['kind'] == 'move' and params.get('destination') == {'x': x, 'y': y}
                     and params.get('dx') == dx and params.get('dy') == dy, 'Move action destination differs from its ordinary key')
        else:
            key = keys.get(identifier)
        _require(key is not None and params.get('key') == key, 'Unit action is outside the implemented ordinary key mapping')
        if identifier == 'unload':
            # Standard 1.06 @UNITS rows in original RULES.TXT: Trireme,
            # Caravel, Galleon, Transport. Numeric rules avoid requiring private
            # game assets just to verify retained standard-rules evidence.
            capacity = {32:2, 33:3, 34:4, 43:8}.get(actor['type_id'])
            expected = {'id':actor['type_id'], 'domain':2, 'role':4,
                        'transport_capacity':capacity}
            declared = params.get('transport_specification')
            specification = selected.get('specification')
            _require(capacity is not None and action['kind'] == 'unload'
                     and isinstance(declared,dict) and set(declared) == set(expected)
                     and all(type(declared.get(k)) is int and declared[k] == v for k,v in expected.items())
                     and isinstance(specification,dict)
                     and all(type(specification.get(k)) is int and specification[k] == v for k,v in expected.items()),
                     'Unload action differs from its original naval transport specification')
    elif question == 'dialog_action':
        point = params.get('center'); index = params.get('option_index')
        _require(action['kind'] == 'dialog_choice' and _sha(pre.get('image_sha256'))
                 and pre.get('width') == 640 and pre.get('height') == 480
                 and isinstance(point, list) and len(point) == 2
                 and all(_int(v) for v in point) and point[0] < 640 and point[1] < 480
                 and _int(index) and action['id'] == 'option_'+str(index)
                 and params.get('observed_text') == action['label'], 'Dialog action has invalid observed option binding')
        dialog = model.get('mandatory_dialog', {})
        _require(dialog.get('title') == actor.get('title') and action['label'] in dialog.get('options', []),
                 'Dialog action differs from the model-observed native menu')
    elif question == 'empire_action':
        keys = {'finish_turn': ('Enter', []), 'open_tax': ('KeyT', ['ShiftLeft']),
                'open_research': ('F6', []), 'open_diplomacy': ('F3', []),
                'open_revolution': ('KeyR', ['ShiftLeft'])}
        key = keys.get(action['id'])
        if re.fullmatch(r'inspect_city_\d+', action['id']):
            key = ('KeyC', ['ShiftLeft'])
            target = params.get('target_city', {})
            _require(any(all(c.get(k) == target.get(k) == actor.get(k) for k in ('id', 'owner', 'name', 'x', 'y'))
                         for c in state['cities']), 'Empire city target differs from the owned save actor')
        _require(key is not None and (params.get('key'), params.get('modifiers')) == key
                 and pre.get('screen_kind') == 'end_turn' and _sha(pre.get('image_sha256')),
                 'Empire action is outside the observed End of Turn command mapping')
    else:
        raise VerificationError('Unsupported model dispatch question')


def _dispatch(payload, action, question, files):
    _require(payload.get('action') == action, 'Dispatched action differs from the selected model action')
    receipt = payload.get('receipt', payload)
    _require(isinstance(receipt, dict), 'Dispatch receipt is missing')
    before = receipt.get('before'); after = payload.get('after')
    files.screen(before); files.screen(after)
    inputs = _inputs(receipt.get('inputs'))
    params = action['parameters']
    keys = [(r['code'], r['down']) for r in inputs if r['type'] == 'key']
    if question in ('unit_action', 'empire_action'):
        if question == 'empire_action':
            _require(before == action['preconditions']['image_sha256'],
                     'Empire receipt does not start from its observed End of Turn image')
        modifiers = params.get('modifiers', [])
        expected = [(k, True) for k in modifiers] + [(params['key'], True), (params['key'], False)] + [(k, False) for k in reversed(modifiers)]
        _require(keys == expected and all(r['type'] == 'key' for r in inputs),
                 'Input receipt does not execute exactly the selected key command')
    else:
        _require(before == action['preconditions']['image_sha256']
                 and receipt.get('point') == params['center']
                 and receipt.get('target') == action['label'], 'Dialog receipt differs from its observed selected target')
        _require(keys in ([], [('Enter', True), ('Enter', False)]), 'Dialog dispatch contains unrelated keys')
        mouse = [r for r in inputs if r['type'] == 'mouse' and r['event'] != 'mousemove']
        _require([r['event'] for r in mouse] == ['mousedown', 'mouseup']
                 and all(r['button'] == 0 for r in mouse), 'Dialog dispatch must contain one ordinary left click')
        wrappers = [r for r in receipt['inputs'] if isinstance(r, dict) and 'inputs' in r]
        if wrappers:
            _require(len(wrappers) == 1 and wrappers[0]['target'] == params['center'],
                     'Cursor receipt targets a different dialog option')
        else:
            _require(all([r['x'], r['y']] == params['center'] for r in mouse),
                     'Direct mouse receipt differs from the selected option coordinates')
    return len(inputs)


def _plan_binding(task, request, saves):
    _require(isinstance(task, dict) and set(task) ==
             {'id','task','label','actor','preconditions','target'}, 'Planning candidate schema is invalid')
    pre, actor, target = task['preconditions'], task['actor'], task['target']
    _require(all(isinstance(v, dict) for v in (pre, actor, target)), 'Planning candidate binding is malformed')
    _require(pre.get('save_sha256') in saves, 'Plan does not reference an earlier native save')
    state = saves[pre['save_sha256']]
    model = request.get('state', {})
    _require(model.get('turn') == pre.get('turn') == state['turn'], 'Planning request and native save turns differ')
    units = [u for u in state['units'] if u['id'] == actor.get('id')]
    fields = ('id','owner','type_id','x','y','home_city_id','veteran')
    _require(set(actor) == set(fields) and len(units) == 1 and all(actor.get(k) == units[0].get(k) for k in fields)
             and actor['id'] == pre.get('selected_unit_id') == state['selected_unit_id'],
             'Planning actor differs from the selected owned unit in its native save')
    selected = model.get('selected_unit', {})
    _require(all(selected.get(k) == actor[k] for k in fields), 'Planning actor differs from the model observation')
    declared = model.get('planning', {}).get('targets', {}).get(task['id'])
    _require(declared == {'task':task['task'],'target':target}, 'Plan target differs from the actual model request')
    name = task['task']
    _require(name in ('hold','survey','settle','road','irrigate','mine','defend','engage'), 'Unknown planning task')
    if name == 'hold':
        _require(target == {'turn':state['turn']+1}, 'Hold plan has an invalid review turn')
        return
    target_fields = ({'x','y','unknown_neighbors'} if name == 'survey' else
                     {'id','x','y'} if name == 'defend' else
                     {'id','owner','type_id','x','y'} if name == 'engage' else {'x','y'})
    _require(set(target) == target_fields, 'Plan target contains unsupported fields')
    point = target.get('x'), target.get('y')
    known = {(t['x'],t['y']) for t in state['map']['tiles']}
    _require(point in known, 'Planning target is outside the explored native observation')
    if name == 'defend':
        _require(any(all(target.get(k) == c[k] for k in ('id','x','y')) for c in state['cities']),
                 'Defend plan does not target an owned city')
    if name == 'engage':
        _require(any(all(target.get(k) == u[k] for k in ('id','owner','type_id','x','y')) for u in state['visible_units']),
                 'Engage plan does not target a currently visible native unit')
    if name == 'survey':
        neighbors = target.get('unknown_neighbors')
        _require(isinstance(neighbors,list) and neighbors, 'Survey plan has no observed frontier boundary')
        width,height = state['map']['coordinate_width'],state['map']['height']
        legal = set()
        for dx,dy in ((0,-2),(1,-1),(2,0),(1,1),(0,2),(-1,1),(-2,0),(-1,-1)):
            x,y = point[0]+dx,point[1]+dy
            if state['settings']['round_world']:x %= width
            if 0 <= x < width and 0 <= y < height and (x,y) not in known:legal.add((x,y))
        _require(all(isinstance(p,dict) and set(p)=={'x','y'} and (p['x'],p['y']) in legal for p in neighbors),
                 'Survey plan introduces terrain facts beyond its known frontier')


def _recording(files, payload, ffprobe):
    manifest_name = str(PurePosixPath(payload['path']).parent / 'recording.json')
    info = files.inspect(manifest_name); manifest = files.json(manifest_name)
    parent = PurePosixPath(manifest_name).parent
    _require(isinstance(manifest, dict), 'Recording manifest is invalid')
    for key in ('fps', 'frames', 'samples', 'duration_seconds', 'time_compression'):
        _require(manifest.get(key) == payload.get(key), 'Recording manifest and journal disagree')
    fps, frames, samples = (manifest.get(k) for k in ('fps', 'frames', 'samples'))
    _require(_int(fps, 1) and fps <= 30 and _int(frames, 1) and _int(samples, 1)
             and samples <= frames and manifest.get('time_compression') is False,
             'Recording count/rate/continuity metadata is invalid')
    duration = manifest.get('duration_seconds')
    _require(isinstance(duration, (int, float)) and not isinstance(duration, bool)
             and math.isfinite(duration) and math.isclose(duration, frames/fps, abs_tol=1e-6),
             'Recording duration differs from its frame count')
    _require(str(parent / manifest.get('path', '')) == payload['path'], 'Recording paths disagree')
    video = files.inspect(payload['path'])
    ledger_name = str(parent / 'frames.jsonl'); ledger = files.inspect(ledger_name)
    records = [_loads(line) for line in files.path(ledger_name).read_text().splitlines()]
    _require(len(records) == samples, 'Recording sample ledger count differs')
    previous_frame, previous_ms = -1, -1
    for index, row in enumerate(records):
        _require(isinstance(row, dict) and row.get('sample') == index+1
                 and _int(row.get('elapsed_ms')) and row['elapsed_ms'] >= previous_ms
                 and _int(row.get('frame')) and previous_frame < row['frame'] < frames
                 and _sha(row.get('sha256')), 'Recording sample ledger is invalid')
        _require(abs(row['frame']/fps-row['elapsed_ms']/1000) <= 1/fps+.02,
                 'Recording sample frame/time assignment differs')
        previous_frame, previous_ms = row['frame'], row['elapsed_ms']
    _require(records[0]['frame'] == records[0]['elapsed_ms'] == 0
             and records[0].get('initial_observation') is True, 'Recording initial sample is missing')
    probe = {'status': 'unavailable'}
    executable = shutil.which('ffprobe') if ffprobe == 'auto' else ffprobe
    if executable:
        try:
            completed = subprocess.run([str(executable), '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,nb_frames,avg_frame_rate,duration:format=duration',
                '-of', 'json', str(files.path(payload['path']))], capture_output=True, timeout=45, check=True)
            raw = _loads(completed.stdout); stream = raw['streams'][0]
            actual_duration = float(raw['format']['duration'])
            numerator, denominator = map(int, stream['avg_frame_rate'].split('/'))
            _require(denominator > 0 and math.isclose(numerator/denominator, fps, abs_tol=1e-6)
                     and abs(actual_duration-duration) <= max(.05, 1/fps), 'Encoded video rate or duration differs from the recording manifest')
            _require(_int(stream['width'], 1) and _int(stream['height'], 1), 'Encoded video dimensions are invalid')
            count = stream.get('nb_frames')
            _require(count in (None, 'N/A') or int(count) == frames, 'Encoded video frame count differs')
            probe = {'status': 'passed', 'duration_seconds': actual_duration,
                     'width': stream['width'], 'height': stream['height'],
                     'frame_count_checked': count not in (None, 'N/A')}
        except VerificationError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
            raise VerificationError('ffprobe could not validate the encoded recording') from None
    return {'video': video, 'manifest': info, 'sample_ledger': ledger, 'fps': fps,
            'frames': frames, 'samples': samples, 'duration_seconds': duration, 'ffprobe': probe,
            'journal_hash_anchored': False,
            'limitation': 'Current recorder journal anchors counts, not hashes of the MP4/manifest/sample ledger. Reported hashes are computed now. Original dashboard PNG samples were streamed, not retained, so sample hashes cannot be rechecked against source pixels.'}


def _terminal(files, name, chain):
    if name is None:
        return {'status': 'unverified', 'outcome': None,
                'reason': 'No explicit reviewed original terminal evidence supplied.'}
    review_info = files.inspect(name); review = files.json(name)
    _require(isinstance(review, dict) and review.get('schema_version') == 1
             and review.get('game') == 'original-civilization-ii-1.06'
             and review.get('source') == 'original_game'
             and review.get('review_method') == 'human_visual_review' and review.get('reviewed') is True
             and review.get('journal_last_sha256') == chain['last_sha256']
             and review.get('outcome') in ('victory_conquest', 'victory_space', 'defeat', 'retired', 'game_over'),
             'Terminal review is incomplete or bound to a different journal')
    screenshots = review.get('screenshots')
    _require(isinstance(screenshots, list) and 1 <= len(screenshots) <= 8,
             'Terminal review requires original screenshot descriptors')
    images = []
    for descriptor in screenshots:
        image = files.descriptor(descriptor)
        try:
            from PIL import Image, ImageStat
            with Image.open(files.path(image['path'])) as picture:
                _require(picture.format == 'PNG' and picture.size == (640, 480),
                         'Terminal evidence must be an original-resolution PNG')
                picture.load()
                _require(max(ImageStat.Stat(picture.convert('RGB')).stddev) > 1,
                         'Terminal evidence is blank or nearly uniform')
        except VerificationError:
            raise
        except (OSError, ValueError, ImportError):
            raise VerificationError('Terminal screenshot cannot be decoded') from None
        images.append(image)
    return {'status': 'human_reviewed', 'outcome': review['outcome'], 'review': review_info,
            'screenshots': images,
            'verification': 'Review declaration and image integrity checked; this tool does not recognize victory pixels or independently authenticate the human review.'}


def _verify_run(directory, *, terminal_review=None, ffprobe='auto'):
    """Verify retained evidence, never infer victory or claim command acceptance."""
    files = Files(directory)
    events, chain = _journal(files)
    saves, started, stages, decisions, plans, plan_statuses, dispatched = {}, {}, {}, {}, {}, {}, set()
    inputs, forced, forced_pending, recording = 0, 0, None, None
    stops, recoveries, unknown = [], [], Counter()
    checks, initial_state = None, None
    for event in events:
        kind, payload = event['kind'], event['payload']
        files.references(payload)
        if kind not in KNOWN_EVENTS:
            unknown[kind] += 1
        if kind in ('begin', 'checkpoint'):
            descriptor = payload['initial_save' if kind == 'begin' else 'artifact']
            info = files.descriptor(descriptor)
            try:
                state = parse_save(files.path(info['path']).read_bytes())
                if kind == 'begin':
                    checks = verify_setup(state)
                    initial_state = state
                    _require(payload.get('checks') == checks and payload.get('settings') == state['settings'],
                             'Initial ledger setup claims differ from the original save')
                else:
                    _require(payload.get('turn') == state['turn'] and payload.get('year') == state['year_raw'],
                             'Checkpoint date differs from its native save')
                    stable = ('difficulty', 'barbarians', 'bloodlust', 'simplified_combat',
                              'round_world', 'restart_eliminated', 'scenario')
                    _require(all(state['settings'][key] == initial_state['settings'][key] for key in stable)
                             and all(state['map'][key] == initial_state['map'][key] for key in ('width','height','coordinate_width')),
                             'Checkpoint changes the requested campaign settings')
            except VerificationError:
                raise
            except (ValueError, RuntimeError, KeyError, TypeError):
                raise VerificationError('Native save or requested initial setup validation failed') from None
            saves[info['sha256']] = state
        elif kind == 'inference_started':
            identifier = payload.get('decision')
            _require(_int(identifier, 1) and identifier not in started, 'Inference identifier is duplicated or invalid')
            request = files.json(payload['request']['path'])
            try:
                _validate_questions(request['questions'])
            except (ValueError, RuntimeError, KeyError, TypeError):
                raise VerificationError('Saved model request is invalid') from None
            started[identifier] = request
            stage = payload.get('stage','command')
            _require(stage in ('command','planning'), 'Inference stage is invalid')
            stages[identifier] = stage
        elif kind == 'model_plan':
            identifier = payload.get('decision')
            _require(identifier in started and identifier not in plans and identifier not in decisions
                     and stages[identifier] == 'planning' and payload.get('executes_input') is False
                     and payload.get('selected_question') == 'task_choice'
                     and events[0]['payload'].get('planning_enabled') is True,
                     'Planning event is not a declared separate non-dispatch inference')
            request = started[identifier]; response = files.json(payload['response']['path'])
            try:
                clean = validate_response(response, request['questions'])
            except (ValueError,RuntimeError,KeyError,TypeError):
                raise VerificationError('Planning response fails strict probability/schema validation') from None
            answer = clean['answers'].get('task_choice', {})
            task = payload.get('task')
            _require(answer.get('type') == 'choice' and isinstance(task,dict)
                     and task.get('id') == answer.get('choice')
                     and task.get('label') == request['questions']['task_choice']['criteria'][answer['choice']],
                     'Plan differs from the actual selected model task')
            _plan_binding(task, request, saves)
            plans[identifier] = {'task':task,'response':response}
        elif kind == 'plan_status':
            _require(payload.get('executes_input') is False, 'Plan status cannot authorize a game input')
            if payload.get('status') == 'unavailable':
                _require('plan' not in payload, 'Unavailable plan status contains a plan')
                continue
            identifier = payload.get('planning_decision'); plan = payload.get('plan')
            _require(identifier in plans and isinstance(plan,dict)
                     and plan.get('decision_id') == identifier and plan.get('candidate') == plans[identifier]['task']
                     and plan.get('status') in ('active','complete','invalidated','expired')
                     and plan.get('current_save_sha256') in saves,
                     'Plan status does not reference its actual prior task and native checkpoint')
            if plan['status'] == 'active':
                state = saves[plan['current_save_sha256']]
                _require(isinstance(plan.get('actor'),dict)
                         and set(plan['actor']) == set(plan['candidate']['actor'])
                         and any(all(u.get(k)==v for k,v in plan['actor'].items()) for u in state['units']),
                         'Active plan actor differs from its current native checkpoint')
            plan_statuses[identifier] = plan
        elif kind == 'model_decision':
            identifier, question = payload.get('decision'), payload.get('selected_question')
            _require(identifier in started and identifier not in decisions and identifier not in plans
                     and stages[identifier] == 'command', 'Model decision has no unique prior command inference')
            request = started[identifier]; response = files.json(payload['response']['path'])
            try:
                clean = validate_response(response, request['questions'])
            except (ValueError, RuntimeError, KeyError, TypeError):
                raise VerificationError('Saved model response fails strict probability/schema validation') from None
            _require(question in DISPATCHES.values() and question in clean['answers']
                     and clean['answers'][question]['type'] == 'choice', 'Dispatch question is not a supported model Choice')
            action = payload.get('action'); choice = clean['answers'][question]['choice']
            _require(isinstance(action, dict) and action.get('id') == choice
                     and action.get('label') == request['questions'][question]['criteria'][choice],
                     'Selected action does not match the actual model choice and criterion')
            _action_binding(action, request, question, saves)
            context = request.get('state', {}).get('persistent_plan')
            if context is not None:
                plan_id = context.get('planning_decision')
                _require(question == 'unit_action' and plan_id in plan_statuses,
                         'Command planning context has no prior observed plan status')
                plan = plan_statuses[plan_id]
                _require(plan['status'] == context.get('status') == 'active'
                         and all(context.get(k) == plan['candidate'][k] for k in ('task','target','label'))
                         and context.get('actor') == plan['actor']
                         and plan['current_save_sha256'] == action['preconditions']['save_sha256'],
                         'Command planning context differs from the current observed model plan')
            decisions[identifier] = {'action': action, 'question': question, 'response': response}
        elif kind == 'forced_empire_command':
            _require(forced_pending is None and payload.get('action', {}).get('id') == 'finish_turn',
                     'Only explicit forced Finish Turn is supported')
            forced_pending = payload['action']
            _action_binding(forced_pending, {'state': {'turn': forced_pending['preconditions']['turn']}},
                            'empire_action', saves)
        elif kind in DISPATCHES:
            question = DISPATCHES[kind]
            identifier = payload.get('decision')
            if identifier is None and question == 'empire_action':
                matches = [i for i, d in decisions.items() if i not in dispatched
                           and d['action'] == payload.get('action') and d['question'] == question]
                if len(matches) == 1:
                    identifier = matches[0]
                elif forced_pending == payload.get('action'):
                    inputs += _dispatch(payload, forced_pending, question, files)
                    forced += 1; forced_pending = None
                    continue
            _require(identifier in decisions and identifier not in dispatched
                     and decisions[identifier]['question'] == question,
                     'Dispatch has no unique prior selected model decision')
            inputs += _dispatch(payload, decisions[identifier]['action'], question, files)
            dispatched.add(identifier)
        elif kind == 'dialog_keyboard_recovery':
            identifier = payload.get('decision')
            _require(identifier in decisions and identifier not in dispatched and identifier not in recoveries
                     and decisions[identifier]['question'] == 'dialog_action'
                     and payload.get('label') == decisions[identifier]['action']['label'],
                     'Manual dialog recovery does not match a pending model choice')
            files.screen(payload.get('before')); files.screen(payload.get('after'))
            recovered_inputs = _inputs(payload.get('inputs'))
            _require(all(r['type'] == 'key' and r['code'] in
                         ('Home','End','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Enter') for r in recovered_inputs)
                     and recovered_inputs[-1]['code'] == 'Enter', 'Manual dialog recovery has unsupported inputs')
            recoveries.append(identifier)
        elif kind == 'recording_finalized':
            _require(recording is None, 'Multiple recording finalizations are unsupported')
            recording = _recording(files, payload, ffprobe)
        elif kind == 'session_stopped':
            stops.append(payload)
        elif kind == 'batch_observed_effect':
            identifiers = payload.get('decisions')
            _require(isinstance(identifiers,list) and all(i in decisions for i in identifiers),
                     'Native effect batch includes a non-command planning decision')
    _require(checks is not None, 'Initial native setup evidence is absent')
    outcome = _terminal(files, terminal_review, chain)
    complete = len(stops) == 1 and recording is not None and not unknown
    responses = [d['response'] for group in (decisions,plans) for d in group.values()]
    numeric_metadata = ('rejected_response_attempts', 'rejected_input_tokens',
                        'rejected_output_tokens', 'rejected_usage_unavailable_attempts')
    totals = {key: 0 for key in numeric_metadata}
    for response in responses:
        metadata = response.get('metadata', {})
        _require(isinstance(metadata, dict), 'Response metadata is malformed')
        for key in numeric_metadata:
            value = metadata.get(key, 0)
            _require(_int(value), 'Response usage metadata is invalid')
            totals[key] += value
    return {'schema_version': 1, 'integrity': 'passed', 'journal': chain,
            'initial_setup': {'checks': checks, 'save_sha256': events[0]['payload']['initial_save']['sha256']},
            'artifacts': {'verified_count': len(files.checked), 'files': sorted(files.checked.values(), key=lambda x: x['path'])},
            'decisions': {'inferences_started': len(started), 'validated_responses': len(decisions)+len(plans),
                          'command_decisions':len(decisions), 'planning_decisions':len(plans),
                          'planning_dispatches':0,
                          'planning_note':'Planning choices and observed plan-status changes are context only, not commands or native effects.',
                          'model_dispatches': len(dispatched), 'ordinary_input_events': inputs,
                          'undispatched_decisions': sorted(set(decisions)-dispatched),
                          'inferences_without_response': sorted(set(started)-set(decisions)-set(plans)),
                          'forced_empire_dispatches': forced,
                          'manually_reviewed_keyboard_recoveries': recoveries,
                          'manual_recovery_note': 'These choices required separately logged manual selection review. They are not counted as automatically verified model dispatches or autonomous-run proof.',
                          'models': sorted({r['model'] for r in responses}),
                          'accepted_response_input_tokens': sum(r['usage']['input_tokens'] for r in responses),
                          'accepted_response_output_tokens': sum(r['usage']['output_tokens'] for r in responses),
                          'rejected_response_usage': totals,
                          'acceptance': 'Inputs match recorded model selections. Native acceptance and strategic effects are not inferred.'},
            'recording': recording, 'outcome': outcome,
            'completeness': {'finalized_session': len(stops) == 1, 'uninterpreted_event_counts': dict(sorted(unknown.items())),
                             'pending_forced_command': forced_pending is not None,
                             'release_review_ready': complete and recording['ffprobe']['status'] == 'passed'
                              and outcome['status'] == 'human_reviewed' and len(dispatched) == len(decisions)
                              and len(started) == len(decisions)+len(plans) and forced_pending is None and not recoveries},
            'limitations': ['A local hash chain is not server-signed proof of model provenance or absence of off-journal input.',
                           'Historical requests are checked as recorded, not regenerated with the current candidate policy. Legal availability and native acceptance are not established; controller source revisions must be retained separately for reproducibility.',
                           'This verifier performs no OCR, live game calls or automatic victory recognition.',
                           'Do not publish original saves or game assets merely because their integrity checks pass.']}


def verify_run(directory, *, terminal_review=None, ffprobe='auto'):
    """Return a compact report or a fixed diagnostic; never contact the game."""
    try:
        return _verify_run(directory, terminal_review=terminal_review, ffprobe=ffprobe)
    except VerificationError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        raise VerificationError('Evidence structure or referenced artifact is invalid') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--terminal-review', help='Confined relative path to an explicit human terminal review JSON')
    parser.add_argument('--no-ffprobe', action='store_true')
    parser.add_argument('--output', help='Optional report output path; no evidence is modified')
    args = parser.parse_args()
    try:
        report = verify_run(args.directory, terminal_review=args.terminal_review,
                            ffprobe=None if args.no_ffprobe else 'auto')
    except (VerificationError, OSError):
        # Neither file paths, original game data nor remote contents are echoed.
        print(json.dumps({'integrity': 'failed', 'error': 'Evidence verification failed; inspect the scoped local artifacts.'}))
        return 1
    data = json.dumps(report, indent=2, allow_nan=False)+'\n'
    if args.output:
        with Path(args.output).open('x', encoding='utf-8') as output:
            output.write(data)
    print(data, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
