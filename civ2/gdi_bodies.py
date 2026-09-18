"""Source-backed herald paragraphs, proven against original GDI pixels.

The measured native layouts are intentionally finite. Only punctuation and at
most two one-edit fixed source words may change. Variables, numbers and choices
are never supplied by state, and no font asset is bundled.
"""
from copy import deepcopy
import re
from zipfile import BadZipFile
from PIL import Image, ImageChops
from .gdi_text import (load_atlas, _sources, _sha, _canonical, _words,
                       ATLAS_ID, ATLAS_SHA256, METRICS_SHA256, ROW_PALETTE,
                       WHITE_RING, BLACK_RING)

SOURCE_PINS = {
    'PROPOSECEASE': '2f5693c4dbe0e845a140a784a1bd4773c0e448258d4a2ba242cd8f5b668590dc',
    'CRUSADE': 'dfa03aa4eb5e386351d27874d5c9b6ed1d871dff7f1ad881678fe28c2250322b',
    'GREETINGS00': '950585acaf81ab9ce622ac94efd3915f89db60c2919745118cfd9ed08e57a682',
    'GREETINGS03': '8bbba02ad91b19004b568fcd7c7ce74c0b1018304b0636df041525afe6708cd4',
    'GAPE': '8d54778744abe523a5779c126082405b0c520ff522c4bbe072712391170260a0',
    'CANCELTREATY1': 'ab31597cd519240587740b360c00ec991b2aa607f4749d47e07941a1f8f65552',
}
# left/top of complete native window; text inset; body rows; radio count;
# exact original sole-OK widget RGB digest (including its entire perimeter).
LAYOUTS = {
    'PROPOSECEASE': (225, 317, 79, 2, 2, '302fdef44a6d776282f8e9bab3050baec2b6c22639973670c4e52223333c09e8'),
    'CRUSADE': (234, 297, 79, 3, 2, 'ae2a6d6f17973d0d0b07e1457bf78cd316fe264d161b7dc70c2f2e6318446da1'),
    'GREETINGS00': (298, 371, 11, 2, 0, '807e29fc9be24409c3a5cbf604eced96277543228750281944fa8ba3eed95a40'),
    'GREETINGS03': (298, 371, 11, 2, 0, '807e29fc9be24409c3a5cbf604eced96277543228750281944fa8ba3eed95a40'),
    'GAPE': (298, 331, 11, 4, 0, '807e29fc9be24409c3a5cbf604eced96277543228750281944fa8ba3eed95a40'),
    'CANCELTREATY1': (294, 297, 11, 3, 2, 'b7c2cd17ba9c6e9153f0e68dd7b50125671250d9d148032db7640d2b600c054c'),
}
PALETTE = (ROW_PALETTE - {(0, 0, 0)}) | {(48, 48, 48)}


def _one_edit_word(a, b):
    """Candidate generation only: a pixel comparison must still prove the word."""
    if (not a.isascii() or not b.isascii() or not a.isalpha() or not b.isalpha()
            or max(len(a),len(b)) > 32 or a.casefold() == b.casefold()):
        return False
    if len(a) == len(b):
        return sum(x != y for x,y in zip(a,b)) == 1
    if abs(len(a)-len(b)) != 1:
        return False
    shorter,longer = (a,b) if len(a) < len(b) else (b,a)
    return any(longer[:i]+longer[i+1:] == shorter for i in range(len(longer)))


