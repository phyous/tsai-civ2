"""Append-only, hash-linked local evidence for a real game attempt."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / 'events.jsonl'
        self.file = self.path.open('x', encoding='utf-8')
        self.started = time.monotonic()
        self.previous = '0' * 64
        self.sequence = 0

    def append(self, kind, **payload):
        self.sequence += 1
        event = {'sequence': self.sequence, 'elapsed_ms': round((time.monotonic()-self.started)*1000),
                 'kind': kind, 'previous_sha256': self.previous, 'payload': payload}
        digest = hashlib.sha256(canonical(event)).hexdigest()
        record = {**event, 'sha256': digest}
        self.file.write(canonical(record).decode('utf-8') + '\n')
        self.file.flush()
        self.previous = digest
        return record

    def artifact(self, name, content):
        path = self.directory / name
        if not path.resolve().is_relative_to(self.directory.resolve()) or path.exists():
            raise ValueError('Evidence artifacts must have new, confined paths')
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, bytes) else canonical(content)
        path.write_bytes(data)
        return {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def close(self):
        self.file.close()


def verify_chain(path):
    previous, elapsed, count = '0' * 64, -1, 0
    with Path(path).open(encoding='utf-8') as source:
        for line in source:
            record = json.loads(line)
            digest = record.pop('sha256')
            count += 1
            if (record['sequence'] != count or record['previous_sha256'] != previous
                or record['elapsed_ms'] < elapsed
                or hashlib.sha256(canonical(record)).hexdigest() != digest):
                raise ValueError('Evidence chain validation failed')
            previous, elapsed = digest, record['elapsed_ms']
    return {'events': count, 'last_sha256': previous, 'duration_ms': max(0, elapsed)}
