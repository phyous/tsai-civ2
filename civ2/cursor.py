"""Observed Windows 3.1 cursor feedback over ordinary DOSBox mouse events.

Windows processes the emulated PS/2 motion relatively, with acceleration. SDL's
absolute canvas coordinate is therefore not the guest cursor coordinate. Every
click below verifies the actual original arrow in a fresh game screenshot first.
"""
from __future__ import annotations

from io import BytesIO
import math
import time
from PIL import Image


# Original white Windows 3.1 arrow, sampled from the unchanged rendered cursor.
# B/W are exact black/white pixels; dots are transparent, unconstrained background.
ARROW = (
    'BB...........', 'BWB..........', 'BWWB.........', 'BWWWB........',
    'BWWWWB.......', 'BWWWWWB......', 'BWWWWWWB.....', 'BWWWWWWWB....',
    'BWWWWWWWWB...', 'BWWWWWWWWWB..', 'BWWWWWWBBBBB.', 'BWWWBWWB.....',
    'BWWBBWWB.....', 'BWB.BBWWB....', 'BB...BWWB....', 'B.....BWWB...',
    '......BWWB...', '.......BWWB..', '.......BWWB..', '........BB...',
)
CONSTRAINTS = tuple((x, y, (0, 0, 0) if char == 'B' else (255, 255, 255))
                    for y, row in enumerate(ARROW) for x, char in enumerate(row) if char != '.')


class CursorError(RuntimeError):
    pass


def locate_cursor(image: Image.Image) -> tuple[int, int]:
    """Return the exact original arrow hotspot; ambiguous/absent arrows fail closed."""
    if image.size != (640, 480):
        raise CursorError('Expected the original 640x480 game image')
    pixels = image.convert('RGB').load()
    candidates = []
    black, white = (0, 0, 0), (255, 255, 255)
    for y in range(480 - len(ARROW) + 1):
        for x in range(640 - len(ARROW[0]) + 1):
            if pixels[x, y] != black or pixels[x + 1, y] != black or pixels[x + 1, y + 1] != white:
                continue
            if all(pixels[x + dx, y + dy] == value for dx, dy, value in CONSTRAINTS):
                candidates.append((x, y))
                if len(candidates) > 1:
                    raise CursorError('More than one original Windows arrow is visible')
    if not candidates:
        raise CursorError('The original Windows arrow is not fully visible')
    return candidates[0]


def _observe(game):
    data = game.request('/bridge/capture/game', binary=True)
    with Image.open(BytesIO(data)) as image:
        return locate_cursor(image)


def move_and_click(game, x: int, y: int, button: int = 0, *, tolerance: int = 3) -> dict:
    """Position by visual feedback, then press/release without extra motion.

    Returns ordinary input receipts plus each observed cursor checkpoint. Raises
    before button-down if the cursor cannot be located or the bounded movement
    does not converge. Hourglass/I-beam cursors require keyboard navigation.
    """
    if type(x) is not int or type(y) is not int or not 0 <= x <= 627 or not 0 <= y <= 460:
        raise ValueError('Target must keep the complete original arrow inside the game image')
    if type(button) is not int or button not in (0, 1, 2):
        raise ValueError('Invalid mouse button')
    if type(tolerance) is not int or not 0 <= tolerance <= 4:
        raise ValueError('Cursor tolerance must be at most four original pixels')
    diagnostic = game.rpc('inputDiagnostics')
    if diagnostic.get('paused'):
        raise CursorError('Resume the original runtime before positioning its cursor')
    host = diagnostic.get('lastMouse') or diagnostic.get('sdlMouse')
    if not isinstance(host, dict) or any(type(host.get(axis)) is not int for axis in ('x', 'y')):
        raise CursorError('Current emulator mouse coordinates are unavailable')
    host_x, host_y = host['x'], host['y']
    if not 0 <= host_x < 640 or not 0 <= host_y < 480:
        raise CursorError('Current emulator mouse coordinates are outside the canvas')
    gains = [1.0, 1.0]
    inputs, checkpoints = [], []
    deadline = time.monotonic() + 20
    cursor = _observe(game)
    for step in range(81):
        checkpoints.append({'cursor': list(cursor), 'host': [host_x, host_y]})
        error = (x - cursor[0], y - cursor[1])
        if max(map(abs, error)) <= tolerance:
            break
        if step == 80 or time.monotonic() >= deadline:
            raise CursorError('Observed cursor did not reach the target within the movement budget')
        delta = []
        for index in range(2):
            value = round(error[index] / gains[index])
            if value == 0 and abs(error[index]) > 2:
                value = 1 if error[index] > 0 else -1
            delta.append(max(-12, min(12, value)))
        actual_delta = tuple(delta)
        if actual_delta == (0, 0):
            raise CursorError('Cursor movement is below the supported resolution')
        inputs.append(game.rpc('moveRelative', *actual_delta))
        time.sleep(.045)
        after = _observe(game)
        # Permit a slow original frame, with no second input until it is observed.
        for _ in range(3):
            if after != cursor:
                break
            time.sleep(.065)
            after = _observe(game)
        if after == cursor:
            raise CursorError('Original guest cursor did not acknowledge mouse movement')
        for index in range(2):
            if actual_delta[index]:
                gain = (after[index] - cursor[index]) / actual_delta[index]
                if math.isfinite(gain) and .25 <= gain <= 8:
                    gains[index] = gain
        host_position = game.rpc('inputDiagnostics')['sdlMouse']
        host_x, host_y, cursor = host_position['x'], host_position['y'], after
    # No further mousemove here: SDL canvas positions are not guest positions.
    try:
        inputs.append(game.rpc('mouse', {'type':'mousedown','x':host_x,'y':host_y,'button':button}))
        time.sleep(.09)
    finally:
        inputs.append(game.rpc('mouse', {'type':'mouseup','x':host_x,'y':host_y,'button':button}))
    return {'issued': True, 'target':[x,y], 'observed_cursor':list(cursor),
            'tolerance':tolerance,'movement_steps':len(checkpoints)-1,
            'checkpoints':checkpoints, 'inputs':inputs}
