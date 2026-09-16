"""Observed original-game dialogs and ordinary-input housekeeping.

This module does not make strategy decisions. It opens native saves, enters
mechanical names and acknowledges explicitly recognized informational dialogs.
"""
from __future__ import annotations
import json
import difflib
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

    def observe(self):
        self.counter += 1
        path = self.directory / f'ui-{self.counter:07d}.png'
        self.game.capture(path)
        observation = recognize(path)
        observation['path'] = str(path)
        self.latest = observation
        return observation

    def key(self, code, *, settle=.25):
        receipts = self.game.key(code, holdMs=120)
        time.sleep(settle)
        return receipts

    def wait(self, predicate, *, timeout=8):
        deadline = time.monotonic() + timeout
        while True:
            observation = self.observe()
            if predicate(observation):
                return observation
            if time.monotonic() >= deadline:
                raise RuntimeError('Expected original-game screen did not appear')
            time.sleep(.2)

    def wait_text(self, text, *, timeout=8):
        return self.wait(lambda o: text.casefold() in o['text'].casefold(), timeout=timeout)

    def select_text(self, observation, text, *, exact=False, confirm=False):
        # The caller supplies the fresh screen containing this exact target.
        if self.latest is not observation:
            raise ValueError('Selection requires the latest observed screen')
        point = find_text(observation, text, exact=exact)
        receipts = self.game.click(*point)
        time.sleep(.2)
        selected = self.observe()
        if confirm:
            receipts += self.key('Enter')
        return {'target': text, 'point': point, 'before': observation['sha256'],
                'selected_frame': selected['sha256'], 'inputs': receipts}

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
