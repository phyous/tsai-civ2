"""Isolated local Chrome runtime: start, inspect, and stop only owned processes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler
import uuid

ROOT = Path(__file__).resolve().parents[1]
LAUNCHES = ROOT / '.runtime' / 'launchers'
PROTECTED_PORTS = frozenset(range(3920, 3925))
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')
FLAGS = ('--headless=new', '--no-first-run', '--no-default-browser-check',
         '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
         '--disable-backgrounding-occluded-windows',
         '--autoplay-policy=no-user-gesture-required', '--window-size=1920,1080')


class LauncherError(RuntimeError):
    pass


def _directory(identifier, *, create=False):
    if not isinstance(identifier, str) or not NAME.fullmatch(identifier):
        raise LauncherError('Use a launch ID containing only letters, numbers, hyphens or underscores')
    # Never follow a profile/state directory redirected outside ignored storage.
    for path in (ROOT / '.runtime', LAUNCHES, LAUNCHES / identifier):
        if path.is_symlink():
            raise LauncherError('Launcher directories must not be symbolic links')
    if create:
        LAUNCHES.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            (LAUNCHES / identifier).mkdir(mode=0o700)
        except FileExistsError:
            raise LauncherError('Launch ID already exists; each launch requires a fresh profile') from None
    directory = LAUNCHES / identifier
    if not directory.is_dir():
        raise LauncherError('Launch ID does not exist')
    return directory


def _port_available(port):
    with socket.socket() as listener:
        try:
            listener.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def select_port(port=None):
    if port is not None:
        if type(port) is not int or not 1024 <= port <= 65535 or port in PROTECTED_PORTS:
            raise LauncherError('Use an unprivileged port outside reserved active ports 3920–3924')
        if not _port_available(port):
            raise LauncherError('Requested loopback port is already in use')
        return port
    for candidate in range(3930, 4000):
        if _port_available(candidate):
            return candidate
    raise LauncherError('No free default port; provide --port explicitly')


def _chrome_path(value=None):
    candidates = ([value] if value else [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        shutil.which('google-chrome'), shutil.which('chromium'), shutil.which('chromium-browser')])
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise LauncherError('Chrome was not found; provide its executable with --chrome')


def commands(directory, port, chrome, backend="legacy"):
    if backend not in ("legacy", "modern"):
        raise LauncherError("Unknown runtime backend")
    query = "?backend=modern" if backend == "modern" else ""
    return {
        'server': [sys.executable, '-m', 'civ2.launcher', '_serve', directory.name, '--port', str(port)],
        'chrome': [chrome, *FLAGS, f'--user-data-dir={directory / "chrome-profile"}',
                   f'http://127.0.0.1:{port}/{query}'],
    }


def process_identity(pid):
    """Capture a PID's start stamp and full command, never its environment."""
    if type(pid) is not int or pid <= 1:
        return None
    try:
        output = subprocess.run(['ps', '-ww', '-p', str(pid), '-o', 'lstart=', '-o', 'command='],
            capture_output=True, text=True, check=False, timeout=3,
            env={**os.environ, 'LC_ALL':'C'}).stdout.strip()
        if not output:
            return None
        pgid = os.getpgid(pid)
    except (OSError, subprocess.TimeoutExpired):
        return None
    parts = output.split(None, 5)
    if len(parts) != 6:
        return None
    return {'pid':pid, 'pgid':pgid, 'command':parts[5],
            'process_sha256':hashlib.sha256(output.encode()).hexdigest()}


def _write(directory, value):
    temporary = directory / 'processes.tmp'
    target = directory / 'processes.json'
    if temporary.is_symlink() or target.is_symlink():
        raise LauncherError('Refusing a redirected launcher manifest')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2)
        stream.write('\n')
    temporary.replace(target)


def _load(identifier):
    directory = _directory(identifier)
    manifest = directory / 'processes.json'
    if manifest.is_symlink():
        raise LauncherError('Refusing a redirected launcher manifest')
    try:
        value = json.loads(manifest.read_text())
        if (value['version'] != 1 or value['id'] != identifier
                or value['directory'] != str(directory) or value['repository'] != str(ROOT)
                or value['profile'] != str(directory / 'chrome-profile')
                or (directory / 'chrome-profile').is_symlink()
                or type(value['port']) is not int or not 1024 <= value['port'] <= 65535
                or value['port'] in PROTECTED_PORTS
                or set(value['processes']) != {'server', 'chrome'}):
            raise ValueError()
        # Commands must carry this launch's own port/profile, never a user profile.
        expected = commands(directory, value['port'], value['commands']['chrome'][0], value.get('backend','legacy'))
        expected['server'][0] = value['commands']['server'][0]
        if value['commands'] != expected:
            raise ValueError()
        for role, record in value['processes'].items():
            if record is not None and (set(record) != {'pid','pgid','command','process_sha256'}
                    or type(record['pid']) is not int or record['pid'] <= 1
                    or record['pgid'] != record['pid']
                    or record['command'] != ' '.join(value['commands'][role])
                    or not re.fullmatch('[a-f0-9]{64}', record['process_sha256'])):
                raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        raise LauncherError('Invalid or incomplete launcher manifest; no processes were signaled') from None
    return directory, value


