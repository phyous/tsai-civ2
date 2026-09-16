"""Original-game image observations; OCR is evidence, not a game-state oracle."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SHORT_CONTROLS = {text.casefold(): text for text in
                  ('OK', 'Cancel', 'Yes', 'No', 'Help', 'Close', 'Next', 'Back', 'Done', 'Continue')}
STATUS_CROP = (466, 440, 640, 480)
STATUS_PHRASES = ('End of Turn', '(Press ENTER)')


def _run_ocr(executable, path):
    raw = subprocess.run([str(executable), str(path)], check=True,
                         capture_output=True, timeout=20).stdout
    return json.loads(raw)


def _prepare_rows(rows, width, height, preprocessing):
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError('Invalid OCR result size')
    prepared = []
    for original in rows:
        row = dict(original)
        if not isinstance(row.get('text'), str) or len(row['text']) > 2000:
            raise ValueError('Invalid OCR text')
        values = [row.get(key) for key in ('x', 'y', 'width', 'height', 'confidence')]
        if any(type(value) not in (int, float) or not math.isfinite(value)
               for value in values) or any(not -1e-6 <= value <= 1+1e-6 for value in values[:4]) or not 0 <= values[4] <= 1:
            raise ValueError('Invalid normalized OCR geometry')
        # Vision can return -1.7e-10 for a box on the top pixel during DOS
        # startup. Clamp only subpixel floating-point error, retaining raw proof.
        x, y, w, h = [min(1,max(0,value)) for value in values[:4]]
        confidence = values[4]
        if w <= 0 or h <= 0 or x + w > 1.001 or y + h > 1.001:
            raise ValueError('OCR geometry outside source image')
        row['bounds'] = [round(x * width), round(y * height), round(w * width), round(h * height)]
        row['center'] = [round((x + w / 2) * width), round((y + h / 2) * height)]
        row['provenance'] = [dict(preprocessing=preprocessing, text=row['text'], confidence=confidence,
                                  normalized_bounds=[x, y, w, h])]
        prepared.append(row)
    return prepared


def _overlap(a, b):
    ax, ay, aw, ah = a['bounds']; bx, by, bw, bh = b['bounds']
    return max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))


def _same_location(a, b):
    area = min(a['bounds'][2] * a['bounds'][3], b['bounds'][2] * b['bounds'][3])
    return (area > 0 and _overlap(a, b) / area >= .6
            and abs(a['center'][0] - b['center'][0]) <= max(6, min(a['bounds'][2], b['bounds'][2]) * .3)
            and abs(a['center'][1] - b['center'][1]) <= 4)


def _ok_lookalike(text):
    return text.strip().translate(str.maketrans({'О': 'O', 'о': 'o', 'К': 'K', 'к': 'k'})).upper() == 'OK'


def _merge_controls(rows, fallback, conflicts):
    for candidate in fallback:
        label = SHORT_CONTROLS.get(candidate['text'].strip().casefold())
        if label is None:
            continue
        overlaps = [row for row in rows if _overlap(row, candidate)]
        if not overlaps:
            rows.append(candidate)
        elif len(overlaps) == 1 and _same_location(overlaps[0], candidate):
            previous = overlaps[0]
            equal = previous['text'].strip().casefold() == label.casefold()
            # Only an independently observed ASCII OK can corroborate the
            # Cyrillic glyph reading at the very same visible control.
            if equal or (label == 'OK' and _ok_lookalike(previous['text'])):
                previous['provenance'].extend(candidate['provenance'])
                if not equal:
                    previous['text'] = 'OK'
                    previous['normalization'] = 'same-control ASCII OK corroboration'
                continue
            conflicts.append(dict(text=candidate['text'], bounds=candidate['bounds'],
                                  reason='contradictory overlapping native text'))
        else:
            conflicts.append(dict(text=candidate['text'], bounds=candidate['bounds'],
                                  reason='ambiguous overlapping native geometry'))


def _near_text(a, b, limit):
    if abs(len(a) - len(b)) > limit:
        return False
    costs = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        previous, costs = costs, [i]
        for j, other in enumerate(b, 1):
            costs.append(min(costs[-1] + 1, previous[j] + 1, previous[j - 1] + (char != other)))
    return costs[-1] <= limit


def _heading_near_match(text):
    """At most two edits corroborate a heading; never generate its text."""
    return _near_text(' '.join(text.casefold().split()), 'found new city', 2)


def _in_status_crop(row):
    x, y, w, h = row['bounds']
    return x >= STATUS_CROP[0] and y >= STATUS_CROP[1] and x + w <= 641 and y + h <= 481


def _status_recovery_needed(rows, width, height):
    if (width, height) != (640, 480):
        return False
    status = [row for row in rows if _in_status_crop(row)]
    if all(any(row['text'].strip() == phrase and row['confidence'] >= .8 for row in status)
           for phrase in STATUS_PHRASES):
        return False
    if any(re.match(r'^(end|press)', re.sub(r'[^a-z]', '', row['text'].casefold())) for row in status):
        return True
    roman_map = any(row['text'].strip().casefold() in ('roman map', 'roman hap')
                    and 40 <= row['center'][1] <= 70 and 30 <= row['center'][0] <= 430
                    and row['confidence'] >= .8 for row in rows)
    moving = any(row['text'].strip().casefold().startswith('moving')
                 and row['center'][0] >= 466 and 245 <= row['center'][1] <= 430 for row in rows)
    return roman_map and not moving


def _status_near_match(text, phrase):
    compact = re.sub(r'[^a-z]', '', text.casefold())
    expected = re.sub(r'[^a-z]', '', phrase.casefold())
    prefix, limit = ('end', 3) if phrase == STATUS_PHRASES[0] else ('press', 4)
    return compact.startswith(prefix) and _near_text(compact, expected, limit)


def _recover_status(rows, raw, conflicts):
    """Recover the pair atomically from actual OCR of the white-glyph crop."""
    local = _prepare_rows(raw, 174, 40, 'status_white_4x')
    if len(local) != 2 or {row['text'].strip() for row in local} != set(STATUS_PHRASES):
        return
    candidates = []
    for phrase in STATUS_PHRASES:
        observed = next(row for row in local if row['text'].strip() == phrase)
        x, y, w, h = observed['provenance'][0]['normalized_bounds']
        mapped = dict(observed, x=(466 + x * 174) / 640, y=(440 + y * 40) / 480,
                      width=w * 174 / 640, height=h * 40 / 480)
        candidate = _prepare_rows([mapped], 640, 480, 'status_white_4x')[0]
        candidate['provenance'][0].update(crop=list(STATUS_CROP), scale=4,
                                          normalized_crop_bounds=[x, y, w, h],
                                          transform='RGB channels >=240 to black; others white; grayscale; bicubic')
        if candidate['confidence'] < .8 or not _in_status_crop(candidate):
            return
        candidates.append(candidate)
    if (candidates[0]['center'][1] >= candidates[1]['center'][1]
            or _overlap(candidates[0], candidates[1])):
        return
    replacements = []
    for candidate, phrase in zip(candidates, STATUS_PHRASES):
        overlaps = [index for index, row in enumerate(rows) if _overlap(row, candidate)]
        nearby = [index for index, row in enumerate(rows) if _in_status_crop(row) and _status_near_match(row['text'], phrase)]
        if not overlaps and not nearby:
            replacements.append((None, candidate))
        elif (len(overlaps) == 1 and nearby == overlaps
              and _same_location(rows[overlaps[0]], candidate)):
            previous = rows[overlaps[0]]
            candidate['provenance'] = previous['provenance'] + candidate['provenance']
            replacements.append((overlaps[0], candidate))
        else:
            conflicts.append(dict(text=phrase, bounds=candidate['bounds'],
                                  reason='ambiguous or contradictory native end-turn status geometry'))
            return
    for index, candidate in replacements:
        if index is None:
            rows.append(candidate)
        else:
            rows[index] = candidate


def recognize(path: str | Path) -> dict:
    path = Path(path).resolve()
    executable = ROOT / '.runtime' / 'ocr'
    if not executable.is_file():
        raise RuntimeError('Build scripts/ocr.swift into .runtime/ocr first')
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as image:
        width, height = image.size
        rows = _prepare_rows(_run_ocr(executable, path), width, height, 'native')
        evidence = dict(passes=['native'], conflicts=[], fallback_errors=[])
        # Analysis copies are temporary and ignored; coordinates always use the
        # original image dimensions, since Vision reports normalized boxes.
        with tempfile.TemporaryDirectory(prefix='ocr-', dir=ROOT / '.runtime') as directory:
            def scaled(scale, resampling, name):
                target = Path(directory) / (name + '.png')
                image.resize((width * scale, height * scale), resampling).save(target)
                evidence['passes'].append(name)
                return _prepare_rows(_run_ocr(executable, target), width, height, name)
            try:
                fallback = scaled(2, Image.Resampling.NEAREST, 'nearest_2x')
                _merge_controls(rows, fallback, evidence['conflicts'])
            except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
                evidence['fallback_errors'].append(dict(pass_name='nearest_2x', error=type(error).__name__))
            # Calibrated recovery is narrowly scoped to this rendered notice:
            # an observed Founded body plus a near-match heading. The accepted
            # heading must then be read exactly by a separate bicubic pass.
            recover_heading = (any(re.search(r'\bFounded:\s*-?\d', row['text'], re.I) for row in rows)
                               and not any(row['text'].strip().casefold() == 'found new city' for row in rows)
                               and any(_heading_near_match(row['text']) for row in rows))
            if recover_heading:
                try:
                    headings = [row for row in scaled(3, Image.Resampling.BICUBIC, 'bicubic_3x')
                                if row['text'].strip().casefold() == 'found new city']
                    if len(headings) == 1:
                        candidate = headings[0]
                        overlaps = [row for row in rows if _overlap(row, candidate)]
                        if len(overlaps) == 1 and _same_location(overlaps[0], candidate) and _heading_near_match(overlaps[0]['text']):
                            previous = overlaps[0]
                            candidate['provenance'] = previous['provenance'] + candidate['provenance']
                            rows[rows.index(previous)] = candidate
                except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
                    evidence['fallback_errors'].append(dict(pass_name='bicubic_3x', error=type(error).__name__))
            if _status_recovery_needed(rows, width, height):
                name = 'status_white_4x'
                try:
                    target = Path(directory) / (name + '.png')
                    image.crop(STATUS_CROP).point(lambda value: 0 if value >= 240 else 255).convert('L').resize(
                        (696, 160), Image.Resampling.BICUBIC).save(target)
                    evidence['passes'].append(name)
                    _recover_status(rows, _run_ocr(executable, target), evidence['conflicts'])
                except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
                    evidence['fallback_errors'].append(dict(pass_name=name, error=type(error).__name__))
    return {'width': width, 'height': height, 'sha256': original_hash,
            'lines': rows, 'text': '\n'.join(row['text'] for row in rows), 'ocr': evidence}


def find_text(observation, text, *, exact=False):
    wanted = text.casefold()
    matches = [row for row in observation['lines']
               if (row['text'].casefold() == wanted if exact else wanted in row['text'].casefold())]
    if len(matches) != 1:
        raise ValueError(f'Game text must match one visible line ({len(matches)} matches)')
    return matches[0]['center']
