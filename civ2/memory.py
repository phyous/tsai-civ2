"""Read-only original Win16 observations, with no native game-save operation.

The pinned helper reads fixed original serializer regions through TOOLHELP.
Capsules retain compressed authentic wire snapshots for independent validation.
Only the same conservative owned/explored projection as native saves is public.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import struct
import time
import zlib

from .save import parse_save, SaveFormatError, MAP_OFFSET

EXE_SHA256 = 'b5a64ecbd8ebdd37e3ca2391c57319fec7ac227fcd2c3b9c96498969ea51ef96'
HELPER_SHA256 = 'b2ca27df1f3c15d6cdbcc8411be761e4d96fd018425bc23c65df329490432236'
WIRE_SIZE = 524288
FORMAT = 'civ2-live-memory-v1'
_SHA = re.compile(r'[0-9a-f]{64}')
_NONCE = re.compile(r'[0-9a-f]{32}')


class MemoryObservationError(ValueError):
    """Missing, changing, unsupported, or unbound original observation."""


def _require(condition, message):
    if not condition:
        raise MemoryObservationError(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, 'Duplicate observation field')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(MemoryObservationError('Nonfinite JSON')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MemoryObservationError('Invalid observation JSON') from exc


def map_topology(tree):
    """Validate the complete calibrated original640x480 map window layout.

    This is additional modal/occlusion evidence; painted turn-status OCR remains
    independently required by the runner. Extra child windows fail closed.
    """
    _require(isinstance(tree, dict) and type(tree.get('version')) is int and tree['version'] == 1
             and tree.get('status') == 'observed'
             and tree.get('stable_active') is True and tree.get('overflow') is False
             and tree.get('root_count') == 1, 'Native topology is unavailable or changing')
    root, task = tree.get('root'), tree.get('game_task')
    _require(type(root) is int and 0 < root < 65536 and type(task) is int and 0 < task < 65536
             and tree.get('active') == root and tree.get('active_task') == task,
             'Original Civ2 map is not foreground')
    windows = tree.get('windows')
    _require(isinstance(windows, list) and len(windows) == 6, 'Unexpected map window or overlay')
    by_id = {}
    for window in windows:
        _require(isinstance(window, dict), 'Invalid native window')
        handle = window.get('hwnd')
        _require(type(handle) is int and 0 < handle < 65536 and handle not in by_id,
                 'Invalid or duplicate native window identity')
        by_id[handle] = window
        _require(window.get('task') == task and window.get('foreign_above_root') == 0
                 and window.get('enabled') == 1 and window.get('root_related') == 1,
                 'Map ownership, visibility, or enabled state differs')
    main = by_id.get(root, {})
    _require(main.get('top') == 1 and main.get('class') == 'MSWindowClass'
             and main.get('rect') == [-4, -4, 644, 484], 'Original main window differs')
    panes = [w for w in windows if w.get('parent') == root]
    expected = {(0, 38, 462, 480), (462, 38, 640, 174), (462, 175, 640, 480)}
    _require(len(panes) == 3 and all(w.get('class') == 'MSWindowClass' and w.get('top') == 0
                                   and w.get('center_exposed') == 1 for w in panes)
             and {tuple(w.get('rect', [])) for w in panes} == expected, 'Original map pane layout absent')
    map_pane = next(w['hwnd'] for w in panes if w['rect'] == [0, 38, 462, 480])
    controls = [w for w in windows if w['hwnd'] != root and w not in panes]
    _require(len(controls) == 2 and all(w.get('parent') == map_pane and w.get('top') == 0
                                      and w.get('class') == 'MSControlClass' for w in controls)
             and {tuple(w.get('rect', [])) for w in controls} == {(9, 43, 27, 61), (29, 43, 47, 61)},
             'Unexpected original map child control')
    grid = tree.get('hit_grid')
    _require(isinstance(grid, list) and len(grid) == 63, 'Incomplete native hit-test coverage')
    for index, hit in enumerate(grid):
        _require(isinstance(hit, list) and len(hit) == 4
                 and hit[:2] == [min(639, 16 + 76 * (index % 9)), min(479, 44 + 70 * (index // 9))]
                 and hit[2] in by_id and hit[3] == task, 'Native map is occluded')
    return tree


def decode_wire(raw, expected_nonce=None):
    """Validate a complete fixed helper envelope, original pointers and owners."""
    _require(isinstance(raw, bytes) and len(raw) == WIRE_SIZE, 'Incomplete native observer envelope')
    header = raw[:128]
    match = re.match(rb'C2OBS2 ([0-9a-f]{32}) (\d+) (\d+) (\d+) (\d+) ([0-9a-f]{8})\n', header)
    _require(match is not None and header[match.end():] == b' ' * (128-match.end()), 'Invalid observer header')
    nonce = match[1].decode()
    _require(expected_nonce is None or expected_nonce == nonce, 'Stale observer response')
    ticks, module, task, size = map(int, match.group(2, 3, 4, 5))
    _require(0 <= ticks <= 0xffffffff and 0 < module < 65536 and 0 < task < 65536
             and 1 <= size <= 500000, 'Invalid native observer bounds')
    payload = raw[128:128+size]
    checksum = 2166136261
    for byte in payload:
        checksum = ((checksum ^ byte) * 16777619) & 0xffffffff
    _require(checksum == int(match[6], 16), 'Observer payload checksum differs')
    footer = b'\nEND2 ' + nonce.encode() + b'\n'
    end = 128 + size
    _require(raw[end:end+len(footer)] == footer and raw[end+len(footer):] == b' ' * (WIRE_SIZE-end-len(footer)),
             'Observer footer or padding is incomplete')
    at = 0
    def line():
        nonlocal at
        stop = payload.find(b'\n', at)
        _require(at <= stop < at+160, 'Invalid observer record header')
        value = payload[at:stop].split(); at = stop+1
        return value
    def block(length):
        nonlocal at
        _require(type(length) is int and 0 < length <= 196602 and at+length < len(payload), 'Invalid observer region length')
        value = payload[at:at+length]; at += length
        _require(payload[at:at+1] == b'\n', 'Truncated observer region'); at += 1
        return value
    parts = line()
    _require(len(parts) == 2 and parts[0] == b'TREE' and parts[1].isdigit(), 'Missing native topology')
    _require(0 < int(parts[1]) < 24000, 'Native topology exceeds helper bound')
    tree = _json(block(int(parts[1])))
    map_topology(tree)
    _require(tree.get('nonce') == nonce and tree.get('game_task') == task, 'Topology and memory owner differ')
    segments, maps = {}, {}
    try:
        for seg in (77, 78, 80):
            parts = line()
            _require(len(parts) == 7 and parts[0] == b'SEG', 'Missing fixed module segment')
            number, handle, selector, kind, length, owner = map(int, parts[1:])
            _require(number == seg and kind == 2 and owner == module and 0 < handle < 65536
                     and 0 < selector < 65536 and 0 < length <= 65536, 'Module allocation owner or bounds differ')
            segments[seg] = dict(handle=handle, selector=selector, owner=owner, data=block(length))
        state, map_data = segments[78]['data'], segments[80]['data']
        _require(len(state) >= 0x8ca2 and len(map_data) >= 0x50 and len(segments[77]['data']) >= 0xe0b0,
                 'Original static allocations are incomplete')
        human = state[0x8b81]
        width, height, area, _, _, locator_x, locator_y = struct.unpack_from('<7H', map_data)
        _require(1 <= human <= 7 and 8 <= width <= 512 and width % 2 == 0 and 8 <= height <= 512
                 and area == width*height//2 and area <= 32767
                 and locator_x == (width+3)//4 and locator_y == (height+3)//4, 'Invalid observed map dimensions')
        for label, size, pointer in ((0, 6*area, 0x18), (human, area, 0x2c+4*human)):
            parts = line()
            _require(len(parts) == 8 and parts[0] == b'MAP', 'Missing original map allocation')
            found, handle, selector, owner, offset, allocation, length = map(int, parts[1:])
            _require(found == label and owner == task and 0 < handle < 65536 and 0 < selector < 65536
                     and length == size and 0 <= offset < 65536 and offset+length <= allocation <= 196608
                     and struct.unpack_from('<HH', map_data, pointer) == (offset, selector),
                     'Original map pointer, allocation, or task owner differs')
            maps[label] = dict(handle=handle, selector=selector, owner=owner, offset=offset, data=block(length))
    except (ValueError, struct.error) as exc:
        if isinstance(exc, MemoryObservationError): raise
        raise MemoryObservationError('Invalid observer record') from exc
    _require(at == len(payload), 'Unexpected observer payload records')
    unit_count, city_count = struct.unpack_from('<HH', state, 0x8b94)
    _require(unit_count <= 2048 and city_count <= 256, 'Original actor array count exceeds bounds')
    regions = dict(header=state[0x8b66:0x8ca2], names=state[0x5400:0x5b90],
                   civilizations=state[0x5fc6:0x8b66],
                   units=segments[77]['data'][0x10b0:0x10b0+26*unit_count],
                   cities=state[:84*city_count], map_header=map_data[:14],
                   terrain=maps[0]['data'], knowledge=maps[human]['data'])
    return dict(nonce=nonce, ticks=ticks, module=module, task=task, tree=tree, regions=regions,
                wire_sha256=_sha(raw), human=human)


def _inflate(encoded):
    _require(isinstance(encoded, str) and len(encoded) <= 710000, 'Oversized compressed observation')
    try:
        compressed = base64.b64decode(encoded, validate=True)
        inflater = zlib.decompressobj()
        raw = inflater.decompress(compressed, WIRE_SIZE+1)
    except (ValueError, zlib.error) as exc:
        raise MemoryObservationError('Invalid compressed observer bytes') from exc
    _require(len(raw) == WIRE_SIZE and inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail,
             'Compressed observation size or stream differs')
    return raw


def _save_inventory(value):
    _require(isinstance(value, list) and len(value) <= 4096, 'Invalid original save inventory')
    result = []
    for item in value:
        _require(isinstance(item, dict) and set(item) in ({'name', 'size', 'modifiedAt'},
                 {'name', 'size', 'modifiedAt', 'sha256'}), 'Invalid save inventory entry')
        content_hashed = 'sha256' in item
        _require(not content_hashed or (item['modifiedAt'] is None and isinstance(item['sha256'],str)
                 and re.fullmatch(r'[a-f0-9]{64}',item['sha256'])), 'Invalid content-hashed save inventory')
        name, size, modified = item['name'], item['size'], item['modifiedAt']
        _require(isinstance(name, str) and 1 <= len(name) <= 255 and name.lower().endswith('.sav')
                 and not any(c in name for c in ('/', '\\', '\0'))
                 and type(size) is int and 0 <= size <= 16777216
                 and (content_hashed or (isinstance(modified, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z', modified))),
                 'Save inventory metadata is unavailable or malformed')
        result.append(dict(item))
    result.sort(key=lambda item: item['name'])
    _require(len({item['name'].casefold() for item in result}) == len(result), 'Ambiguous native save names')
    return result


def _inventory_changes(before, after):
    old = {entry['name']:entry for entry in before}
    new = {entry['name']:entry for entry in after}
    return [dict(name=name, before=old.get(name), after=new.get(name))
            for name in sorted(old.keys() | new.keys()) if old.get(name) != new.get(name)]


def _campaign_start(value, initial):
    if value is None:
        return None  # Constructor baseline, with no forgiven startup changes.
    _require(isinstance(value, dict) and set(value) == {'phase', 'startup_inventory', 'campaign_inventory', 'startup_changes', 'preferences_sha256'}
             and value['phase'] == 'after_verified_autosave_off_before_first_observation'
             and isinstance(value['preferences_sha256'], str) and _SHA.fullmatch(value['preferences_sha256']),
             'Invalid explicit campaign-start boundary')
    startup = _save_inventory(value['startup_inventory'])
    campaign = _save_inventory(value['campaign_inventory'])
    changes = _inventory_changes(startup, campaign)
    _require(campaign == initial and value['startup_changes'] == changes, 'Campaign inventory boundary differs')
    _require(all(re.fullmatch(r'[A-Za-z0-9_]{1,24}_AUTO\.SAV', change['name'], re.I)
                 and change['after'] is not None for change in changes),
             'Only original startup autosaves may precede the explicit campaign boundary')
    return value


def _validate_capsule(data):
    _require(isinstance(data, bytes) and 1 <= len(data) <= 1500000, 'Invalid observation capsule size')
    capsule = _json(data)
    _require(isinstance(capsule, dict) and set(capsule) == {'format', 'original_exe_sha256', 'helper_sha256', 'snapshots', 'proof'}
             and capsule['format'] == FORMAT and capsule['original_exe_sha256'] == EXE_SHA256
             and capsule['helper_sha256'] == HELPER_SHA256, 'Unsupported observation source')
    _require(_canonical(capsule) == data, 'Observation capsule is not canonical')
    proof = capsule['proof']
    proof_fields = {'input_sequence_before', 'input_sequence_after', 'image_sha256', 'elapsed_ms',
                    'save_inventory_initial', 'save_inventory_before', 'save_inventory_after', 'runtime_provenance'}
    _require(isinstance(proof, dict) and proof_fields <= set(proof)
             and set(proof) <= proof_fields | {'campaign_start', 'frame_images_identical'}, 'Unexpected freshness proof')
    _require(type(proof['input_sequence_before']) is int and proof['input_sequence_before'] >= 0
             and type(proof['input_sequence_after']) is int and proof['input_sequence_after'] == proof['input_sequence_before']
             and type(proof['elapsed_ms']) is int and 0 <= proof['elapsed_ms'] <= 60000, 'Ordinary input or invalid interval during observation')
    initial = _save_inventory(proof['save_inventory_initial'])
    _require(proof['save_inventory_initial'] == initial and _save_inventory(proof['save_inventory_before']) == initial
             and _save_inventory(proof['save_inventory_after']) == initial, 'Native save created or changed during final run')
    _campaign_start(proof.get('campaign_start'), initial)
    _require(proof['runtime_provenance'] == {'original_exe_sha256':EXE_SHA256, 'helper_sha256':HELPER_SHA256},
             'Actual guest source hashes differ from pinned observer')
    images = proof['image_sha256']
    _require(isinstance(images, list) and len(images) == 3 and all(isinstance(h, str) and _SHA.fullmatch(h) for h in images),
             'Three original frame hashes required')
    identical = len(set(images)) == 1
    if 'frame_images_identical' in proof:
        _require(proof['frame_images_identical'] is identical, 'Frame identity label differs from actual image hashes')
    else:
        _require(identical, 'Legacy observation required identical original frames')
    # Blinking sprites/status are presentation changes. State coherence is
    # established below by exact paired native regions+topology and no input.
    # This never grants permission to click or substitutes for fresh UI OCR.
    _require(isinstance(capsule['snapshots'], list) and len(capsule['snapshots']) == 2, 'Two native snapshots required')
    snapshots = []
    for item in capsule['snapshots']:
        _require(isinstance(item, dict) and set(item) == {'wire_zlib_base64', 'wire_sha256'}, 'Unexpected native snapshot fields')
        raw = _inflate(item['wire_zlib_base64'])
        _require(_sha(raw) == item['wire_sha256'], 'Native snapshot hash differs')
        snapshots.append(decode_wire(raw))
    first, second = snapshots
    _require(first['nonce'] != second['nonce'] and first['module'] == second['module'] and first['task'] == second['task'],
             'Snapshots are stale or native ownership changed')
    normalize = lambda tree: {k:v for k,v in tree.items() if k not in ('nonce', 'ticks')}
    _require(normalize(first['tree']) == normalize(second['tree']) and first['regions'] == second['regions'],
             'Original topology or game state changed during observation')
    return capsule, second


def parse_memory(data, rules_text=None, *, include_stack_links=False):
    """Return only owned/explored state from the exact canonical memory capsule."""
    capsule, snapshot = _validate_capsule(data)
    regions = snapshot['regions']
    width, height, area, _, _, lx, ly = struct.unpack('<7H', regions['map_header'])
    human = snapshot['human']
    unit_base = MAP_OFFSET+14+13*area+2*lx*ly+1024
    city_base = unit_base+len(regions['units'])
    # Internal field-layout adapter only: never written, recorded, or called a
    # native save. Unread minimap/view fields are absent; parser exposes no view.
    layout = bytearray(city_base+len(regions['cities']))
    layout[:12] = b'CIVILIZE\0\x1a\x27\x00'
    layout[12:328] = regions['header']; layout[328:2264] = regions['names']
    layout[2264:MAP_OFFSET] = regions['civilizations']
    layout[MAP_OFFSET:MAP_OFFSET+14] = regions['map_header']
    known = MAP_OFFSET+14+(human-1)*area
    layout[known:known+area] = regions['knowledge']
    terrain = MAP_OFFSET+14+7*area
    layout[terrain:terrain+6*area] = regions['terrain']
    layout[unit_base:city_base] = regions['units']; layout[city_base:] = regions['cities']
    try:
        state = parse_save(bytes(layout), rules_text=rules_text,include_stack_links=include_stack_links)
    except SaveFormatError as exc:
        raise MemoryObservationError(str(exc)) from exc
    old_evidence = state['evidence']
    state['evidence'] = dict(kind='live_memory', observation_sha256=_sha(data), observation_bytes=len(data),
                             classic_layout=True, original_exe_sha256=EXE_SHA256, helper_sha256=HELPER_SHA256,
                             year_semantics=old_evidence['year_semantics'],
                             foreign_units=old_evidence['foreign_units'], outcome='not inferred from memory; require original result UI',
                             source='Original Win16 ToolHelp read-only fixed serializer regions; no game save')
    return state


def capsule_from_wires(wires, *, image_sha256, input_sequence_before, input_sequence_after, elapsed_ms, save_inventory_initial, save_inventory_before, save_inventory_after, runtime_provenance, campaign_start=None):
    _require(isinstance(wires, (list, tuple)) and len(wires) == 2, 'Two native wire snapshots required')
    value = dict(format=FORMAT, original_exe_sha256=EXE_SHA256, helper_sha256=HELPER_SHA256,
                 snapshots=[dict(wire_zlib_base64=base64.b64encode(zlib.compress(w, 6)).decode(), wire_sha256=_sha(w)) for w in wires],
                 proof=dict(input_sequence_before=input_sequence_before, input_sequence_after=input_sequence_after,
                            image_sha256=list(image_sha256), elapsed_ms=elapsed_ms,
                            save_inventory_initial=_save_inventory(save_inventory_initial),
                            save_inventory_before=_save_inventory(save_inventory_before),
                            save_inventory_after=_save_inventory(save_inventory_after),
                            runtime_provenance=runtime_provenance, campaign_start=campaign_start,
                            frame_images_identical=len(set(image_sha256)) == 1))
    data = _canonical(value)
    _validate_capsule(data)
    return data


class LiveMemoryObserver:
    """Bounded native observer. No keys, clicks, save/import calls, or selection.

    The emulator runs only to service its hidden read-only helper. It is paused
    on return/error. Model decisions never receive the raw native capsule.
    """
    def __init__(self, game, directory, *, max_attempts=12, response_seconds=8):
        _require(type(max_attempts) is int and 1 <= max_attempts <= 32 and 0 < response_seconds <= 20,
                 'Invalid observer retry limits')
        self.game, self.directory = game, Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_attempts, self.response_seconds = max_attempts, response_seconds
        self.initial_save_inventory = _save_inventory(self.game.rpc('listSaves'))
        self.startup_save_inventory = self.initial_save_inventory
        self.campaign_start = None
        self._reads_started = False
        self.provenance = self.game.rpc('observerProvenance')
        _require(self.provenance == {'original_exe_sha256':EXE_SHA256, 'helper_sha256':HELPER_SHA256},
                 'Actual guest executable/helper does not match pinned read-only observer')

    def begin_campaign(self, preferences):
        """Explicit one-shot boundary after native Autosave-off, before play.

        Civ2 may write its startup autosave while creating the initial world.
        Record that exact delta; never reset the guard after observations start.
        """
        _require(not self._reads_started and self.campaign_start is None, 'Campaign inventory cannot be reset after observation begins')
        _require(isinstance(preferences, dict) and preferences.get('autosave_disabled') is True
                 and preferences.get('checkbox_after', {}).get('Autosave each turn') is False,
                 'Verified native Autosave-off receipt required before campaign begins')
        current = _save_inventory(self.game.rpc('listSaves'))
        value = dict(phase='after_verified_autosave_off_before_first_observation',
                     startup_inventory=self.startup_save_inventory, campaign_inventory=current,
                     startup_changes=_inventory_changes(self.startup_save_inventory, current),
                     preferences_sha256=_sha(_canonical(preferences)))
        _campaign_start(value, current)
        self.initial_save_inventory = current
        self.campaign_start = value
        return json.loads(json.dumps(value))

    def adopt_campaign_start(self, boundary):
        """Adopt a verified boot receipt across CLI processes, never rebaseline.

        The caller must validate its setup report first. Exact current inventory
        must still equal that report's campaign boundary; later saves cannot be
        forgiven by constructing a fresh observer instance.
        """
        _require(not self._reads_started and self.campaign_start is None,
                 'Campaign inventory cannot be reset after observation begins')
        _require(isinstance(boundary, dict), 'A verified explicit boot boundary is required')
        current = _save_inventory(self.game.rpc('listSaves'))
        _campaign_start(boundary, current)
        self.campaign_start = json.loads(json.dumps(boundary))
        self.startup_save_inventory = self.campaign_start['startup_inventory']
        self.initial_save_inventory = current
        return json.loads(json.dumps(self.campaign_start))

    def _read_wire(self, sequence):
        nonce = secrets.token_hex(16)
        request = self.game.rpc('observerRequest', nonce)
        _require(request.get('nonce') == nonce and request.get('inputSequence') == sequence
                 and request.get('gameInput') is False, 'Observer request was not a read-only query')
        deadline = time.monotonic()+self.response_seconds
        while time.monotonic() < deadline:
            try:
                result = self.game.rpc('readObserver')
            except RuntimeError:
                # The fixed mailbox can be absent/incomplete while the native
                # helper is writing it. A complete current-nonce envelope is
                # still required; a permanent bridge failure times out closed.
                time.sleep(.025)
                continue
            if result:
                try:
                    _require(result.get('encoding') == 'base64', 'Invalid observer bridge encoding')
                    raw = base64.b64decode(result['data'], validate=True)
                    decode_wire(raw, nonce)
                    return raw
                except (MemoryObservationError, ValueError, KeyError):
                    pass  # Only a complete response with this nonce can escape.
            time.sleep(.025)
        raise MemoryObservationError('No complete current map observation from native helper')

    def read(self, *, rules_text=None, include_stack_links=False, middle_settle=0.0):
        _require(type(middle_settle) in (int,float) and math.isfinite(middle_settle)
                 and 0 <= middle_settle <= .5, 'Invalid bounded middle-frame wait')
        last_error = None
        self._reads_started = True
        total_start = time.monotonic()
        try:
            self.game.rpc('resume')
            for attempt in range(self.max_attempts):
                start = time.monotonic(); sequence = self.game.rpc('status')['inputSequence']
                inventory_before = _save_inventory(self.game.rpc('listSaves'))
                _require(inventory_before == self.initial_save_inventory, 'Native save created or changed during final run')
                token = secrets.token_hex(8); paths = []; hashes = []; wires = []
                for index in range(3):
                    path = self.directory/f'memory-{token}-{index}.png'
                    self.game.capture(path); frame = path.read_bytes()
                    _require(frame[:8] == b'\x89PNG\r\n\x1a\n' and frame[16:24] == struct.pack('>II', 640, 480),
                             'Original observation must be640x480 PNG')
                    paths.append(str(path)); hashes.append(_sha(frame))
                    # Optional phase variation for a strict current-image map
                    # proof. No input is sent; native state/topology must still
                    # match on both sides of this longer image bracket.
                    if index == 1 and middle_settle:
                        time.sleep(middle_settle)
                    if index < 2: wires.append(self._read_wire(sequence))
                after = self.game.rpc('status')['inputSequence']
                inventory_after = _save_inventory(self.game.rpc('listSaves'))
                _require(inventory_after == self.initial_save_inventory, 'Native save created or changed during final run')
                try:
                    data = capsule_from_wires(wires, image_sha256=hashes, input_sequence_before=sequence,
                                              input_sequence_after=after, elapsed_ms=round(1000*(time.monotonic()-start)),
                                              save_inventory_initial=self.initial_save_inventory, save_inventory_before=inventory_before,
                                              save_inventory_after=inventory_after, runtime_provenance=self.provenance, campaign_start=self.campaign_start)
                    state = parse_memory(data, rules_text=rules_text,include_stack_links=include_stack_links)
                except MemoryObservationError as exc:
                    last_error = exc
                    _require(after == sequence, 'Ordinary input interrupted observation')
                    continue
                capsule, decoded = _validate_capsule(data)
                return dict(state=state, data=data, receipt=dict(kind='live_memory', nonce=decoded['nonce'],
                    native_ticks=decoded['ticks'], module=decoded['module'], task=decoded['task'],
                    observation_sha256=_sha(data), proof=capsule['proof'], source_images=paths,
                    region_sha256={k:_sha(v) for k,v in decoded['regions'].items()},
                    original_exe_sha256=EXE_SHA256, helper_sha256=HELPER_SHA256, attempts=attempt+1, total_elapsed_ms=round(1000*(time.monotonic()-total_start)),
                    campaign_start=self.campaign_start))
            raise MemoryObservationError('Original native state/topology did not stabilize within observation budget') from last_error
        finally:
            self.game.rpc('pause')
