"""Constrained Python client for original Civ II keyboard/mouse and captures."""
from __future__ import annotations
import base64
import json
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import URLError, HTTPError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise URLError('Redirects disabled')


class Game:
    def __init__(self, port=3920):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid local port')
        self.base = f'http://127.0.0.1:{port}'
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, payload=None, binary=False):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.base + path, data=data, headers={'Content-Type':'application/json'})
        try:
            with self.opener.open(request, timeout=100) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
        except HTTPError as exc:
            code = exc.code; exc.close()
            raise RuntimeError(f'Local game bridge HTTP {code}') from None
        except (URLError, TimeoutError):
            raise RuntimeError('Local game bridge unavailable') from None
        if len(raw) > 16 * 1024 * 1024:
            raise RuntimeError('Bridge response exceeds limit')
        return raw if binary else json.loads(raw)

    def rpc(self, command, *args):
        if command in ('pause', 'resume'):
            state = self.rpc('status')
            if state.get('paused') == (command == 'pause'):
                return state
        return self.request('/bridge/rpc', {'command': command, 'args': list(args)})['result']

    def capture(self, path, dashboard=False):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        data = self.request('/bridge/capture/' + ('dashboard' if dashboard else 'game'), binary=True)
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('Invalid original game capture')
        path.write_bytes(data)
        return path

    def key(self, code, **options):
        return self.rpc('key', code, options)

    def click(self, x, y, button=0, *, timeout=20):
        from .cursor import move_and_click
        return [move_and_click(self, x, y, button, timeout=timeout)]

    def chord(self, *codes, hold_ms=70):
        if len(codes) < 2:
            raise ValueError('Chord requires a modifier and a key')
        return self.rpc('chord', list(codes), {'holdMs': hold_ms})

    def type_text(self, text):
        punctuation = {'.':'Period', '-':'Minus', '/':'Slash', '\\':'Backslash',
                       ':':'Semicolon', '_':'Minus', ' ':'Space'}
        if not isinstance(text, str) or len(text) > 128:
            raise ValueError('Bounded game text required')
        receipts = []
        for char in text:
            if char.isascii() and char.isalpha():
                code = 'Key' + char.upper()
            elif char in '0123456789':
                code = 'Digit' + char
            elif char in punctuation:
                code = punctuation[char]
            else:
                raise ValueError('Unsupported game text character')
            receipts.append(self.chord('ShiftLeft', code) if char.isupper() or char in ':_' else self.key(code))
        return receipts

    def save_bytes(self, name):
        result = self.rpc('readSave', name)
        if result.get('encoding') != 'base64':
            raise RuntimeError('Invalid save encoding')
        data = base64.b64decode(result['data'], validate=True)
        if len(data) != result['length']:
            raise RuntimeError('Truncated save')
        return data

    def import_save(self, name, data):
        # Setup/recovery copies a whole original save; the guest must then load
        # it through its normal Load Game dialog. Existing files cannot change.
        from .save import parse_save
        parse_save(data)
        return self.rpc('importSave', name, {'encoding':'base64','length':len(data),
            'data':base64.b64encode(data).decode('ascii')})

    def state(self, snapshot):
        return self.request('/bridge/state', snapshot)
