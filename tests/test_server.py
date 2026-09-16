"""Isolated HTTP/WebSocket protocol checks; never connects to the live game."""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, WSServerHandshakeError
from aiohttp.test_utils import TestServer
from yarl import URL

from civ2.server import Runtime, create_app


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        for directory in ('engine', 'web', 'civ2/static'):
            (self.root / directory).mkdir(parents=True)
        (self.root / 'engine/runtime.html').write_text('ORIGINAL-RUNTIME-TEST-PAGE')
        (self.root / 'web/index.html').write_text('SPECTATOR-TEST-PAGE')
        (self.root / 'civ2/static/transport.js').write_text('TRANSPORT-TEST')
        (self.root / 'private.txt').write_text('OUTSIDE-STATIC-ROOT')
        (self.root / 'engine/.private').write_text('HIDDEN-STATIC-FILE')
        self.root_patch = patch('civ2.server.ROOT', self.root)
        self.root_patch.start()
        self.app = create_app(port=43920)
        self.server = TestServer(self.app, host='127.0.0.1', port=0)
        await self.server.start_server()
        # The ephemeral socket is private to this test. Host/Origin exercise the
        # application's configured boundary, without binding the real game port.
        self.host = '127.0.0.1:43920'
        self.origin = 'http://' + self.host
        self.session = ClientSession(headers={'Host': self.host})
        self.sockets = []

    async def asyncTearDown(self):
        for ws in self.sockets:
            await ws.close()
        await self.session.close()
        await self.server.close()
        self.root_patch.stop()
        self.directory.cleanup()

    def url(self, path):
        return URL(str(self.server.make_url('/')).rstrip('/') + path, encoded=True)

    async def socket(self):
        ws = await self.session.ws_connect(self.url('/api/runtime'), origin=self.origin)
        self.sockets.append(ws)
        return ws

    async def test_websocket_rpc_roundtrip_and_capture(self):
        ws = await self.socket()
        async def browser():
            request = await ws.receive_json(timeout=2)
            self.assertEqual(request['command'], 'status')
            self.assertEqual(request['args'], [])
            await ws.send_json({'id': request['id'], 'ok': True,
                                'result': {'started': True, 'paused': False}})
        responding = asyncio.create_task(browser())
        async with self.session.post(self.url('/bridge/rpc'), json={'command': 'status'}) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.json(), {'result': {'started': True, 'paused': False}})
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        await responding
        # A tiny stand-in with the real PNG signature tests transport fidelity;
        # pixel/image validity remains the runtime recorder's responsibility.
        png = b'\x89PNG\r\n\x1a\nTEST-PNG-PAYLOAD'
        async def capturing():
            request = await ws.receive_json(timeout=2)
            self.assertEqual(request['command'], 'capture')
            await ws.send_json({'id': request['id'], 'ok': True,
                                'result': 'data:image/png;base64,' + base64.b64encode(png).decode()})
        responding = asyncio.create_task(capturing())
        async with self.session.get(self.url('/bridge/capture/game')) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, 'image/png')
            self.assertEqual(await response.read(), png)
        await responding
        self.assertEqual(self.app['runtime'].pending, {})

    async def test_foreign_origin_host_and_browser_control_are_rejected(self):
        for path, headers in [('/api/state', {'Origin': 'https://foreign.example'}),
                              ('/api/state', {'Host': 'foreign.example'}),
                              ('/bridge/health', {'Origin': self.origin})]:
            async with self.session.get(self.url(path), headers=headers) as response:
                self.assertEqual(response.status, 403)
        with self.assertRaises(WSServerHandshakeError) as error:
            await self.session.ws_connect(self.url('/api/runtime'), origin='https://foreign.example')
        self.assertEqual(error.exception.status, 403)
        async with self.session.get(self.url('/api/state'), headers={'Origin': self.origin}) as response:
            self.assertEqual(response.status, 200)

    async def test_forbidden_commands_and_bad_shapes_do_not_reach_runtime(self):
        ws = await self.socket()
        for payload in ({'command':'eval','args':['window.secret']},
                        {'command':'importSave','args':['X.SAV',[1]]},
                        {'command':'status','args':{}}, [], {'args':[]}):
            async with self.session.post(self.url('/bridge/rpc'), json=payload) as response:
                self.assertEqual(response.status, 400)
        self.assertEqual(self.app['runtime'].serial, 0)
        self.assertEqual(self.app['runtime'].pending, {})
        self.assertFalse(ws.closed)

    async def test_static_files_are_confined_to_approved_roots(self):
        for path, expected in [('/', 'SPECTATOR-TEST-PAGE'),
                               ('/engine/runtime.html', 'ORIGINAL-RUNTIME-TEST-PAGE'),
                               ('/transport.js','TRANSPORT-TEST')]:
            async with self.session.get(self.url(path)) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.text(), expected)
        outside_link = self.root / 'engine/leak.txt'
        outside_link.symlink_to(self.root / 'private.txt')
        for path in ('/engine/../private.txt', '/engine/%2e%2e/private.txt',
                     '/engine/%2e%2e%2fprivate.txt', '/web/../private.txt',
                     '/engine/leak.txt', '/engine/.private', '/private.txt'):
            async with self.session.get(self.url(path)) as response:
                self.assertEqual(response.status, 404, path)
                self.assertNotIn('OUTSIDE-STATIC-ROOT', await response.text())

    async def test_disconnect_fails_pending_rpc_and_next_connection_can_recover(self):
        ws = await self.socket()
        async def disconnecting():
            await ws.receive_json(timeout=2)
            await ws.close()
        disconnect = asyncio.create_task(disconnecting())
        async with self.session.post(self.url('/bridge/rpc'), json={'command':'status'}) as response:
            self.assertEqual(response.status, 503)
            self.assertEqual(await response.json(), {'error':'Game runtime unavailable or timed out'})
        await disconnect
        self.assertEqual(self.app['runtime'].pending, {})
        replacement = await self.socket()
        async def responding():
            request = await replacement.receive_json(timeout=2)
            await replacement.send_json({'id':request['id'],'ok':True,'result':'reconnected'})
        response_task = asyncio.create_task(responding())
        async with self.session.post(self.url('/bridge/rpc'), json={'command':'status'}) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['result'], 'reconnected')
        await response_task

    async def test_runtime_errors_and_invalid_capture_are_sanitized(self):
        ws = await self.socket()
        async def responding():
            first = await ws.receive_json(timeout=2)
            await ws.send_json({'id':first['id'],'ok':False,'error':'PRIVATE ERROR MUST NOT ESCAPE'})
            second = await ws.receive_json(timeout=2)
            await ws.send_json({'id':second['id'],'ok':True,'result':'data:image/png;base64,not-base64'})
        response_task = asyncio.create_task(responding())
        async with self.session.post(self.url('/bridge/rpc'), json={'command':'status'}) as response:
            self.assertEqual(response.status, 503)
            self.assertNotIn('PRIVATE', await response.text())
        async with self.session.get(self.url('/bridge/capture/game')) as response:
            self.assertIn(response.status, (400,503))
            self.assertNotIn('not-base64', await response.text())
        await response_task

    async def test_second_runtime_is_rejected(self):
        await self.socket()
        with self.assertRaises(WSServerHandshakeError) as error:
            await self.socket()
        self.assertEqual(error.exception.status, 409)


class RuntimeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_send_cleans_pending_and_normalizes_connection_error(self):
        class BrokenSocket:
            closed = False
            async def send_json(self, value):
                raise ConnectionResetError('private low-level details')
        runtime = Runtime()
        runtime.ws = BrokenSocket()
        try:
            with self.assertRaises(RuntimeError):
                await runtime.call('status', [])
        finally:
            self.assertEqual(runtime.pending, {})

    async def test_queued_call_rechecks_connection_after_lock(self):
        class Socket:
            closed = False
        runtime = Runtime()
        runtime.ws = Socket()
        await runtime.lock.acquire()
        waiting = asyncio.create_task(runtime.call('status', []))
        await asyncio.sleep(0)
        runtime.ws = None
        runtime.lock.release()
        with self.assertRaises(RuntimeError):
            await waiting
        self.assertEqual(runtime.pending, {})


if __name__ == '__main__':
    unittest.main()
