"""Retain a freshly recorded final dashboard without restarting its recorder."""
import hashlib
from io import BytesIO
import json
import math
import time
from PIL import Image

METHOD = 'paused_game_bracket_and_recorded_dashboard_sha256_v1'


def _png(data, *, original=False):
    if not isinstance(data, bytes) or not 24 <= len(data) <= 16*1024*1024:
        raise RuntimeError('Final recording capture is invalid')
    with Image.open(BytesIO(data)) as image:
        if image.format != 'PNG' or (original and image.size != (640, 480)):
            raise RuntimeError('Final recording capture has invalid dimensions')
        image.verify()
    return hashlib.sha256(data).hexdigest()


def _paused(game, sequence=None):
    state = game.rpc('status')
    value = state.get('inputSequence')
    if (state.get('paused') is not True or state.get('heldKeys') != []
            or state.get('buttons') != 0 or type(value) is not int or value < 0
            or sequence is not None and value != sequence):
        raise RuntimeError('Final recording requires unchanged paused input state')
    return value


def validate_final_game(recorder, retained):
    sequence = retained['input_sequence']
    _paused(recorder.game, sequence)
    frame = recorder.game.request('/bridge/capture/game', binary=True)
    if _png(frame, original=True) != retained['game']['sha256']:
        raise RuntimeError('Final original game changed during recording finalization')
    _paused(recorder.game, sequence)


def _tail(path):
    # The existing recording thread flushes whole rows. Ignore an incomplete
    # last row, but never edit/reconstruct its append-only sample ledger.
    with path.open('rb') as source:
        source.seek(0, 2); size = source.tell(); source.seek(max(0, size-16384))
        raw = source.read()
    lines = raw.splitlines(keepends=True)
    if size > 16384: lines = lines[1:]
    return [json.loads(line) for line in lines if line.endswith(b'\n')]


def retain_final_sample(recorder, *, timeout=5):
    """Wait for the existing thread to record this exact current dashboard.

    No stop signal is sent on failure: the original recording remains active.
    Works with a thread already executing the older capture loop.
    """
    recorder.check()
    sequence = _paused(recorder.game)
    earliest_ms = math.ceil((time.monotonic()-recorder.started)*1000)
    original = recorder.game.request('/bridge/capture/game', binary=True)
    original_hash = _png(original, original=True)
    dashboard = recorder.game.request('/bridge/capture/dashboard', binary=True)
    dashboard_hash = _png(dashboard)
    proof = dict(method=METHOD, input_sequence=sequence,
                 game=dict(sha256=original_hash), dashboard=dict(sha256=dashboard_hash))
    validate_final_game(recorder, proof)
    deadline = time.monotonic()+timeout
    sample = None
    while time.monotonic() < deadline:
        recorder.check()
        if not recorder.thread.is_alive():
            raise RuntimeError('Recording ended before the final state was sampled')
        rows = _tail(recorder.directory/'frames.jsonl')
        matching = [row for row in rows if row.get('sha256') == dashboard_hash
                    and type(row.get('elapsed_ms')) is int and row['elapsed_ms'] >= earliest_ms]
        if matching:
            sample = matching[-1]
            break
        time.sleep(.05)
    if sample is None:
        raise RuntimeError('Current final dashboard was not observed in the recording')
    # Let at least one complete encoded-frame interval elapse in real time.
    # Do not append a fabricated future frame or time-compress the ending.
    time.sleep(max(0, (sample['frame']+1)/recorder.fps-(time.monotonic()-recorder.started)))
    validate_final_game(recorder, proof)
    attempt = getattr(recorder, '_final_capture_attempt', 0)+1
    recorder._final_capture_attempt = attempt
    for key, data in (('game', original), ('dashboard', dashboard)):
        name = f'final-{key}-{attempt:03d}.png'
        with (recorder.directory/name).open('xb') as output:
            output.write(data)
        proof[key].update(name=name, bytes=len(data))
    proof.update({key:sample[key] for key in ('sample','frame','elapsed_ms')})
    return proof
