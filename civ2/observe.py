"""Original-game image observations; OCR is evidence, not a game-state oracle."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def recognize(path: str | Path) -> dict:
    path = Path(path).resolve()
    executable = ROOT / '.runtime' / 'ocr'
    if not executable.is_file():
        raise RuntimeError('Build scripts/ocr.swift into .runtime/ocr first')
    raw = subprocess.run([str(executable), str(path)], check=True,
                         capture_output=True, timeout=20).stdout
    rows = json.loads(raw)
    with Image.open(path) as image:
        width, height = image.size
    for row in rows:
        row['bounds'] = [round(row['x'] * width), round(row['y'] * height),
                         round(row['width'] * width), round(row['height'] * height)]
        row['center'] = [round((row['x'] + row['width'] / 2) * width),
                         round((row['y'] + row['height'] / 2) * height)]
    return {'width': width, 'height': height, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'lines': rows, 'text': '\n'.join(row['text'] for row in rows)}


def find_text(observation, text, *, exact=False):
    wanted = text.casefold()
    matches = [row for row in observation['lines']
               if (row['text'].casefold() == wanted if exact else wanted in row['text'].casefold())]
    if len(matches) != 1:
        raise ValueError(f'Game text must match one visible line ({len(matches)} matches)')
    return matches[0]['center']
