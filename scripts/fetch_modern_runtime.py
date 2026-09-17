#!/usr/bin/env python3
"""Install the optional, byte-pinned GPL js-dos backend into ignored assets."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def checked(data: bytes, entry: dict) -> bool:
    return len(data) == entry['bytes'] and hashlib.sha256(data).hexdigest() == entry['sha256']


def install(archive: bytes, engine: Path, manifest: dict) -> None:
    if not checked(archive, manifest['archive']):
        raise ValueError('Modern runtime archive checksum or size differs')
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as package:
        for entry in manifest['files']:
            relative = Path(entry['path'])
            if relative.is_absolute() or '..' in relative.parts or relative.parts[:2] != ('vendor', 'modern'):
                raise ValueError('Modern runtime destination escapes its directory')
            members = [m for m in package.getmembers() if m.name == entry['member']]
            if len(members) != 1 or not members[0].isfile() or members[0].size != entry['bytes']:
                raise ValueError('Modern runtime package member differs')
            source = package.extractfile(members[0])
            assert source is not None
            data = source.read(entry['bytes'] + 1)
            if not checked(data, entry):
                raise ValueError('Modern runtime member checksum differs')
            dest = engine / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=dest.parent, prefix='.modern-', delete=False) as out:
                temporary = Path(out.name)
                out.write(data)
            try:
                temporary.replace(dest)
            finally:
                temporary.unlink(missing_ok=True)


def main() -> None:
    engine = ROOT / 'engine'
    manifest = json.loads((engine / 'modern-manifest.json').read_text())
    if all((engine / item['path']).is_file() and checked((engine / item['path']).read_bytes(), item)
           for item in manifest['files']):
        print('Verified optional js-dos 8.4.2 assets')
        return
    entry = manifest['archive']
    with urllib.request.urlopen(entry['url'], timeout=60) as response:
        archive = response.read(entry['bytes'] + 1)
    install(archive, engine, manifest)
    print('Installed and verified optional js-dos 8.4.2; game assets unchanged')


if __name__ == '__main__':
    main()
