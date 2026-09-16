#!/usr/bin/env python3
"""Fetch the exact public runtime into ignored local directories; verify every byte."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"


def checked(path: Path, entry: dict) -> bool:
    return (path.is_file() and path.stat().st_size == entry["bytes"]
            and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"])


def derive_input_runtime(engine: Path = ENGINE) -> None:
    """Hash-bound original host-input exports; keep downloaded function bodies intact."""
    patch = json.loads((engine / "input-patch.json").read_text())
    source = (engine / patch["original"]).read_bytes()
    if hashlib.sha256(source).hexdigest() != patch["original_sha256"]:
        raise RuntimeError("Input export patch requires the exact original emulator")
    old, new = patch["replace_once"].encode(), patch["with"].encode()
    if source.count(old) != 1:
        raise RuntimeError("Original emulator export table differs")
    derived = source.replace(old, new)
    if len(derived) != patch["derived_bytes"] or hashlib.sha256(derived).hexdigest() != patch["derived_sha256"]:
        raise RuntimeError("Derived input runtime checksum differs")
    dest = engine / patch["derived"]
    with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=".input-runtime-", delete=False) as out:
        temporary = Path(out.name)
        out.write(derived)
    try:
        temporary.replace(dest)
    finally:
        temporary.unlink(missing_ok=True)
    print("Verified derived host input runtime; original emulator unchanged")


def main() -> None:
    manifest = json.loads((ENGINE / "runtime-manifest.json").read_text())
    for entry in manifest["files"]:
        dest = ENGINE / entry["path"]
        if checked(dest, entry):
            print(f"Verified {entry['path']}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(entry["url"], headers={
            "Referer": manifest["source_page"],
            "User-Agent": "tsai-civ2-runtime-setup/1.0",
        })
        temp_name = None
        try:
            with urllib.request.urlopen(request, timeout=60) as response, tempfile.NamedTemporaryFile(
                dir=dest.parent, prefix=".download-", delete=False
            ) as out:
                temp_name = Path(out.name)
                remaining = entry["bytes"] + 1
                while remaining:
                    chunk = response.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            if not checked(temp_name, entry):
                raise RuntimeError(f"Runtime checksum/size differs: {entry['path']}")
            temp_name.replace(dest)
            print(f"Downloaded and verified {entry['path']}")
        finally:
            if temp_name:
                temp_name.unlink(missing_ok=True)
    with zipfile.ZipFile(ENGINE / "game/civ2-win31.zip") as bundle:
        executable = bundle.read(manifest["game"]["executable"])
        if hashlib.sha256(executable).hexdigest() != manifest["game"]["executable_sha256"]:
            raise RuntimeError("Original game executable checksum differs")
    derive_input_runtime()
    print(f"Ready: Civilization II {manifest['game']['version']}; assets remain ignored.")


if __name__ == "__main__":
    main()