def _binding(template, raw):
    """Unique observed-variable binding with <=2 candidate fixed-word edits.

    Each edit retains its global observed token index. No variable is corrected,
    numeric literals are immutable, and case-only guesses are excluded.
    """
    if not raw.isascii() or len(raw) > 600:
        return None
    observed = _words(raw)
    parts = re.findall(r'%STRING\d+|%NUMBER\d+|[A-Za-z0-9]+', template)
    if not 1 <= len(observed) <= 90:
        return None
    found = []; visits = 0; exhausted = False

    def visit(i, j, values, corrections):
        nonlocal visits, exhausted
        visits += 1
        if visits > 10000:
            exhausted = True
        if exhausted or len(found) > 1:
            return
        if i == len(parts):
            if j == len(observed):
                found.append((values,corrections))
            return
        token = parts[i]
        if not token.startswith('%'):
            if j < len(observed) and token == observed[j]:
                visit(i + 1, j + 1, values, corrections)
            elif j < len(observed) and len(corrections) < 2 and _one_edit_word(observed[j],token):
                visit(i + 1,j + 1,values,corrections + [dict(word_index=j,observed=observed[j],source=token)])
            return
        if token in values:
            words = values[token].split()
            if observed[j:j + len(words)] == words:
                visit(i + 1, j + len(words), values, corrections)
            return
        for count in range(1, min(8, len(observed) - j) + 1):
            words = observed[j:j + count]
            if token.startswith('%NUMBER') and (count != 1 or not words[0].isdigit()):
                continue
            visit(i + 1, j + count, {**values, token: ' '.join(words)}, corrections)

    visit(0, 0, {}, [])
    if exhausted or len(found) != 1:
        return None
    values,corrections = found[0]
    rendered = template.replace('_._._.', ' . . .')
    rendered = re.sub(r'%(?:STRING|NUMBER)\d+', lambda m: values[m[0]], rendered)
    # The original paragraph formatter collapses source whitespace. This only
    # generates a candidate; the complete actual glyph mask must prove spacing.
    rendered = re.sub(r'\s+', ' ', rendered).strip()
    expected = list(observed)
    for edit in corrections:
        expected[edit['word_index']] = edit['source']
    return (rendered,values,corrections) if _words(rendered) == expected else None


def _wrap_observed(text, body, corrections=()):
    """Retain observed word-to-row partition; source punctuation stays intact."""
    spans = list(re.finditer(r'[A-Za-z0-9]+', text))
    observed = _words(' '.join(r['text'] for r in body));expected = list(observed)
    for edit in corrections:
        index = edit['word_index']
        if not 0 <= index < len(expected) or expected[index] != edit['observed']:
            return None
        expected[index] = edit['source']
    if _words(text) != expected:
        return None
    counts = [len(_words(r['text'])) for r in body]
    if not all(counts) or sum(counts) != len(spans):
        return None
    result = []
    start = used = 0
    for count in counts[:-1]:
        used += count
        previous, following = spans[used - 1], spans[used]
        separator = text[previous.end():following.start()]
        # Native wrapping is at a space. Never split punctuation inside a word.
        if not separator.endswith(' '):
            return None
        end = following.start()
        result.append(text[start:end].strip())
        start = end
    result.append(text[start:].strip())
    return result if [len(_words(r)) for r in result] == counts else None


def _frame(image, layout):
    left, top, inset, count, radios, button_sha = layout
    p = image.load()
    bands = [([(x, y) for x in range(left, 640) for y in (top, 478)]
              + [(x, y) for x in (left, 639) for y in range(top, 479)], 0),
             ([(x, top + 1) for x in range(left + 1, 638)]
              + [(left + 1, y) for y in range(top + 1, 478)], 223),
             ([(x, y) for x in (637, 638) for y in range(top + 2, 478)]
              + [(x, 477) for x in range(left + 2, 639)], 65)]
    if any(p[x, y] != (value, value, value) for points, value in bands for x, y in points):
        return None
    button = (left + 7, 447, 633, 475)
    if _sha(image.crop(button).tobytes()) != button_sha:
        return None
    centers = []
    # Count every native ring throughout this window's text area, including
    # possible extra choices. Nothing is inferred from OCR's row count.
    for y in range(top + 24, 439):
        for x in range(left + 12, 629):
            if (all(p[x + dx, y + dy] == (255, 255, 255) for dx, dy in WHITE_RING)
                    and all(p[x + dx, y + dy] == (0, 0, 0) for dx, dy in BLACK_RING)):
                centers.append([x, y])
    expected = [[left + inset + 16, 402], [left + inset + 16, 427]] if radios else []
    if centers != expected:
        return None
    return dict(frame_bounds=[left, top, 640, 479], button_bounds=list(button),
                button_rgb_sha256=button_sha, radio_centers=centers,
                frame_border_sha256=_sha(bytes(p[x, y][0] for points, _ in bands for x, y in points)))


