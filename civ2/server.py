"""Local spectator server and constrained bridge to the embedded game runtime."""
from __future__ import annotations
import argparse
import asyncio
import base64
import json
import re
from pathlib import Path
import time
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = frozenset(('boot', 'status', 'pause', 'resume', 'key', 'chord', 'keyDown',
    'keyUp', 'mouse', 'click', 'releaseInputs', 'capture', 'captureDashboard',
    'listSaves', 'readSave', 'inputDiagnostics', 'moveRelative', 'importSave',
    'observerRequest', 'readObserver', 'observerProvenance'))


class Runtime:
    def __init__(self):
        self.ws = None
        self.pending = {}
        self.serial = 0
        self.lock = asyncio.Lock()
        self.state = {'status': 'setup', 'mode': 'live', 'civilization': 'Rome',
                      'message': 'Connect the original game to begin.'}

    async def call(self, command, args):
        if command not in COMMANDS or not isinstance(args, list):
            raise ValueError('Unsupported runtime request')
        if command == 'moveRelative' and (len(args) != 2 or any(type(v) is not int or not -32 <= v <= 32 for v in args) or args == [0,0]):
            raise ValueError('Bounded relative mouse deltas required')
        if command == 'observerRequest' and (len(args) != 1 or not isinstance(args[0],str)
                or not re.fullmatch(r'[a-f0-9]{32}',args[0])):
            raise ValueError('A fixed observer nonce is required')
        if command in ('readObserver','observerProvenance') and args:
            raise ValueError('Observer reads accept no paths or addresses')
        if command == 'importSave':
            if (len(args) != 2 or not isinstance(args[0],str) or not re.fullmatch(r'[A-Za-z0-9_]{1,8}\.sav',args[0],re.I)
                or not isinstance(args[1],dict) or args[1].get('encoding') != 'base64'
                or not isinstance(args[1].get('data'),str) or len(args[1]['data']) > 6000000
                or type(args[1].get('length')) is not int or not 1 <= args[1]['length'] <= 4000000):
                raise ValueError('A bounded original save is required')
        # Inputs and snapshots are serialized, so reads cannot race a key chord.
        async with self.lock:
            ws = self.ws
            if ws is None or ws.closed:
                raise RuntimeError('The game iframe is not connected')
            self.serial += 1
            sequence = self.serial
            future = asyncio.get_running_loop().create_future()
            self.pending[sequence] = future
            try:
                try:
                    await ws.send_json({'id': sequence, 'command': command, 'args': args})
                except (ConnectionError, OSError) as error:
                    raise RuntimeError('The game connection was interrupted') from error
                return await asyncio.wait_for(future, 90 if command == 'boot' else 35)
            finally:
                self.pending.pop(sequence, None)
                if not future.done():
                    future.cancel()


def create_app(port=3920):
    app = web.Application(client_max_size=8 * 1024 * 1024)
    runtime = Runtime()
    app['runtime'] = runtime
    allowed_origins = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}

    @web.middleware
    async def boundary(request, handler):
        if request.host not in {f'127.0.0.1:{port}', f'localhost:{port}'}:
            raise web.HTTPForbidden(text='Loopback host required')
        origin = request.headers.get('Origin')
        if origin and origin not in allowed_origins:
            raise web.HTTPForbidden(text='Foreign origins are disabled')
        if request.path.startswith('/bridge/') and origin:
            raise web.HTTPForbidden(text='Control bridge is not browser accessible')
        try:
            response = await handler(request)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return web.json_response({'error': 'Invalid harness request'}, status=400)
        except (RuntimeError, asyncio.TimeoutError):
            return web.json_response({'error': 'Game runtime unavailable or timed out'}, status=503)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    app.middlewares.append(boundary)

    async def runtime_socket(request):
        ws = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024, heartbeat=20)
        if runtime.ws is not None and not runtime.ws.closed:
            raise web.HTTPConflict(text='A game runtime is already connected')
        await ws.prepare(request)
        runtime.ws = ws
        try:
            async for message in ws:
                if message.type != web.WSMsgType.TEXT:
                    continue
                payload = json.loads(message.data)
                future = runtime.pending.get(payload.get('id'))
                if future and not future.done():
                    if payload.get('ok'):
                        future.set_result(payload.get('result'))
                    else:
                        future.set_exception(RuntimeError('Game command failed'))
        finally:
            if runtime.ws is ws:
                runtime.ws = None
            for future in list(runtime.pending.values()):
                if not future.done():
                    future.set_exception(RuntimeError('Game disconnected'))
        return ws

    async def state(request):
        return web.json_response(runtime.state)

    async def set_state(request):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError('State must be an object')
        runtime.state = payload
        return web.json_response({'ok': True})

    async def control(request):
        action = (await request.json()).get('action')
        command = {'start': 'boot', 'pause': 'pause', 'resume': 'resume'}.get(action)
        if command is None:
            raise ValueError('Unknown spectator control')
        await runtime.call(command, [])
        runtime.state = {**runtime.state, 'status': 'paused' if action == 'pause' else 'running',
                         'message': 'Original Civilization II runtime connected.'}
        return web.json_response(runtime.state)

    async def rpc(request):
        payload = await request.json()
        result = await runtime.call(payload['command'], payload.get('args', []))
        return web.json_response({'result': result})

    async def health(request):
        return web.json_response({'connected': bool(runtime.ws and not runtime.ws.closed),
                                  'status': runtime.state.get('status')})

    async def screenshot(request):
        command = 'captureDashboard' if request.match_info['kind'] == 'dashboard' else 'capture'
        value = await runtime.call(command, [])
        if not isinstance(value, str) or not value.startswith('data:image/png;base64,'):
            raise RuntimeError('Invalid capture')
        data = base64.b64decode(value.partition(',')[2], validate=True)
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('Invalid PNG')
        return web.Response(body=data, content_type='image/png')

    async def static(request):
        relative = request.match_info.get('path', '')
        if not relative:
            path = ROOT / 'web/index.html'
        elif relative == 'transport.js':
            path = ROOT / 'civ2/static/transport.js'
        elif relative.startswith('engine/'):
            path = ROOT / relative
            if not path.resolve().is_relative_to((ROOT / 'engine').resolve()):
                raise web.HTTPNotFound()
        else:
            relative = relative.removeprefix('web/')
            path = ROOT / 'web' / relative
            if not path.resolve().is_relative_to((ROOT / 'web').resolve()):
                raise web.HTTPNotFound()
        if not path.is_file() or path.name.startswith('.'):
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    app.router.add_get('/api/runtime', runtime_socket)
    app.router.add_get('/api/state', state)
    app.router.add_post('/api/control', control)
    app.router.add_get('/bridge/health', health)
    app.router.add_post('/bridge/state', set_state)
    app.router.add_post('/bridge/rpc', rpc)
    app.router.add_get('/bridge/capture/{kind:game|dashboard}', screenshot)
    app.router.add_get('/{path:.*}', static)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=3920)
    args = parser.parse_args()
    web.run_app(create_app(args.port), host='127.0.0.1', port=args.port, access_log=None)

if __name__ == '__main__':
    main()