def _health(port):
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/bridge/health', timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def _wait_ready(port, processes, *, connected=False, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise LauncherError('A launched process exited; inspect its ignored local log')
        health = _health(port)
        if (isinstance(health, dict) and (not connected or health.get('connected') is True)
                and all(process.poll() is None for process in processes)):
            return
        time.sleep(.15)
    raise LauncherError('Runtime startup timed out; inspect the ignored local logs')


def start(*, port=None, chrome=None, identifier=None, backend="legacy"):
    if backend not in ("legacy", "modern"):
        raise LauncherError("Unknown runtime backend")
    port = select_port(port)
    chrome = _chrome_path(chrome)
    identifier = identifier or datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    directory = _directory(identifier, create=True)
    profile = directory / 'chrome-profile'
    profile.mkdir(mode=0o700)
    launch_commands = commands(directory, port, chrome, backend)
    value = dict(version=1, id=identifier, repository=str(ROOT), directory=str(directory),
        profile=str(profile), port=port, backend=backend, url=launch_commands['chrome'][-1],
        watch_url=f'http://127.0.0.1:{port}/web/watch.html', commands=launch_commands,
        processes={'server':None,'chrome':None}, status='starting')
    _write(directory, value)
    children = []
    # This runtime does not need model credentials. They remain in the controller.
    environment = {k:v for k,v in os.environ.items() if k != 'TYPESAFE_API_KEY'}
    try:
        for role in ('server', 'chrome'):
            with (directory / f'{role}.log').open('xb') as log:
                process = subprocess.Popen(launch_commands[role], cwd=ROOT, env=environment,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            children.append(process)
            # macOS Python may exec its framework interpreter after Popen.
            # Capture the durable identity after readiness, while the original
            # direct child is still alive, rather than a transient argv[0].
            _wait_ready(port, children, connected=role=='chrome')
            identity = process_identity(process.pid)
            if (identity is None or identity['pgid'] != process.pid
                    or process.poll() is not None):
                raise LauncherError('Could not establish ownership of a launched process')
            suffix = ' ' + ' '.join(launch_commands[role][1:])
            if not identity['command'].endswith(suffix):
                raise LauncherError('A launched process changed its expected arguments')
            # Preserve the interpreter actually executing this direct child.
            # _load still validates every argument and its full recorded identity.
            value['commands'][role][0] = identity['command'][:-len(suffix)]
            value['processes'][role] = identity
            _write(directory, value)
        value['status'] = 'connected'
        _write(directory, value)
        return value
    except BaseException:
        # These Popen children were created in this call, so they are owned even
        # if a failed startup prevented writing a complete persistent receipt.
        for process in reversed(children):
            try:
                if process.poll() is None and os.getpgid(process.pid) == process.pid:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=3)
            except ProcessLookupError:
                # A child exiting between poll/getpgid/signal must not prevent
                # cleanup of the earlier owned server or Chrome process.
                continue
        value['status'] = 'failed'
        _write(directory, value)
        raise


def status(identifier):
    _, value = _load(identifier)
    states = {}
    for role, record in value['processes'].items():
        current = process_identity(record['pid']) if record else None
        states[role] = 'stopped' if current is None else ('owned' if current == record else 'identity_mismatch')
    return {'id':identifier, 'status':value['status'], 'port':value['port'],
            'watch_url':value['watch_url'], 'processes':states, 'directory':value['directory']}


def stop(identifier, *, timeout=8):
    directory, value = _load(identifier)
    # Check both first: an edited/stale receipt cannot partly stop another run.
    for record in value['processes'].values():
        if record and (current := process_identity(record['pid'])) is not None and current != record:
            raise LauncherError('Process identity changed; refusing to signal any process')
    for role in ('chrome', 'server'):
        record = value['processes'][role]
        if not record or process_identity(record['pid']) is None:
            continue
        if process_identity(record['pid']) != record:
            raise LauncherError('Process identity changed during stop; refusing further signals')
        try:
            os.killpg(record['pgid'], signal.SIGTERM)
        except ProcessLookupError:
            continue
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and process_identity(record['pid']) == record:
            time.sleep(.1)
        current = process_identity(record['pid'])
        if current == record:
            try:
                os.killpg(record['pgid'], signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif current is not None:
            raise LauncherError('Process identity changed during shutdown; no force signal sent')
    value['status'] = 'stopped'
    _write(directory, value)
    return status(identifier)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    launch = sub.add_parser('start', help='Create a fresh isolated headless runtime')
    launch.add_argument('--port', type=int)
    launch.add_argument('--chrome')
    launch.add_argument('--backend', choices=('legacy','modern'), default='legacy')
    launch.add_argument('--name', dest='identifier')
    for command in ('stop', 'status'):
        sub.add_parser(command).add_argument('identifier')
    serve = sub.add_parser('_serve', help='Internal launcher-owned server process')
    serve.add_argument('identifier')
    serve.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == '_serve':
            _directory(args.identifier)
            from aiohttp import web
            from .server import create_app
            web.run_app(create_app(args.port), host='127.0.0.1', port=args.port, access_log=None)
            return
        result = start(port=args.port, chrome=args.chrome, identifier=args.identifier, backend=args.backend) if args.command=='start' \
                 else stop(args.identifier) if args.command=='stop' else status(args.identifier)
        print(json.dumps({k:v for k,v in result.items() if k != 'commands'}, indent=2))
    except (LauncherError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
