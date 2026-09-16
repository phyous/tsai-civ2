"""Offline integrity checks for a local original-Civ-II evidence directory.

No emulator, network, credential, OCR, or game-control calls occur here. A valid
local hash chain is not an independent attestation of how its data was created.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess

from .boot import verify_setup
from .city import WORKED_BITS, city_labor_projection
from .evidence import canonical
from .save import parse_save
from .typesafe import _validate_questions, validate_response


class VerificationError(ValueError):
    """Messages are fixed diagnostics, never raw evidence or remote output."""


SHA = re.compile(r'[0-9a-f]{64}')
SCREEN_KEYS = {'screen', 'before', 'after', 'dialog', 'typed', 'saved',
               'selected_frame', 'source_image', 'image_sha256', 'completion_screen', 'opening', 'verified_image'}
DISPATCHES = {'command_dispatched': 'unit_action', 'dialog_dispatched': 'dialog_action',
              'empire_command_dispatched': 'empire_action', 'city_control_dispatched':'city_action'}
KNOWN_EVENTS = {'begin', 'checkpoint', 'inference_started', 'model_decision',
                'screen_observed', 'mechanical_input', 'open_city_control',
                'navigate_selected_city', 'batch_observed_effect',
                'forced_empire_command', 'session_stopped', 'recording_finalized',
                'dialog_keyboard_recovery',
                'model_plan', 'plan_status',
                'forced_city_control', 'city_control_review_completed', 'city_control_closed',
                'graphics_preferences_configured',
                'city_labor_refresh_started', 'city_labor_refresh_input',
                'city_labor_checkpoint', 'city_labor_ready',
                'city_labor_refresh_failed',
                'native_presentation_acknowledged', 'checkpoint_reused',
                *DISPATCHES}


def _require(condition, message):
    if not condition:
        raise VerificationError(message)


def _int(value, minimum=0):
    return type(value) is int and value >= minimum


def _sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _one_edit(a,b):
    if a==b:return True
    if abs(len(a)-len(b))>1:return False
    if len(a)==len(b):return sum(x!=y for x,y in zip(a,b))==1
    short,long=(a,b) if len(a)<len(b) else (b,a)
    return any(long[:i]+long[i+1:]==short for i in range(len(long)))


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


def _action_binding(action, request, question, saves, *, forced=False):
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
        if actor.get('id') == 'buy_quote':
            _purchase_quote(dialog.get('quote'))
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
    elif question == 'city_action':
        controls = {'change_production':('change','production_choice'),
                    'open_buy_quote':('buy','buy_quote'), 'exit_city':('exit','original_map')}
        identifier = action['id']; point = params.get('center')
        expected = controls.get(identifier)
        labor = action['kind'] == 'city_labor'
        _require((labor or expected is not None and action['kind'] == 'city_control')
                 and set(actor) == {'kind','id','owner','name','x','y'} and actor['kind'] == 'city'
                 and all(_int(actor[k]) for k in ('id','owner','x','y')) and isinstance(actor['name'],str)
                 and any(all(actor.get(k)==c.get(k) for k in ('id','owner','name','x','y')) for c in state['cities']),
                 'City control actor differs from its owned native city')
        _require(pre.get('screen_kind') == 'city_screen' and _sha(pre.get('image_sha256'))
                 and pre.get('width') == 640 and pre.get('height') == 480
                 and pre.get('year_raw') == state['year_raw']
                 and isinstance(pre.get('reviewed_action_ids'),list)
                 and len(set(pre['reviewed_action_ids'])) == len(pre['reviewed_action_ids'])
                 and set(pre['reviewed_action_ids']) <= {'change_production','open_buy_quote'}
                 and identifier not in pre['reviewed_action_ids'], 'City control observation binding is invalid')
        title = pre.get('observed_city_title')
        match = re.match(r'^City of (.+?),\s*(\d{1,5})\s*(B\.?\s*C\.?|A\.?\s*D\.?)\b',title,re.I) if isinstance(title,str) else None
        _require(match is not None
                 and int(match[2])*(-1 if match[3][0].casefold()=='b' else 1) == state['year_raw'],
                 'City control title differs from its native city and year')
        normalized=lambda value:' '.join(value.casefold().split())
        if normalized(match[1])!=normalized(actor['name']):
            proof=pre.get('city_name_recovery',{})
            matches=[c for c in state['cities'] if _one_edit(normalized(match[1]),normalized(c['name']))]
            _require(3<=len(normalized(match[1]))<=50 and len(matches)==1 and matches[0]['id']==actor['id']
                     and pre.get('observed_city_name')==actor['name']
                     and isinstance(proof,dict)
                     and set(proof)=={'source','ocr_text','canonical_name','city_id','save_sha256','source_line'}
                     and proof.get('source')=='Unique one-edit match to owned city in original save'
                     and proof.get('ocr_text')==match[1] and proof.get('canonical_name')==actor['name']
                     and type(proof.get('city_id')) is int and proof['city_id']==actor['id']
                     and proof.get('save_sha256')==digest and _int(proof.get('source_line')),
                     'Recovered city title lacks unique native-save and original OCR provenance')
        if labor:
            _labor_binding(action, state, model)
        else:
            _require(isinstance(point,list) and len(point)==2 and all(_int(v) for v in point)
                 and point[0]<640 and point[1]<480 and _int(params.get('button_index')) and params['button_index']<64
                 and isinstance(params.get('observed_text'),str)
                 and params['observed_text'].strip().casefold() == expected[0]
                 and params.get('control') == 'button' and params.get('expected_screen') == expected[1]
                 and params.get('only_open_menu') is (identifier!='exit_city')
                 and params.get('purchase_authorized') is False
                 and params.get('confirmation_requires_separate_choice') is (identifier=='open_buy_quote'),
                     'City control does not match its ordinary button or quote-only semantics')
        if not forced:
            review = model.get('city_control_review', {})
            _require(review.get('actor') == actor and review.get('observed_title') == title
                     and review.get('year_raw') == pre['year_raw']
                     and review.get('reviewed_action_ids') == pre['reviewed_action_ids']
                     and review.get('controls') == request['questions']['city_action']['criteria'],
                     'City control differs from the actual observed model request')
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
        if question == 'city_action':
            _require(before == action['preconditions']['image_sha256'] and not keys,
                     'City control receipt does not match its image or contains unrelated keys')
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


def _city_review_binding(action, reviewed, *, completed=False):
    actor,pre = action['actor'],action['preconditions']
    expected = set(pre['reviewed_action_ids']) | ({action['id']} if completed else set())
    _require(isinstance(reviewed,dict) and set(reviewed) in (
                {'city_id','city_name','year_raw','actions'},
                {'city_id','city_name','year_raw','actions','labor_reassignments'})
             and reviewed['city_id']==actor['id'] and reviewed['city_name']==actor['name']
             and reviewed['year_raw']==pre['year_raw'] and isinstance(reviewed['actions'],list)
             and len(reviewed['actions'])==len(set(reviewed['actions']))
             and set(reviewed['actions'])==expected, 'City control review belongs to a different city, year or transaction')
    used=reviewed.get('labor_reassignments',0)
    _require(_int(used) and used<=40, 'City labor review allowance is invalid')
    if action['kind']=='city_labor':
        _require(used==pre['labor_review_used'], 'Labor receipt changes its declared review allowance')


def _labor_values(state, actor):
    """Decode retained native bytes; never trust a claimed bitmap delta."""
    projection=city_labor_projection(state,actor['id'])
    city=projection['city']
    _require(all(city[k]==actor.get(k) for k in ('id','owner','name','x','y')),
             'Labor save belongs to a different original city')
    return dict(worked_tiles_bits=projection['worked_tiles_bits'],
                specialist_count=projection['specialists']['count'],
                specialists={k:v for k,v in projection['specialists']['stored_type_counts'].items() if v},
                size=city['size']), projection


def _labor_binding(action, state, model):
    pre,params=action['preconditions'],action['parameters']
    old,projection=_labor_values(state,action['actor'])
    slot=params.get('slot');mode=params.get('mode')
    _require(_int(slot) and slot<len(WORKED_BITS) and slot!=16,
             'Labor action targets an uncalibrated slot or immutable center')
    byte,bit,dx,dy=WORKED_BITS[slot]
    cell=projection['city_radius'][slot]
    _require(set(params)=={'control','center','slot','position','mode','source_byte','source_bit',
                         'only_open_menu','purchase_authorized','expected_screen',
                         'native_checkpoint_required','city_center_immutable'}
             and params.get('control')=='resource_map'
             and isinstance(params.get('center'),list) and all(_int(v) for v in params['center'])
             and params.get('center')==[104+24*dx,192+12*dy]
             and type(params.get('source_byte')) is int and params['source_byte']==48+byte
             and type(params.get('source_bit')) is int and params['source_bit']==bit
             and canonical(params.get('position'))==canonical(cell['position']) and cell['knowledge']=='explored'
             and params.get('only_open_menu') is False and params.get('purchase_authorized') is False
             and params.get('expected_screen')=='city_screen'
             and params.get('native_checkpoint_required') is True and params.get('city_center_immutable') is True,
             'Labor action differs from its calibrated original Resource Map target')
    _require(canonical(pre.get('labor_before'))==canonical(old) and not projection['warnings']
             and not old['specialists'].get('taxman') and not old['specialists'].get('scientist')
             and pre.get('labor_calibration')=='classic640-labor-grid-20-native-save-v1',
             'Labor action differs from its complete native worker and specialist preconditions')
    worked=bool(old['worked_tiles_bits'][byte]&(1<<bit))
    _require((mode=='remove_worker' and worked
              or mode=='assign_entertainer' and not worked and old['specialists'].get('entertainer',0)>0)
             and action['id']==f'labor_{mode}_{slot}',
             'Labor mode is not supported by the original worker assignment')
    used,limit=pre.get('labor_review_used'),pre.get('labor_review_limit')
    review=model.get('city_control_review',{})
    allowance=review.get('labor_review',{})
    _require(_int(used) and type(limit) is int and limit==min(40,2*old['size']) and used<limit
             and review.get('labor_checkpoint_ready') is True
             and all(_int(allowance.get(k)) for k in ('used','limit','remaining'))
             and allowance.get('used')==used and allowance.get('limit')==limit
             and allowance.get('remaining')==limit-used,
             'Labor action has no remaining declared city review allowance')


def _labor_result(action, before, after):
    old,a=_labor_values(before,action['actor']);new,b=_labor_values(after,action['actor'])
    _require(before['turn']==after['turn'] and before['year_raw']==after['year_raw']
             and a['city']==b['city'] and old==action['preconditions']['labor_before'],
             'Labor follow-up changed its bound city, population or turn')
    expected=deepcopy(old)
    byte,bit,_,_=WORKED_BITS[action['parameters']['slot']]
    delta=1 if action['parameters']['mode']=='remove_worker' else -1
    expected['worked_tiles_bits'][byte]^=1<<bit
    expected['specialist_count']+=delta
    expected['specialists']['entertainer']=expected['specialists'].get('entertainer',0)+delta
    expected['specialists']={k:v for k,v in expected['specialists'].items() if v}
    status=('observed_expected_change' if new==expected else
            'no_observed_change' if new==old else 'unexpected_change')
    return dict(status=status,before=old,expected=expected,after=new,
                before_save_sha256=before['evidence']['save_sha256'],
                after_save_sha256=after['evidence']['save_sha256'],turn=after['turn'],city=b['city'])


def _labor_city(state, city):
    _require(isinstance(city,dict) and set(city)=={'id','owner','name','x','y'}
             and all(_int(city.get(k)) for k in ('id','owner','x','y'))
             and isinstance(city.get('name'),str)
             and city['owner']==state['player']['id']
             and sum(all(c.get(k)==v for k,v in city.items()) for c in state['cities'])==1,
             'Labor refresh does not identify one owned native city')


def _labor_navigation(payload, city, files):
    _require(payload.get('city')==city, 'Labor refresh navigated to another city')
    count=0
    for key,label in (('receipt',city['name']),('zoom_receipt','Zoom To City')):
        receipt=payload.get(key)
        _require(isinstance(receipt,dict) and isinstance(receipt.get('target'),str)
                 and receipt['target'].casefold()==label.casefold(),
                 'Labor refresh locator does not select its observed city and Zoom control')
        _require(not any(row['type']=='key' for row in _inputs(receipt.get('inputs'))),
                 'Labor refresh locator must use two ordinary clicks without confirmation keys')
        action={'label':receipt['target'],'preconditions':{'image_sha256':receipt.get('before')},
                'parameters':{'center':receipt.get('point')}}
        count+=_dispatch({'action':action,'receipt':receipt,'after':receipt.get('before')},
                         action,'dialog_action',files)
    return count


def _purchase_quote(quote):
    _require(isinstance(quote,dict) and isinstance(quote.get('item'),str) and 0<len(quote['item'])<=100
             and _int(quote.get('cost')) and _int(quote.get('treasury')) and quote['cost']<=quote['treasury']
             and quote.get('purchase_executed') is False
             and quote.get('source')=='Original GAME.TXT COMPLETE1 and complete visible quote',
             'Purchase response lacks its original observed cost/treasury quote')


def _graphics_preferences(receipt, files):
    labels = {'Throne Room','Diplomacy Screen','Animated Heralds',
              'Civilopedia for Advances','High Council','Wonder Movies'}
    target = 'Civilopedia for Advances'
    _require(isinstance(receipt,dict), 'Graphics preference receipt is missing')
    before,after = receipt.get('checkbox_before'),receipt.get('checkbox_after')
    _require(isinstance(before,dict) and isinstance(after,dict) and set(before)==set(after)==labels
             and all(type(v) is bool for values in (before,after) for v in values.values())
             and after[target] is False and all(before[k]==after[k] for k in labels-{target})
             and receipt.get('other_checkboxes_unchanged') is True,
             'Graphics preferences changed more than the single presentation option')
    for key in ('before','opening','after'):files.screen(receipt.get(key))
    keys = _inputs(receipt.get('inputs'))
    _require([(r['type'],r.get('code'),r.get('down')) for r in keys]==[
        ('key','ControlLeft',True),('key','KeyP',True),('key','KeyP',False),('key','ControlLeft',False),
        ('key','Enter',True),('key','Enter',False)], 'Graphics preference dialog uses unrelated keyboard input')
    changes = receipt.get('changes')
    _require(isinstance(changes,list) and len(changes)==1 and isinstance(changes[0],dict) and changes[0].get('label')==target
             and changes[0].get('before') is before[target] and changes[0].get('after') is False,
             'Graphics preference change does not match its observed checkbox states')
    change=changes[0];files.screen(change.get('verified_image'));click=change.get('receipt')
    if before[target] is False:
        _require(click is None, 'Already-disabled presentation option must not be toggled')
        return
    _require(isinstance(click,dict) and click.get('before')==receipt['opening']
             and isinstance(click.get('target'),str)
             # The original checked box is read as a leading M in006. The
             # recorded target retains that glyph; it is not another option.
             and re.sub(r'[^a-z0-9]','',click['target'].casefold()) in
                 ('civilopediaforadvances','mcivilopediaforadvances'),
             'Graphics preference click targets a different option')
    inputs=_inputs(click.get('inputs'))
    buttons=[r for r in inputs if r['type']=='mouse' and r['event']!='mousemove']
    _require(not any(r['type']=='key' for r in inputs) and [r['event'] for r in buttons]==['mousedown','mouseup']
             and all(r['button']==0 for r in buttons), 'Graphics preference needs one ordinary checkbox click')
    park=click.get('pointer_park')
    _require(isinstance(park,dict) and park.get('issued') is False and park.get('target')==[620,410]
             and isinstance(park.get('observed_cursor'),list) and len(park['observed_cursor'])==2
             and all(_int(v) for v in park['observed_cursor']) and _int(park.get('tolerance'))
             and park['tolerance']<=4 and max(abs(a-b) for a,b in zip(park['observed_cursor'],park['target']))<=park['tolerance']
             and isinstance(park.get('inputs'),list), 'Preference cursor park was not observed at its bounded target')
    if park['inputs']:
        _require(all(r['type']=='relativeMouse' for r in _inputs(park['inputs'])),
                 'Preference cursor park contains a non-movement input')


def _presentation(payload, files, observed_screens):
    source=payload.get('source_hash');receipt=payload.get('receipt')
    files.screen(source)
    observed=observed_screens.get(source,{})
    _require(payload.get('resource_tag')=='THRONE' and observed.get('classification')=='presentation_notice'
             and observed.get('supported') is True and isinstance(receipt,dict)
             and receipt.get('before')==source and isinstance(receipt.get('target'),str)
             and receipt['target'].strip().casefold()=='(click mouse to continue...)',
             'Presentation acknowledgment lacks its prior classified original notice and prompt')
    point=receipt.get('point')
    _require(isinstance(point,list) and len(point)==2 and all(_int(v) for v in point)
             and 60<=point[0]<=580 and 90<=point[1]<=310
             and receipt.get('method')=='Original full-screen click-to-continue prompt; clicked observed narrative'
             and not any(r['type']=='key' for r in _inputs(receipt.get('inputs'))),
             'Presentation acknowledgment must click its observed narrative within the original full-screen notice')
    if 'acknowledgement_point' in payload or 'template_sha256' in payload:
        _require(payload.get('acknowledgement_point')==point and _sha(payload.get('template_sha256')),
                 'Presentation receipt differs from the recorded classified narrative point or template')
    action={'label':receipt['target'],'preconditions':{'image_sha256':source},'parameters':{'center':point}}
    return _dispatch({'action':action,'receipt':receipt,'after':source},action,'dialog_action',files)


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
    _require(name in ('hold','survey','settle','road','irrigate','mine','defend','engage','approach_city'), 'Unknown planning task')
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
    if name == 'approach_city':
        _require(any((c.get('x'),c.get('y')) == point for c in state['known_cities'])
                 and any((c.get('x'),c.get('y')) == point for c in model.get('remembered_foreign_cities',[])),
                 'Approach plan does not target a remembered city shown to the model')
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
    forced_city, forced_city_pending, city_pending = 0, None, None
    city_reviews, city_closures, graphics_reviews = 0, 0, 0
    labor_refresh, labor_ready = None, None
    labor_outcomes, labor_usage, checkpoint_sequences = {}, {}, {}
    labor_failures=[]
    latest_save_sha256=None
    observed_screens={}
    checkpoint_count,checkpoint_reuses,presentation_acknowledgments=0,0,0
    last_finish,reusable_checkpoint=None,None
    stops, recoveries, unknown = [], [], Counter()
    checks, initial_state = None, None
    for event in events:
        kind, payload = event['kind'], event['payload']
        files.references(payload)
        observation_only={'screen_observed','batch_observed_effect','plan_status'}
        if kind not in observation_only|{'checkpoint','checkpoint_reused'}:
            reusable_checkpoint=None
        if kind not in observation_only|{'checkpoint'}:
            last_finish=None
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
            checkpoint_sequences[info['sha256']]=event['sequence']
            latest_save_sha256=info['sha256']
            if kind=='checkpoint':
                checkpoint_count+=1
                reusable_checkpoint=(dict(checkpoint=checkpoint_count,save_sha256=info['sha256'],
                                          turn=state['turn'],year=state['year_raw'])
                                     if last_finish is not None and state['turn']>last_finish['turn'] else None)
            last_finish=None
        elif kind=='screen_observed':
            observed_screens[payload.get('screen')]={'classification':payload.get('classification'),
                                                     'supported':payload.get('supported')}
        elif kind=='checkpoint_reused':
            _require(reusable_checkpoint is not None
                     and all(canonical(payload.get(k))==canonical(v) for k,v in reusable_checkpoint.items())
                     and payload.get('save_sha256')==latest_save_sha256
                     and payload.get('ordinary_inputs_since_checkpoint') is False
                     and observed_screens.get(payload.get('screen'))=={'classification':'end_turn','supported':True},
                     'Reused checkpoint is stale, repeated or lacks an immediately verified advanced turn')
            files.screen(payload['screen']);checkpoint_reuses+=1;reusable_checkpoint=None
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
            if action['kind']=='city_labor':
                signature={k:action['actor'][k] for k in ('id','owner','name','x','y')}
                key=(signature['id'],signature['name'],action['preconditions']['year_raw'])
                _require(labor_refresh is None and labor_ready is not None
                         and labor_ready['city']==signature
                         and labor_ready['save_sha256']==action['preconditions']['save_sha256']==latest_save_sha256
                         and action['preconditions']['labor_review_used']==labor_usage.get(key,0),
                         'Labor choice lacks a completed native refresh or reuses its review allowance')
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
        elif kind == 'forced_city_control':
            action = payload.get('action')
            _require(forced_city_pending is None and city_pending is None and isinstance(action,dict)
                     and action.get('id')=='exit_city', 'Only a pending-free observed Exit may be forced')
            _action_binding(action,{'state':{'turn':action['preconditions']['turn']}},'city_action',saves,forced=True)
            _city_review_binding(action,payload.get('reviewed'))
            forced_city_pending = action
        elif kind in DISPATCHES:
            _require(labor_refresh is None and not (city_pending is not None
                     and city_pending['action']['kind']=='city_labor'),
                     'A strategic dispatch interrupted an unresolved labor verification')
            question = DISPATCHES[kind]
            identifier = payload.get('decision')
            if question == 'city_action':
                _require(city_pending is None, 'A city control transaction is already pending')
                _city_review_binding(payload.get('action',{}),payload.get('reviewed'))
                if identifier is None:
                    _require(forced_city_pending == payload.get('action') and forced_city_pending is not None,
                             'Forced city dispatch has no prior observed Exit')
                    inputs += _dispatch(payload,forced_city_pending,question,files)
                    city_pending = {'action':forced_city_pending,'decision':None,'sequence':event['sequence'],'mechanical':[]}
                    forced_city += 1; forced_city_pending = None
                    continue
            if identifier is None and question == 'empire_action':
                matches = [i for i, d in decisions.items() if i not in dispatched
                           and d['action'] == payload.get('action') and d['question'] == question]
                if len(matches) == 1:
                    identifier = matches[0]
                elif forced_pending == payload.get('action'):
                    inputs += _dispatch(payload, forced_pending, question, files)
                    last_finish={'turn':forced_pending['preconditions']['turn']}
                    forced += 1; forced_pending = None
                    continue
            _require(identifier in decisions and identifier not in dispatched
                     and decisions[identifier]['question'] == question,
                     'Dispatch has no unique prior selected model decision')
            selected=decisions[identifier]['action']
            if selected['kind']=='city_labor':
                key=(selected['actor']['id'],selected['actor']['name'],selected['preconditions']['year_raw'])
                _require(labor_ready is not None
                         and labor_ready['save_sha256']==selected['preconditions']['save_sha256']==latest_save_sha256
                         and selected['preconditions']['labor_review_used']==labor_usage.get(key,0),
                         'Labor dispatch lost its current refresh or remaining review allowance')
            inputs += _dispatch(payload, decisions[identifier]['action'], question, files)
            if question=='empire_action' and selected['id']=='finish_turn':
                last_finish={'turn':selected['preconditions']['turn']}
            dispatched.add(identifier)
            labor_ready=None
            if question == 'city_action':
                city_pending = {'action':decisions[identifier]['action'],'decision':identifier,
                                'sequence':event['sequence'],'mechanical':[]}
                if city_pending['action']['kind']=='city_labor':
                    action=city_pending['action']
                    key=(action['actor']['id'],action['actor']['name'],action['preconditions']['year_raw'])
                    labor_usage[key]=labor_usage.get(key,0)+1
                    labor_outcomes[identifier]={'decision':identifier,'status':'unobserved',
                                                'action_id':action['id']}
        elif kind == 'city_labor_refresh_started':
            purpose=payload.get('purpose');action=payload.get('action');identifier=payload.get('decision')
            digest=payload.get('before_save_sha256')
            _require(labor_refresh is None and purpose in ('prepare_labor_choices','verify_labor')
                     and digest in saves, 'Labor refresh has no unique native starting checkpoint')
            _labor_city(saves[digest],payload.get('city'))
            if purpose=='verify_labor':
                _require(city_pending is not None and city_pending['decision']==identifier
                         and action==city_pending['action'] and action['kind']=='city_labor'
                         and action['preconditions']['save_sha256']==digest
                         and all(action['actor'][k]==v for k,v in payload['city'].items()),
                         'Labor verification refresh does not follow its exact dispatched choice')
            else:
                _require(city_pending is None and action is None and identifier is None,
                         'Preparation refresh cannot hide an unresolved city transaction')
            labor_refresh={**payload,'sequence':event['sequence'],'step':'started'}
            labor_ready=None
        elif kind == 'city_labor_refresh_input':
            _require(labor_refresh is not None and payload.get('decision')==labor_refresh['decision']
                     and payload.get('purpose')==labor_refresh['purpose']
                     and not labor_refresh.get('failed'),
                     'Labor refresh input has no matching pending transaction')
            step=payload.get('step')
            _require((step=='close_city' and labor_refresh['step']=='started'
                      or step=='open_locator' and labor_refresh['step']=='checkpoint'),
                     'Labor refresh input is missing, duplicated or out of order')
            files.screen(payload.get('before'));ordinary=_inputs(payload.get('inputs'))
            expected=([('Escape',True),('Escape',False)] if step=='close_city' else
                      [('ShiftLeft',True),('KeyC',True),('KeyC',False),('ShiftLeft',False)])
            _require(all(r['type']=='key' for r in ordinary)
                     and [(r['code'],r['down']) for r in ordinary]==expected,
                     'Labor refresh contains an unrelated input')
            inputs+=len(ordinary);labor_refresh['step']=step
            labor_refresh['input_sequence']=event['sequence']
        elif kind == 'city_labor_checkpoint':
            digest=payload.get('save_sha256')
            _require(labor_refresh is not None and payload.get('decision')==labor_refresh['decision']
                     and payload.get('purpose')==labor_refresh['purpose']
                     and labor_refresh['step']=='close_city' and digest in saves
                     and not labor_refresh.get('failed')
                     and checkpoint_sequences[digest]>labor_refresh['input_sequence']
                     and _int(payload.get('checkpoint'),1),
                     'Labor follow-up lacks a later native save after closing the city')
            _labor_city(saves[digest],labor_refresh['city'])
            before=saves[labor_refresh['before_save_sha256']];after=saves[digest]
            _require(before['turn']==after['turn'] and before['year_raw']==after['year_raw'],
                     'Labor refresh crossed a native turn or year')
            if labor_refresh['purpose']=='verify_labor':
                result=_labor_result(labor_refresh['action'],before,after)
                claimed=payload.get('result')
                _require(isinstance(claimed,dict) and set(claimed)==set(result)|{'observation'}
                         and all(canonical(claimed.get(k))==canonical(v) for k,v in result.items())
                         and isinstance(claimed.get('observation'),str),
                         'Claimed labor result differs from the subsequent native save')
                identifier=labor_refresh['decision']
                labor_outcomes[identifier].update(result)
            else:
                _require(payload.get('result') is None,
                         'Preparing labor choices cannot claim a labor input result')
            labor_refresh.update(step='checkpoint',save_sha256=digest)
        elif kind == 'navigate_selected_city' and labor_refresh is not None:
            _require(labor_refresh['step']=='open_locator' and not labor_refresh.get('failed'),
                     'Labor refresh locator navigation is out of order')
            inputs+=_labor_navigation(payload,labor_refresh['city'],files)
            labor_refresh['step']='navigated'
        elif kind == 'city_labor_ready':
            _require(labor_refresh is not None and labor_refresh['step']=='navigated'
                     and not labor_refresh.get('failed')
                     and all(payload.get(k)==labor_refresh[k] for k in ('decision','purpose','city','save_sha256')),
                     'Labor readiness does not follow its native save and same-city reopening')
            files.screen(payload.get('screen'))
            labor_ready=payload
            if labor_refresh['purpose']=='verify_labor':city_pending=None
            labor_refresh=None
        elif kind == 'city_labor_refresh_failed':
            _require(labor_refresh is not None and not labor_refresh.get('failed')
                     and payload.get('decision')==labor_refresh['decision']
                     and payload.get('purpose')==labor_refresh['purpose']
                     and isinstance(payload.get('reason'),str) and 0<len(payload['reason'])<=1000,
                     'Labor refresh failure has no matching active transaction')
            labor_refresh['failed']=True
            identifier=labor_refresh['decision']
            if identifier in labor_outcomes:labor_outcomes[identifier]['refresh_failed']=True
            labor_failures.append(dict(decision=identifier,purpose=labor_refresh['purpose'],
                status='failed',native_result_status=labor_outcomes.get(identifier,{}).get('status','unobserved')))
        elif kind == 'mechanical_input' and city_pending is not None:
            city_pending['mechanical'].append(payload)
        elif kind == 'city_control_review_completed':
            _require(city_pending is not None and payload.get('decision')==city_pending['decision'],
                     'City review has no matching pending control dispatch')
            action = city_pending['action']; observed = payload.get('observed_dialog')
            _require(action['id'] in ('change_production','open_buy_quote')
                     and payload.get('action_id')==action['id'] and isinstance(observed,dict)
                     and observed.get('kind')==action['parameters']['expected_screen'],
                     'City review does not match the opened native transaction')
            files.screen(observed.get('sha256')); files.screen(payload.get('completion_screen'))
            response_id = payload.get('response_decision')
            if response_id is None:
                _require(action['id']=='open_buy_quote' and observed.get('resource_tag')=='COMPLETE0',
                         'Only an information-only native quote may finish without a separate model choice')
                acknowledgements = [r for r in city_pending['mechanical']
                                    if r.get('label')=='acknowledge_information' and r.get('before')==observed['sha256']]
                _require(len(acknowledgements)==1, 'Information-only quote has no unique mechanical acknowledgement')
                events_in = _inputs(acknowledgements[0].get('inputs'))
                _require([(r.get('type'),r.get('code'),r.get('down')) for r in events_in]
                         == [('key','Enter',True),('key','Enter',False)],
                         'Information-only quote acknowledgement contains unrelated input')
            else:
                response = decisions.get(response_id,{})
                _require(_int(response_id,1) and response_id in dispatched
                         and response_id > city_pending['decision'] and response.get('question')=='dialog_action'
                         and response.get('action',{}).get('preconditions',{}).get('image_sha256')==observed['sha256'],
                         'City review response is not a separate dispatched choice for its observed dialog')
                if action['id']=='open_buy_quote':
                    _require(observed.get('resource_tag')=='COMPLETE1', 'Purchase quote lacks the original separate-choice resource')
                    _purchase_quote(started[response_id].get('state',{}).get('mandatory_dialog',{}).get('quote'))
            _city_review_binding(action,payload.get('reviewed'),completed=True)
            city_reviews += 1; city_pending = None
        elif kind == 'city_control_closed':
            _require(city_pending is not None and city_pending['action']['id']=='exit_city'
                     and payload.get('decision')==city_pending['decision'] and payload.get('action_id')=='exit_city',
                     'City closure has no matching Exit dispatch')
            action = city_pending['action']
            _require(payload.get('city')=={'id':action['actor']['id'],'name':action['actor']['name'],
                                          'year_raw':action['preconditions']['year_raw']},
                     'City closure belongs to another city or year')
            files.screen(payload.get('completion_screen'))
            city_closures += 1; city_pending = None
        elif kind == 'graphics_preferences_configured':
            _graphics_preferences(payload.get('receipt'),files)
            graphics_reviews += 1
        elif kind == 'native_presentation_acknowledged':
            inputs+=_presentation(payload,files,observed_screens)
            presentation_acknowledgments+=1
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
                          'forced_city_exit_dispatches':forced_city,
                          'completed_city_reviews':city_reviews, 'closed_city_controls':city_closures,
                          'graphics_preference_reviews':graphics_reviews,
                          'native_presentation_acknowledgments':presentation_acknowledgments,
                          'reused_native_checkpoints':checkpoint_reuses,
                          'city_labor_results':[labor_outcomes[k] for k in sorted(labor_outcomes)],
                          'city_labor_refresh_failures':labor_failures,
                          'city_labor_review_note':'Per-city/year dispatched input allowance checked. Omitted options are not claimed illegal; labor outcomes are only the recorded native bitmap/specialist comparison, not yield gains.',
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
                             'pending_city_control':city_pending is not None or forced_city_pending is not None,
                             'pending_labor_refresh':labor_refresh is not None,
                             'release_review_ready': complete and recording['ffprobe']['status'] == 'passed'
                              and outcome['status'] == 'human_reviewed' and len(dispatched) == len(decisions)
                              and len(started) == len(decisions)+len(plans) and forced_pending is None and not recoveries
                              and city_pending is None and forced_city_pending is None and labor_refresh is None},
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
