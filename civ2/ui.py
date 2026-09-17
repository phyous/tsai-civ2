"""Observed original-game dialogs and ordinary-input housekeeping.

This module does not make strategy decisions. It opens native saves, enters
mechanical names and acknowledges explicitly recognized informational dialogs.
"""
from __future__ import annotations
import json
import difflib
import hashlib
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
import time
from .engine import Game
from .observe import recognize, find_text


def saved_notice(observation):
    # This original bitmap font sometimes OCRs saved as samed/saued. Match the
    # small modal's heading plus its leader/date body; the save file is still
    # read and independently parsed before it becomes state evidence.
    lines = [line['text'].casefold().strip(' .!|') for line in observation['lines']]
    heading = any(line.startswith('game sa') and
                  difflib.SequenceMatcher(None,line,'game saved').ratio() >= .8 for line in lines)
    return heading and any('of the romans' in line for line in lines)


class UI:
    def __init__(self, game=None, directory='.runtime/probes'):
        self.game = game or Game()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.counter = 0
        self.latest = None
        self._recognition_cache = OrderedDict()

    def observe(self, *, retain_unreadable=False):
        self.counter += 1
        path = self.directory / f'ui-{self.counter:07d}.png'
        self.game.capture(path)
        # Capture every time. Reuse only analysis of identical original PNG
        # bytes, never an old screen, path, cursor state or model decision.
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        executable = Path(__file__).resolve().parents[1]/'.runtime/ocr'
        stat = executable.stat() if executable.is_file() else None
        key = (digest, recognize, None if stat is None else
               (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        if not hasattr(self, '_recognition_cache'):
            self._recognition_cache = OrderedDict()
        cache = self._recognition_cache
        if key in cache:
            observation = deepcopy(cache[key])
            cache.move_to_end(key)
        else:
            try:
                observation = recognize(path)
            except ValueError as error:
                if not retain_unreadable or str(error) != 'Invalid normalized OCR geometry':
                    raise
                # An input may already have happened. Retain its actual after
                # frame so the caller can journal the returned input receipts;
                # unreadable pixels supply no text, controls or cursor target.
                captured = path.read_bytes()
                if hashlib.sha256(captured).hexdigest() != digest:
                    raise ValueError('Recognized image differs from captured screen') from error
                from io import BytesIO
                from PIL import Image
                with Image.open(BytesIO(captured)) as image:
                    if image.format != 'PNG':
                        raise ValueError('Captured screen is not a PNG') from error
                    image.load()
                    width, height = image.size
                observation = dict(width=width, height=height, sha256=digest,
                    path=str(path), lines=[], text='', ocr=dict(
                        unreadable_after_input=True, passes=[], conflicts=[],
                        fallback_errors=[dict(pass_name='recognize', error='ValueError',
                                              message=str(error))]))
                self.latest = observation
                return observation
            if observation.get('sha256') != digest:
                raise ValueError('Recognized image differs from captured screen')
            if not observation.get('ocr', {}).get('fallback_errors'):
                cache[key] = deepcopy(observation)
                while len(cache) > 16:
                    cache.popitem(last=False)
        observation['path'] = str(path)
        from .cursor import locate_cursor, CursorError
        from PIL import Image
        try:
            with Image.open(path) as image:
                observation['cursor_hotspot'] = list(locate_cursor(image))
        except CursorError:
            pass
        self.latest = observation
        return observation

    def key(self, code, *, settle=.25):
        receipts = self.game.key(code, holdMs=120)
        time.sleep(settle)
        return receipts

    def wait(self, predicate, *, timeout=8):
        deadline = time.monotonic() + timeout
        while True:
            try:
                observation = self.observe()
            except ValueError as error:
                # A partially painted startup frame can yield an OCR box
                # outside the image. It supplies no controls; await a new frame.
                if str(error) != 'Invalid normalized OCR geometry' or time.monotonic() >= deadline:
                    raise
                time.sleep(.1)
                continue
            if predicate(observation):
                return observation
            if time.monotonic() >= deadline:
                raise RuntimeError('Expected original-game screen did not appear')
            time.sleep(.2)

    def wait_text(self, text, *, timeout=8):
        return self.wait(lambda o: text.casefold() in o['text'].casefold(), timeout=timeout)

    def park_pointer(self):
        from .cursor import move_cursor, CursorError
        before=self.game.rpc('status')
        try:
            # The old lower-right point obscured the original herald message.
            # This observed title-bar corner keeps the complete arrow visible.
            return move_cursor(self.game,2,1,tolerance=1)
        except CursorError as error:
            after=self.game.rpc('status')
            receipt=dict(error.cursor_receipt)
            for label,state in (('before',before),('after',after)):
                receipt['input_sequence_'+label]=state.get('inputSequence')
                receipt['held_keys_'+label]=state.get('heldKeys')
                receipt['buttons_'+label]=state.get('buttons')
            if isinstance(getattr(error,'frame',None),bytes):
                import hashlib
                digest=hashlib.sha256(error.frame).hexdigest()
                (self.directory/('cursor-park-'+digest+'.png')).write_bytes(error.frame)
                receipt['failure_frame_sha256']=digest
            return receipt

    def select_text(self, observation, text, *, exact=False, confirm=False, timeout=20,
                    source_line=None, center=None):
        # The caller supplies the fresh screen containing this exact target.
        if self.latest is not observation:
            raise ValueError('Selection requires the latest observed screen')
        if source_line is None and center is None:
            point = find_text(observation, text, exact=exact)
        else:
            # A classified foreground control can share its label with map or
            # status text behind the dialog. Bind its original OCR row and
            # exact observed center instead of searching the whole image again.
            rows = observation.get('lines', [])
            if (not exact or type(source_line) is not int or
                    not 0 <= source_line < len(rows) or
                    not isinstance(center, (list, tuple)) or len(center) != 2 or
                    any(type(v) is not int for v in center)):
                raise ValueError('Selection requires an exact observed control row')
            row = rows[source_line]
            bounds = row.get('bounds')
            if (not isinstance(text, str) or row.get('text', '').strip() != text.strip() or
                    row.get('center') != list(center) or
                    not isinstance(bounds, (list, tuple)) or len(bounds) != 4 or
                    any(type(v) is not int for v in bounds)):
                raise ValueError('Selected control differs from its observed row')
            x, y, width, height = bounds
            if (width <= 0 or height <= 0 or x < 0 or y < 0 or
                    not x <= center[0] <= x + width or not y <= center[1] <= y + height or
                    not 0 <= center[0] < observation['width'] or
                    not 0 <= center[1] < observation['height']):
                raise ValueError('Selected control geometry is outside its source image')
            point = list(center)
        receipts = self.game.click(*point, timeout=timeout)
        time.sleep(.2)
        parking = self.park_pointer()
        selected = self.observe()
        if confirm:
            receipts += self.key('Enter')
        return {'target': text, 'point': point, 'before': observation['sha256'],
                'selected_frame': selected['sha256'], 'inputs': receipts, 'pointer_park':parking}

    def save_native(self, name):
        """Write through the original Save dialog, then read the resulting file."""
        import re
        if not re.fullmatch(r'[A-Za-z0-9_]{1,8}\.sav', name, re.I):
            raise ValueError('Use an ordinary DOS 8.3 save filename')
        self.game.rpc('resume')
        before = self.observe()
        self.game.chord('ControlLeft', 'KeyS', hold_ms=120)
        dialog = self.wait_text('Select File Name', timeout=6)
        # Win3.1 edit controls do not uniformly support Ctrl+A.
        self.key('Home', settle=.05)
        self.game.chord('ShiftLeft', 'End', hold_ms=80)
        self.game.type_text(name)
        typed = self.observe()
        self.key('Enter')
        deadline = time.monotonic() + 5
        while True:
            current = self.observe()
            lower = current['text'].casefold()
            if saved_notice(current):
                data = self.game.save_bytes(name)
                self.key('Enter')
                return data, {'before': before['sha256'], 'dialog': dialog['sha256'],
                              'typed': typed['sha256'], 'saved': current['sha256'],
                              'name': name, 'mechanical_operation': 'native-save'}
            if ('already exists' in lower or 'replace' in lower or 'overwrite' in lower):
                # The caller explicitly selected this checkpoint filename.
                if 'yes' not in lower:
                    raise RuntimeError('Unrecognized save replacement confirmation')
                self.game.key('KeyY', holdMs=120)
            if time.monotonic() >= deadline:
                raise RuntimeError('Original game did not confirm the checkpoint')
            time.sleep(.2)

    def acknowledge_information(self, observation):
        text = observation['text'].casefold()
        recognized = (saved_notice(observation) or 'civ tutorial' in text
                      or 'civ tuborial' in text or 'civ tucorial' in text
                      or 'in the beginning' in text or 'found new city' in text
                      or 'foond new city' in text)
        if not recognized:
            return False
        self.key('Enter')
        return True
