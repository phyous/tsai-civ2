"""Recognize reviewed informational GAME.TXT events from complete visible OCR.

No input is dispatched here. Resource templates must come from the original
game text. A matching title alone, an OK button alone, or a partly read body
cannot authorize acknowledgement. Strategic menus and editor/UI templates are
outside this module's reviewed event tags.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata


EVENT_TITLES = {
    'ADJACENTCITY': 'civ rules: cities',
    'CIVADVANCE': 'civilization advance',
    **dict.fromkeys(('DECREASE', 'FOODSHORTAGE', 'BUILT', 'BUILT3', 'DISORDER',
                     'RESTORED', 'WELOVEKING', 'WEDONTLOVEKING', 'FURTHERGROWTH',
                     'INHOCK', 'FERTILE', 'UPGRADED', 'UPGRADE'), 'domestic advisor'),
    **dict.fromkeys(('MANHATTAN', 'SUPPORT'), 'military advisor'),
    **dict.fromkeys(('NEWGOVT', 'CHERNOBYL', 'INCIDENTALLIED', 'INCIDENTWAR',
                     'INCIDENTTERROR', 'SENATESCANDAL'), 'newspaper'),
    **dict.fromkeys(('PLANTEDNUKE', 'FEARWARMING', 'GLOBALWARMING'), '(newspaper)'),
}
# Reviewed against original screenshots B003/74 and A002/254 respectively.
# These aliases never replace observed text and still require a complete body
# from the matching original resource and the sole aligned OK control.
TITLE_ALIASES = {'ADJACENTCITY': {'civ rules: cines'},
                 'CIVADVANCE': {'ciadization advance'}}
RULE_REJECTIONS = {'ADJACENTCITY': 'Cities cannot be built in adjacent squares.'}
OBSERVED_EVENT_TITLES = set(EVENT_TITLES.values()) | set().union(*TITLE_ALIASES.values())
CONTROLS = {'ok', 'cancel', 'yes', 'no', 'help', 'continue', 'back', 'next', 'done', 'close'}
TOKEN = re.compile(r'%(STRING|NUMBER)(\d{1,2})', re.I)


def _normal(text):
    return ' '.join(unicodedata.normalize('NFKC', text).translate(
        str.maketrans({'“': '"', '”': '"', '’': "'", '‘': "'"})).casefold().split())


def _rows(observation):
    if not isinstance(observation, dict):
        return None
    width, height = observation.get('width'), observation.get('height')
    if any(type(n) is not int or not 1 <= n <= 4096 for n in (width, height)):
        return None
    if not re.fullmatch(r'[a-f0-9]{64}', str(observation.get('sha256', ''))):
        return None
    source = observation.get('lines')
    if not isinstance(source, list) or len(source) > 1000:
        return None
    result = []
    for index, row in enumerate(source):
        if not isinstance(row, dict) or not isinstance(row.get('text'), str) or len(row['text']) > 2000:
            return None
        bounds, center = row.get('bounds'), row.get('center')
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4
                or not isinstance(center, (list, tuple)) or len(center) != 2
                or any(type(n) is not int for n in [*bounds, *center])):
            return None
        x, y, w, h = bounds
        confidence = row.get('confidence', 1.)
        if (w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width + 1 or y + h > height + 1
                or not 0 <= center[0] < width or not 0 <= center[1] < height
                or not x - 1 <= center[0] <= x + w + 1 or not y - 1 <= center[1] <= y + h + 1
                or type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not 0 <= confidence <= 1):
            return None
        if row['text'].strip():
            result.append(dict(text=row['text'].strip(), normal=_normal(row['text']),
                               bounds=list(bounds), center=list(center), confidence=confidence,
                               source_line=index))
    return result


def _body_pattern(body, values):
    """Bind repeated placeholders consistently; require a real lexical anchor."""
    if not isinstance(body, str) or not body.strip() or len(body) > 2000:
        return None
    if not isinstance(values, dict) or len(values) > 16:
        return None
    tokens = list(TOKEN.finditer(body))
    if len(tokens) > 16 or '%' in TOKEN.sub('', body):
        return None
    chunks, seen, position, anchors = [], set(), 0, ''
    # Normalizing complete strings before splitting would lowercase the token
    # names; token matching is deliberately case-insensitive.
    text = _normal(body.replace('^', ' '))
    for token in TOKEN.finditer(text):
        literal = text[position:token.start()]
        chunks.append(re.escape(literal)); anchors += literal
        name = token.group(1).upper() + token.group(2)
        if name in seen:
            chunks.append(f'(?P={name})')
        else:
            supplied = values.get(name)
            if supplied is not None:
                if (not isinstance(supplied, (list, tuple)) or not 1 <= len(supplied) <= 64
                        or any(not isinstance(value, str) or not value.strip() or len(value) > 120 for value in supplied)):
                    return None
                normalized = {_normal(value) for value in supplied}
                value_pattern = '(?:' + '|'.join(re.escape(value) for value in sorted(normalized)) + ')'
                anchors += min(normalized, key=len)
            elif name.startswith('NUMBER'):
                value_pattern = r'[+-]?\d[\d,]{0,19}'
            else:
                # No punctuation or question can be hidden inside an unbound
                # game name. Sentence punctuation belongs to the template.
                value_pattern = r"[\w][\w '\-(),]{0,119}?"
            chunks.append(f'(?P<{name}>{value_pattern})'); seen.add(name)
        position = token.end()
    chunks.append(re.escape(text[position:])); anchors += text[position:]
    # BUILT consists entirely of placeholders: its original completion verb
    # must be supplied from LABELS.TXT before it can be recognized safely.
    if len(re.sub(r'[^a-z]', '', anchors)) < 5:
        return None
    return re.compile(''.join(chunks))


def classify_information(observation, resources, *, placeholder_values=None):
    """Return an information result only for one complete original event.

    ``resources`` is the output of dialogs.dialog_resources(GAME.TXT).
    ``placeholder_values`` optionally supplies finite original substitutions by
    tag, e.g. BUILT -> STRING3 -> completion verbs read from LABELS.TXT. These
    values constrain matching; they never become invented observation text.
    Unsupported results contain no mechanical action or actionable options.
    """
    result = dict(kind='unknown', supported=False, mechanical_action=None,
                  requires_model=False, title='', options=[], buttons=[], resource_tag=None,
                  reason='No unique complete informational original event')
    rows = _rows(observation)
    if (rows is None or not isinstance(resources, list) or len(resources) > 1000
            or (placeholder_values is not None and not isinstance(placeholder_values, dict))):
        result['reason'] = 'Invalid event observation or resource input'
        return result
    placeholder_values = placeholder_values or {}
    controls = [row for row in rows if row['normal'] in CONTROLS]
    # Global uniqueness avoids borrowing a background OK from another dialog.
    if len(controls) != 1 or controls[0]['normal'] != 'ok':
        result['reason'] = 'A sole observed OK control is required'
        return result
    ok = controls[0]
    matches = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        tag, title, body = (resource.get(key) for key in ('tag', 'title', 'body'))
        if (not isinstance(tag, str) or tag not in EVENT_TITLES or not isinstance(title, str) or _normal(title) != EVENT_TITLES[tag]
                or resource.get('options') != [] or resource.get('listbox') is not False
                or resource.get('buttons') not in ([], ['OK'])):
            continue
        if tag in RULE_REJECTIONS and _normal(body or '') != _normal(RULE_REJECTIONS[tag]):
            continue
        tag_values = placeholder_values.get(tag, {})
        if not isinstance(tag_values, dict):
            continue
        if tag in ('BUILT', 'BUILT3') and not tag_values.get('STRING3'):
            continue
        pattern = _body_pattern(body, tag_values)
        if pattern is None:
            continue
        allowed_titles = {_normal(title)} | TITLE_ALIASES.get(tag, set())
        titles = [row for row in rows if row['normal'] in allowed_titles]
        if len(titles) != 1:
            continue
        heading = titles[0]
        if (heading['confidence'] < .8 or ok['confidence'] < .8
                or abs(heading['center'][0] - ok['center'][0]) > 8
                or ok['bounds'][1] - (heading['bounds'][1] + heading['bounds'][3]) < 16):
            continue
        declared_width = resource.get('width')
        if declared_width is not None and (type(declared_width) is not int or not 100 <= declared_width <= observation['width']):
            continue
        half = max((declared_width or 320) / 2, heading['bounds'][2] / 2 + 8, ok['bounds'][2] / 2 + 8)
        top, bottom = heading['bounds'][1] + heading['bounds'][3], ok['bounds'][1]
        ocr = observation.get('ocr', {})
        conflicts = ocr.get('conflicts', []) if isinstance(ocr, dict) else None
        if not isinstance(conflicts, list):
            continue
        if any(isinstance(conflict, dict) and isinstance(conflict.get('bounds'), list)
               and len(conflict['bounds']) == 4
               and all(type(n) is int for n in conflict['bounds'])
               and conflict['bounds'][0] < heading['center'][0] + half
               and conflict['bounds'][0] + conflict['bounds'][2] > heading['center'][0] - half
               and conflict['bounds'][1] < ok['bounds'][1] + ok['bounds'][3]
               and conflict['bounds'][1] + conflict['bounds'][3] > heading['bounds'][1]
               for conflict in conflicts):
            continue
        body_rows = [row for row in rows if row not in (heading, ok)
                     and top <= row['center'][1] <= bottom
                     and abs(row['center'][0] - heading['center'][0]) <= half]
        if not body_rows or any(row['confidence'] < .8 or row['bounds'][1] < top - 2
                                or row['bounds'][1] + row['bounds'][3] > bottom + 2
                                for row in body_rows):
            continue
        body_rows.sort(key=lambda row: (row['bounds'][1], row['bounds'][0]))
        observed_body = ' '.join(row['normal'] for row in body_rows)
        if len(observed_body) > 2000 or pattern.fullmatch(observed_body) is None:
            continue
        # A second visible advisor/event heading indicates ambiguous layers.
        if any(row is not heading and row['normal'] in OBSERVED_EVENT_TITLES for row in rows):
            continue
        matches.append((resource, heading, body_rows))
    if len(matches) != 1:
        return result
    resource, heading, body_rows = matches[0]
    option = {key: ok[key] for key in ('text', 'center', 'source_line', 'confidence')}
    option.update(control='button', enabled=None)
    observed_body = '\n'.join(row['text'] for row in body_rows)
    result.update(kind='rule_rejection' if resource['tag'] in RULE_REJECTIONS else 'information',
                  supported=True, mechanical_action='acknowledge_information',
                  title=heading['text'], options=[option], buttons=[option], resource_tag=resource['tag'], reason=None,
                  evidence=dict(source='original GAME.TXT event template', source_tag=resource['tag'],
                                template_sha256=hashlib.sha256(json.dumps(resource, sort_keys=True).encode()).hexdigest(),
                                title_source_line=heading['source_line'],
                                observed_title=heading['text'], observed_body=observed_body,
                                title_match='exact' if heading['normal']==_normal(resource['title']) else 'reviewed OCR alias',
                                body_source_lines=[row['source_line'] for row in body_rows],
                                button_source_line=ok['source_line'],
                                match='complete visible title and body; sole observed OK'))
    if resource['tag'] in RULE_REJECTIONS:
        result['native_rejection'] = dict(tag=resource['tag'], body=observed_body,
            title=heading['text'], source='original GAME.TXT',
            template_sha256=result['evidence']['template_sha256'],
            observation_sha256=observation['sha256'])
    return result