def _paragraph(image, texts, body, layout, atlas):
    left, top, inset, count, radios, _ = layout
    ox, oy = left + inset, top + 30
    region = (ox, oy, 637, 390 if radios else 447)
    crop = image.crop(region)
    colors = crop.getcolors(crop.width * crop.height)
    if not colors or any(color not in PALETTE for _, color in colors):
        return None
    actual = crop.getchannel('R').point(lambda v: 255 if v == 48 else 0)
    expected = Image.new('L', actual.size)
    bounds = []
    for i, (text, row) in enumerate(zip(texts, body)):
        glyphs = atlas.render(text)
        # Original TextOut clips negative left bearings at the shared origin.
        glyphs.paste(0, (0, 0, 4, glyphs.height))
        box = glyphs.getbbox()
        if box is None or box[2] - 4 > crop.width or box[3] - 4 + 20 * i > crop.height:
            return None
        x, y = ox - 4 + box[0], oy - 4 + 20 * i + box[1]
        w, h = box[2] - box[0], box[3] - box[1]
        if (abs(x + w / 2 - row['center'][0]) > 14
                or abs(y + h / 2 - row['center'][1]) > 6):
            return None
        expected.paste(glyphs, (-4, -4 + 20 * i), glyphs)
        bounds.append([x, y, w, h])
    if ImageChops.difference(actual, expected).getbbox() is not None:
        return None
    return bounds, dict(region=list(region), region_rgb_sha256=_sha(crop.tobytes()),
        foreground_rgb=[48, 48, 48], comparison='complete paragraph foreground mask with calibrated palette',
        textout_origin=[ox, oy], line_pitch=20, clip_left_at_textout_origin=True,
        extra_pixels=0, missing_pixels=0)


