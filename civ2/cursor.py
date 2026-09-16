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
# The original map uses a second18px arrow (005/1045 hotspot269,249).
# It shares the first9 rows, then has a shorter head and alternating-width stem.
# These are exact observed pixels, not a scaled or approximate cursor match.
MAP_ARROW = (
    'BB.........','BWB........','BWWB.......','BWWWB......',
    'BWWWWB.....','BWWWWWB....','BWWWWWWB...','BWWWWWWWB..',
    'BWWWWWWWWB.','BWWWWWBBBBB','BWWBBWB....','BWB.BWWB...',
    'BB...BWB...','B....BWWB..','......BWB..','......BWWB.',
    '.......BWB.','.......BB..',
)
MAP_CONSTRAINTS = tuple((x,y,(0,0,0) if char=='B' else (255,255,255))
                        for y,row in enumerate(MAP_ARROW) for x,char in enumerate(row) if char!='.')
# Start at the existing estimator's upper accepted gain until actual motion
# calibrates each axis. Starting at 1 made the observed Windows vertical gain 2
# overshoot near bottom controls and clip the cursor before any readback.
INITIAL_GAIN = 8.0


class CursorError(RuntimeError):
    pass


def locate_cursor(image: Image.Image) -> tuple[int, int]:
    """Return the exact original arrow hotspot; ambiguous/absent arrows fail closed."""
    if image.size != (640, 480):
        raise CursorError('Expected the original 640x480 game image')
    pixels = image.convert('RGB').load()
    candidates = []
    black, white = (0, 0, 0), (255, 255, 255)
    for shape,constraints in ((ARROW,CONSTRAINTS),(MAP_ARROW,MAP_CONSTRAINTS)):
        for y in range(480 - len(shape) + 1):
            for x in range(640 - len(shape[0]) + 1):
                if pixels[x, y] != black or pixels[x + 1, y] != black or pixels[x + 1, y + 1] != white:
                    continue
                if all(pixels[x + dx, y + dy] == value for dx, dy, value in constraints):
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


def locate_clipped_cursor(image: Image.Image) -> tuple[int, int]:
    """Recognize a substantial exact arrow fragment only at a canvas edge.

    This never authorizes a click. Its sole use is moving away from the edge,
    after which the complete original arrow must be observed again.
    """
    if image.size != (640, 480):
        raise CursorError('Expected the original 640x480 game image')
    pixels = image.convert('RGB').load()
    candidates = []
    for y in range(469):
        for x in range(633):
            if x <= 627 and y <= 460:
                continue
            visible = [(dx,dy,value) for dx,dy,value in CONSTRAINTS
                       if x+dx < 640 and y+dy < 480]
            if len(visible) < 85 or pixels[x,y] != (0,0,0):
                continue
            if all(pixels[x+dx,y+dy] == value for dx,dy,value in visible):
                candidates.append((x,y))
                if len(candidates) > 1:
                    raise CursorError('Clipped original arrow is ambiguous')
    if len(candidates) != 1:
        raise CursorError('No sufficiently complete clipped original arrow is visible')
    return candidates[0]


def _initial_observe(game, inputs):
    data = game.request('/bridge/capture/game', binary=True)
    with Image.open(BytesIO(data)) as image:
        try:
            return locate_cursor(image), None
        except CursorError as error:
            if str(error) != 'The original Windows arrow is not fully visible':
                raise
        clipped = locate_clipped_cursor(image)
    delta = (-8 if clipped[0] > 627 else 0, -8 if clipped[1] > 460 else 0)
    inputs.append(game.rpc('moveRelative', *delta))
    time.sleep(.1)
    restored = _observe(game)  # Full arrow is mandatory before any click.
    return restored, {'clipped_cursor':list(clipped), 'delta':list(delta),
                      'restored_full_cursor':list(restored), 'button_pressed':False}


def _move(game, x: int, y: int, button: int = 0, *, tolerance: int = 3, press: bool = True, timeout: float = 20) -> dict:
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
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 1 <= timeout <= 180:
        raise ValueError('Cursor deadline must be between one and 180 seconds')
    diagnostic = game.rpc('inputDiagnostics')
    if diagnostic.get('paused'):
        raise CursorError('Resume the original runtime before positioning its cursor')
    host = diagnostic.get('lastMouse') or diagnostic.get('sdlMouse')
    if not isinstance(host, dict) or any(type(host.get(axis)) is not int for axis in ('x', 'y')):
        raise CursorError('Current emulator mouse coordinates are unavailable')
    host_x, host_y = host['x'], host['y']
    if not 0 <= host_x < 640 or not 0 <= host_y < 480:
        raise CursorError('Current emulator mouse coordinates are outside the canvas')
    gains = [INITIAL_GAIN, INITIAL_GAIN]
    inputs, checkpoints = [], []
    deadline = time.monotonic() + timeout
    cursor, edge_recovery = _initial_observe(game, inputs)
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
            # Use the full bounded host-input range. Every step still requires
            # a freshly observed guest cursor before another move or click.
            delta.append(max(-32, min(32, value)))
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
    if press:
        try:
            inputs.append(game.rpc('mouse', {'type':'mousedown','x':host_x,'y':host_y,'button':button}))
            time.sleep(.09)
        finally:
            inputs.append(game.rpc('mouse', {'type':'mouseup','x':host_x,'y':host_y,'button':button}))
    return {'issued': press, 'target':[x,y], 'observed_cursor':list(cursor),
            'tolerance':tolerance,'movement_steps':len(checkpoints)-1,
            'checkpoints':checkpoints, 'inputs':inputs,
            **({'edge_recovery':edge_recovery} if edge_recovery else {})}


def move_and_click(game, x: int, y: int, button: int = 0, *, tolerance: int = 3, timeout: float = 20) -> dict:
    return _move(game,x,y,button,tolerance=tolerance,timeout=timeout)


def move_cursor(game, x: int, y: int, *, tolerance: int = 3) -> dict:
    """Move with original-image feedback; never press a mouse button."""
    return _move(game,x,y,tolerance=tolerance,press=False)
