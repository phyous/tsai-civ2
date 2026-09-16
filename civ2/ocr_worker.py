"""Private persistent Vision transport; unchanged one-shot CLI is the fallback.

No OCR result caching, image transformations, or recognition rules live here.
One serialized child belongs to this Python process and executable revision.
"""
from __future__ import annotations
import atexit
import json
import os
from pathlib import Path
import select
import subprocess
import threading
import time

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_WORKER_REQUESTS = 256


class _ProtocolError(ValueError):
    pass


class OCRWorker:
    def __init__(self, executable):
        self.executable = str(Path(executable).resolve())
        self.process = None
        self.disabled = False
        self.sequence = 0
        self.requests = 0
        self.buffer = b''
        self.lock = threading.Lock()

    def close(self):
        with self.lock:
            # A caller may already hold this object while a new executable
            # revision retires it. It must not spawn an untracked child later.
            self.disabled = True
            self._close()

    def _close(self):
        process, self.process = self.process, None
        self.buffer = b''
        self.requests = 0
        if process is not None:
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            process.wait()
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    pipe.close()

    def _read(self, deadline, timeout):
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], max(0, remaining))[0]:
                raise subprocess.TimeoutExpired([self.executable, '--worker'], timeout)
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise _ProtocolError('OCR worker closed its response pipe')
            self.buffer += chunk
            if len(self.buffer) > MAX_RESPONSE_BYTES:
                raise _ProtocolError('OCR worker response exceeded limit')
        line, self.buffer = self.buffer.split(b'\n', 1)
        return json.loads(line)

    def run(self, path, *, timeout=20):
        path = str(Path(path).resolve())
        with self.lock:
            deadline = time.monotonic() + timeout
            if not self.disabled:
                try:
                    # Bound opaque framework-cache lifetime over long games.
                    if self.process is not None and self.requests >= MAX_WORKER_REQUESTS:
                        self._close()
                    if self.process is None:
                        self.process = subprocess.Popen([self.executable, '--worker'],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, bufsize=0, close_fds=True)
                        if self._read(deadline, timeout) != {'ready': 1}:
                            raise _ProtocolError('Unexpected OCR worker handshake')
                    self.sequence += 1
                    self.requests += 1
                    message = json.dumps({'id': self.sequence, 'path': path}).encode() + b'\n'
                    if len(message) > 16384:
                        raise ValueError('OCR path exceeds worker request limit')
                    if self.process.stdin.write(message) != len(message):
                        raise _ProtocolError('Incomplete OCR worker request')
                    response = self._read(deadline, timeout)
                    if (not isinstance(response, dict) or type(response.get('id')) is not int
                            or response['id'] != self.sequence):
                        raise _ProtocolError('OCR worker response identity mismatch')
                    if set(response) == {'id', 'error'}:
                        raise subprocess.CalledProcessError(1, [self.executable, path], stderr=b'Game image OCR failed\n')
                    if set(response) != {'id', 'rows'} or not isinstance(response['rows'], list):
                        raise _ProtocolError('Invalid OCR worker response')
                    return response['rows']
                except subprocess.CalledProcessError:
                    # A valid per-image failure is not a transport failure.
                    raise
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    self.disabled = True
                    self._close()
                    if time.monotonic() >= deadline:
                        raise
            # Old binaries, worker crashes, and protocol errors use the same
            # real image with the original CLI. Never accept a stale response.
            raw = subprocess.run([self.executable, path], check=True,
                capture_output=True, timeout=max(.001, deadline - time.monotonic())).stdout
            return json.loads(raw)


_workers = {}
_lock = threading.Lock()


def run_ocr(executable, path):
    executable = Path(executable).resolve()
    stat = executable.stat()
    revision = (str(executable), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    with _lock:
        # Atomic binary replacement invalidates only its own old child.
        for old in list(_workers):
            if old[0] == revision[0] and old != revision:
                _workers.pop(old).close()
        worker = _workers.setdefault(revision, OCRWorker(executable))
    return worker.run(path)


def close_workers():
    with _lock:
        workers = list(_workers.values())
        _workers.clear()
    for worker in workers:
        worker.close()


atexit.register(close_workers)