def recover_herald_paragraph(image, rows, executable=None, directory=None, evidence=None,
                             *, atlas=None, game_text=None):
    """Atomic optional OCR fallback; final ordinary classifier keeps authority."""
    if image.size != (640, 480) or not isinstance(rows, list) or (evidence or {}).get('conflicts'):
        return False
    headings = [r for r in rows if r['text'].endswith(' Emissary') and r.get('confidence', 0) >= .8
                and 420 <= r['center'][0] <= 485 and 300 <= r['center'][1] <= 399]
    controls = [r for r in rows if r['text'] in ('OK', 'Cancel', 'Yes', 'No', 'Help', 'Goal')]
    if (len(headings) != 1 or len(controls) != 1 or controls[0]['text'] != 'OK'
            or controls[0].get('confidence', 0) < .8 or not 450 <= controls[0]['center'][1] <= 467
            or abs(headings[0]['center'][0] - controls[0]['center'][0]) > 8):
        return False
    if game_text is None:
        try:
            game_text, _ = _sources()
        except (OSError, ValueError, KeyError, BadZipFile):
            return False
    from .dialogs import dialog_resources, classify_dialog
    templates = [t for t in dialog_resources(game_text) if t['tag'] in SOURCE_PINS
                 and _sha(_canonical(t)) == SOURCE_PINS[t['tag']]
                 and sum(line.strip() == '@' + t['tag'] for line in game_text.splitlines()) == 1]
    image = image.convert('RGB')
    proposals = []
    for template in templates:
        tag = template['tag']
        layout = LAYOUTS[tag]
        left, top, inset, count, radios, _ = layout
        if not top + 8 <= headings[0]['center'][1] <= top + 22:
            continue
        end = 390 if radios else 447
        body = sorted([r for r in rows if left + 3 <= r['center'][0] < 637
                       and top + 24 <= r['center'][1] < end], key=lambda r: r['center'][1])
        if (len(body) != count or any(r.get('confidence', 0) < .8 for r in body)
                or any(abs((b['center'][1] - a['center'][1]) - 20) > 4 for a, b in zip(body, body[1:]))):
            continue
        binding = _binding(template['body'], ' '.join(r['text'] for r in body))
        if binding is None:
            continue
        texts = _wrap_observed(binding[0], body, binding[2])
        if texts is None:
            continue
        normalized = [t.replace(' . . .', '...') for t in texts]
        # Existing readers may already retain the source's ellipsis spacing.
        # This is only a no-op check, never an alternative acceptance proof.
        existing = [re.sub(r' *\.\s*\.\s*\.', '...', r['text']) for r in body]
        if normalized == existing:
            continue
        frame = _frame(image, layout)
        if frame is None:
            continue
        atlas = atlas or load_atlas()
        if atlas is None:
            return False
        try:
            match = _paragraph(image, texts, body, layout, atlas)
        except ValueError:
            continue
        if match is None:
            continue
        bounds, proof = match
        proposed = deepcopy(rows)
        for old, text, box in zip(body, normalized, bounds):
            x, y, w, h = box
            row = deepcopy(old)
            row.update(text=text, bounds=box, center=[round(x + w / 2), round(y + h / 2)], confidence=1,
                       x=x / 640, y=y / 480, width=w / 640, height=h / 480)
            row['provenance'] = deepcopy(old.get('provenance', [])) + [dict(
                preprocessing='original_gdi_paragraph_exact', text=text, confidence=1,
                normalized_bounds=[x / 640, y / 480, w / 640, h / 480],
                atlas_id=ATLAS_ID, atlas_sha256=ATLAS_SHA256, metrics_sha256=METRICS_SHA256,
                source_template=tag, source_sha256=SOURCE_PINS[tag],
                observed_variable_bindings=binding[1],static_word_corrections=deepcopy(binding[2]),
                **proof, **frame)]
            proposed[rows.index(old)] = row
        # Temporary RGB identity only: normal recognition/classification later
        # retains and binds the unchanged original captured PNG SHA256.
        checked = classify_dialog(dict(width=640, height=480, sha256=_sha(image.tobytes()), lines=proposed),
                                  game_text=game_text)
        if (not checked.get('supported') or checked.get('resource_tag') != tag
                or bool(checked.get('requires_model')) != bool(radios)
                or len(checked.get('options', [])) != (radios or 1)
                or checked.get('mechanical_action') != (None if radios else 'acknowledge_information')
                or [b['text'] for b in checked.get('buttons', [])] != ['OK']):
            continue
        if radios and any(abs(option['center'][1] - center[1]) > 6
                          for option, center in zip(checked['options'], frame['radio_centers'])):
            continue
        # A body target and its offered action must be the same observed target.
        # The general classifier matches each source row independently; this
        # optional proof additionally binds repeated variables across the rows.
        options_match = True
        for option, original in zip(checked['options'] if radios else [], template['options']):
            expected = re.sub(r'%(?:STRING|NUMBER)\d+', lambda m: binding[1].get(m[0], m[0]), original)
            observed = re.sub(r'^(?:O|[○●•])\s+', '', option['text'])
            if '%' in expected or _words(expected) != _words(observed):
                options_match = False
        if not options_match:
            continue
        proposals.append((proposed, tag, proof, frame))
    if len(proposals) != 1:
        return False
    proposed, tag, proof, frame = proposals[0]
    rows[:] = proposed
    if evidence is not None:
        evidence.setdefault('passes', []).append('original_gdi_paragraph_exact')
        evidence.setdefault('gdi_paragraph', []).append(dict(resource_tag=tag, source_sha256=SOURCE_PINS[tag],
            atlas_id=ATLAS_ID, atlas_sha256=ATLAS_SHA256, image_rgb_sha256=_sha(image.tobytes()), **proof, **frame))
    return True
