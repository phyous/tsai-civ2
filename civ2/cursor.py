"""Observed Windows 3.1 cursor feedback over ordinary DOSBox mouse events.

Windows processes the emulated PS/2 motion relatively, with acceleration. SDL's
absolute canvas coordinate is therefore not the guest cursor coordinate. Every
click below verifies the actual original arrow in a fresh game screenshot first.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import math
from pathlib import Path
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
REPAINT_DELAYS = (.055, .11, .19)
REPAINT_DIRECTORY = Path(__file__).resolve().parents[1]/'.runtime/cursor-repaints'


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


def _repaint_frame(data, status):
    """Keep original diagnostic pixels privately; these are not model evidence."""
    digest=hashlib.sha256(data).hexdigest()
    REPAINT_DIRECTORY.mkdir(parents=True,exist_ok=True)
    path=REPAINT_DIRECTORY/(digest+'.png')
    if not path.exists():path.write_bytes(data)
    return {'frame_digest':digest,'status':status}


def _observe(game, *, diagnostics=None):
    """Wait briefly for a unique exact arrow when dirty rectangles overlap.

    A modern frame can briefly contain both old and new cursor pixels. No
    additional input is issued here; persistent ambiguity still fails closed.
    """
    frames=[]
    for attempt in range(len(REPAINT_DELAYS)+1):
        data=game.request('/bridge/capture/game',binary=True)
        try:
            with Image.open(BytesIO(data)) as image:cursor=locate_cursor(image)
        except CursorError as error:
            ambiguous=str(error)=='More than one original Windows arrow is visible'
            if ambiguous or frames:
                frames.append(_repaint_frame(data,'ambiguous' if ambiguous else 'unresolved'))
            if ambiguous and attempt<len(REPAINT_DELAYS):
                time.sleep(REPAINT_DELAYS[attempt]);continue
            error.frame=data
            error.repaint_frames=frames
            if diagnostics is not None:diagnostics.extend(frames)
            raise
        if frames:
            frames.append(_repaint_frame(data,'unique'))
            if diagnostics is not None:diagnostics.extend(frames)
        return cursor


def locate_clipped_cursor(image: Image.Image, *, minimum_visible=85) -> tuple[int, int]:
    """Recognize a substantial exact arrow fragment only at a canvas edge.

    This never authorizes a click. Its sole use is moving away from the edge,
    after which the complete original arrow must be observed again.
    """
    if image.size != (640, 480):
        raise CursorError('Expected the original 640x480 game image')
    if minimum_visible not in (44,85):
        raise ValueError('Only calibrated original arrow-fragment thresholds are supported')
    pixels = image.convert('RGB').load()
    candidates = []
    for y in range(473 if minimum_visible==44 else 469):
        for x in range(633):
            if x <= 627 and y <= 460:
                continue
            visible = [(dx,dy,value) for dx,dy,value in CONSTRAINTS
                       if x+dx < 640 and y+dy < 480]
            if len(visible) < minimum_visible or pixels[x,y] != (0,0,0):
                continue
            if all(pixels[x+dx,y+dy] == value for dx,dy,value in visible):
                candidates.append((x,y))
                if len(candidates) > 1:
                    raise CursorError('Clipped original arrow is ambiguous')
    if len(candidates) != 1:
        raise CursorError('No sufficiently complete clipped original arrow is visible')
    return candidates[0]


def _initial_observe(game, inputs, diagnostics=None):
    try:
        return _observe(game,diagnostics=diagnostics),None
    except CursorError as error:
        if str(error) != 'The original Windows arrow is not fully visible':raise
        data=error.frame
    try:
        with Image.open(BytesIO(data)) as image:
            minimum_visible=85
            try:
                clipped = locate_clipped_cursor(image)
            except CursorError as error:
                if str(error)!='No sufficiently complete clipped original arrow is visible':raise
                # Original010/38 retained exactly44 head pixels at y472.
                # This weaker edge-only proof permits a pointer retreat only;
                # the full unique arrow remains mandatory before any click.
                minimum_visible=44
                clipped=locate_clipped_cursor(image,minimum_visible=minimum_visible)
    except CursorError as error:
        error.frame=data
        raise
    delta = (-8 if clipped[0] > 627 else 0, -8 if clipped[1] > 460 else 0)
    inputs.append(game.rpc('moveRelative', *delta))
    time.sleep(.1)
    restored = _observe(game,diagnostics=diagnostics)  # Full arrow is mandatory before any click.
    return restored, {'clipped_cursor':list(clipped), 'delta':list(delta),
                      'restored_full_cursor':list(restored), 'button_pressed':False,
                      'fragment_minimum_pixels':minimum_visible}


def _move(game, x: int, y: int, button: int = 0, *, tolerance: int = 3, press: bool = True, timeout: float = 20, _trace=None) -> dict:
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
    host = diagnostic.get('lastMouse') or diagnostic.get('hostMouse') or diagnostic.get('sdlMouse')
    if not isinstance(host, dict) or any(type(host.get(axis)) is not int for axis in ('x', 'y')):
        raise CursorError('Current emulator mouse coordinates are unavailable')
    host_x, host_y = host['x'], host['y']
    if not 0 <= host_x < 640 or not 0 <= host_y < 480:
        raise CursorError('Current emulator mouse coordinates are outside the canvas')
    gains = [INITIAL_GAIN, INITIAL_GAIN]
    trace=_trace if _trace is not None else {'inputs':[],'checkpoints':[],'cursor_repaints':[]}
    inputs, checkpoints, repaints = trace['inputs'],trace['checkpoints'],trace['cursor_repaints']
    step_edges=trace.setdefault('post_step_edge_recoveries',[])
    deadline = time.monotonic() + timeout
    cursor, edge_recovery = _initial_observe(game, inputs, repaints)
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
            value=max(-32,min(32,value))
            # Windows accelerates larger relative requests: a measured gain
            # from a 2-pixel request cannot safely size a 12-pixel edge step.
            # Keep edge-directed motion small and reobserve every step.
            margin=([627,460][index]-cursor[index]) if value>0 else cursor[index]
            if margin<=32:
                limit=1 if margin<=8 else 2
                value=max(-limit,min(limit,value))
            delta.append(value)
        actual_delta = tuple(delta)
        if actual_delta == (0, 0):
            raise CursorError('Cursor movement is below the supported resolution')
        inputs.append(game.rpc('moveRelative', *actual_delta))
        time.sleep(.045)
        recovery=None
        try:
            after = _observe(game,diagnostics=repaints)
        except CursorError as error:
            if str(error)!='The original Windows arrow is not fully visible' or len(step_edges)>=2:
                raise
            # Native acceleration can clip the arrow after a measured move,
            # not just at entry. The same exact partial-raster proof must
            # restore a full arrow before another movement or any button.
            after,recovery=_initial_observe(game,inputs,repaints)
            if recovery is not None:step_edges.append({'after_step':step+1,**recovery})
        # Permit a slow original frame, with no second input until it is observed.
        for _ in range(3):
            if after != cursor:
                break
            time.sleep(.065)
            after = _observe(game,diagnostics=repaints)
        if after == cursor:
            raise CursorError('Original guest cursor did not acknowledge mouse movement')
        for index in range(2):
            if recovery is not None:
                # The recovery moved too: its net displacement cannot measure
                # the gain of the original step. Restart conservatively.
                gains[index]=INITIAL_GAIN
                continue
            if actual_delta[index]:
                gain = (after[index] - cursor[index]) / actual_delta[index]
                if math.isfinite(gain) and .25 <= gain <= 8:
                    gains[index] = gain
        position_diagnostics = game.rpc('inputDiagnostics')
        host_position = position_diagnostics.get('hostMouse') or position_diagnostics.get('sdlMouse')
        if (not isinstance(host_position,dict) or any(type(host_position.get(axis)) is not int for axis in ('x','y'))
                or not 0<=host_position['x']<640 or not 0<=host_position['y']<480):
            raise CursorError('Current emulator mouse coordinates are unavailable')
        host_x, host_y, cursor = host_position['x'], host_position['y'], after
    # No further mousemove here: SDL canvas positions are not guest positions.
    if press:
        trace['button_down_attempted']=True
        try:
            inputs.append(game.rpc('mouse', {'type':'mousedown','x':host_x,'y':host_y,'button':button}))
            time.sleep(.09)
        finally:
            inputs.append(game.rpc('mouse', {'type':'mouseup','x':host_x,'y':host_y,'button':button}))
    return {'issued': press, 'target':[x,y], 'observed_cursor':list(cursor),
            'tolerance':tolerance,'movement_steps':len(checkpoints)-1,
            'checkpoints':checkpoints, 'inputs':inputs,
            **({'cursor_repaints':repaints} if repaints else {}),
            **({'edge_recovery':edge_recovery} if edge_recovery else {}),
            **({'post_step_edge_recoveries':step_edges} if step_edges else {})}


def move_and_click(game, x: int, y: int, button: int = 0, *, tolerance: int = 3, timeout: float = 20) -> dict:
    trace={'inputs':[],'checkpoints':[],'cursor_repaints':[],'button_down_attempted':False}
    try:
        return _move(game,x,y,button,tolerance=tolerance,timeout=timeout,_trace=trace)
    except Exception as error:
        # Preserve actual returned receipts even when a later capture or RPC
        # fails. A button attempt without an acknowledged completion is
        # explicitly uncertain, never silently reported as no click.
        error.cursor_receipt={'issued':None if trace['button_down_attempted'] else False,
            'status':'failed','target':[x,y],'tolerance':tolerance,
            'error':str(error),'error_type':type(error).__name__,**trace}
        raise


def move_cursor(game, x: int, y: int, *, tolerance: int = 3) -> dict:
    """Move with original-image feedback; never press a mouse button."""
    trace={'inputs':[],'checkpoints':[],'cursor_repaints':[]}
    try:
        return _move(game,x,y,tolerance=tolerance,press=False,_trace=trace)
    except CursorError as error:
        # A failed observation can follow real relative motion. Preserve every
        # returned input receipt; failure must never be reported as no input.
        error.cursor_receipt={'issued':False,'status':'failed','target':[x,y],
            'tolerance':tolerance,'error':str(error),**trace}
        raise
