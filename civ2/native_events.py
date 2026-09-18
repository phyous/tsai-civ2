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
from .notice_icons import proven_notice_icon


EVENT_TITLES = {
    'GOLDENAGE': 'golden age of philosophy',
    'NEWFORTRESS': 'new order: fortress',
    'ADJACENTCITY': 'civ rules: cities',
    'CIVADVANCE': 'civilization advance',
    'DESTROYED': 'defense minister',
    'CITYCAPTURE': 'defense minister',
    'MULTIPLEWIN': 'defense minister',
    'MULTIPLELOSE': 'defense minister',
    'TOOKCIV': 'civilization advance stolen!',
    'CARAVAN': 'trade route',
    'FOODCARAVAN': 'trade route',
    'CARAVANOTHER': 'trade route',
    'CARAVANHOME': 'civ rules: trade units',
    'BADSPACE': 'excess spaceship parts',
    'NOSPACESHIPS': 'space ships',
    **dict.fromkeys(('SPACERACE','LAUNCHED','NOFURTHER','SPACERETURNS','SPACEDESTROYED'), 'science advisor'),
    'SNEAK': 'defense minister',
    'SURPRISESCROLLS': 'village',
    'SURPRISEMETALS': 'village',
    'SURPRISEMERCS': 'village',
    'TERMS': 'foreign minister',
    'WITHDRAWN': 'foreign minister',
    'WITHDRAWN1': 'foreign minister',
    'BUILT2': 'foreign advisor',
    **dict.fromkeys(('STARTWONDER','SWITCHWONDER','ABANDONWONDER','ALMOSTWONDER'), 'travellers report'),
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
                 # Original005/1688: complete Horseback Riding discovery and
                 # sole OK. Preserve this observed title, not guessed glyphs.
                 # Original011/735: complete Ceremonial Burial discovery and
                 # sole OK; the original pixels show Civilization Advance.
                 # Original012/663: complete two-line Monarchy discovery;
                 # this measured title spelling still requires the full body.
                 'CIVADVANCE': {'ciadization advance', 'cialization advance', 'cinlization adsance', 'cinlization advance'},
                 # Original006/608: complete destruction notice and sole OK.
                 'DESTROYED': {'detense ifinister'},
                 # Original010/2521: two independent 4x title crops, full
                 # pinned capture/plunder notice and the sole aligned OK.
                 'CITYCAPTURE': {'defense mfinister'},
                 # Original010/2533: independent title/body crops after the
                 # Hispalis capture, with the complete pinned TOOKCIV notice.
                 'TOOKCIV': {'cialization advance stolen!'},
                 # Original009/570: full sneak-attack body and sole OK.
                 'SNEAK': {'detense mfinister'},
                 # Original011/1245: complete source treaty-withdrawal reminder,
                 # including its two-square radius, and the sole observed OK.
                 'TERMS': {'foreign ifinister'},
                 # Original011/1629: after a separate actual Withdraw choice,
                 # complete singular relocation notice and sole observed OK.
                 'WITHDRAWN1': {'foreign ifinister'}}
RULE_REJECTIONS = {'ADJACENTCITY': 'Cities cannot be built in adjacent squares.'}
# Reviewed complete original GAME.TXT records. These narrow additions have
# source/synthetic coverage; they are not a claim of live modal calibration.
COMBAT_NOTICE_RESOURCES = {
    'CITYCAPTURE': '6d85a84bf5749949f3c4fcd9915ca8f44dfc80e2ce6b54069252be45c1a7d1fe',
    'MULTIPLEWIN': '72e8bd528879eca5bff6259e6976b83a451aa9724dce6e94161d347d51504438',
    'MULTIPLELOSE': 'dcb38e4e3fff4ce44a83d9834d5d7f69e512deb089af8a31e048b1015f73fb7f',
    'TOOKCIV': 'ef12f6bbbaeed93332c5c54ee7d7587c579421cd3da72ff5be8e1aed81a4a192',
}
TRADE_NOTICE_RESOURCES = {
    'CARAVAN': '81e7dd7878249d0f110efac44694cd6f1509d55e3a34ea75c9095286e3299a4f',
    'FOODCARAVAN': '8d11a59207b1740e82c609c1d2360e28156aec5656290193feb35ca7152036c9',
    'CARAVANHOME': 'b27f78a773aeab795a9a70211c3274edf4ba8caec0bd6feaa755e49b4b632418',
    'CARAVANOTHER': '580ee3496eb05f126e9d2660ced4efec6fc3e5cf5ac3d66174252558cb178e8c',
}
ORDER_NOTICE_RESOURCES = {
    'NEWFORTRESS': '7008caabad90b14e8e354ed60484e54359857ebf4f5da5284f35630d45028f8c',
}
PHILOSOPHY_NOTICE_RESOURCES = {
    'GOLDENAGE': 'b8fae752a1051a78b7f42dbf360d7473c55bbeb5acf8baecb5d7302987d2b135',
}
FOREIGN_NOTICE_RESOURCES = {
    'BUILT2': '2c09eb9b67c932e3391f839b3df04e5512edf656bc324a0c66adb8f7ef9a5427',
}
SPACE_NOTICE_RESOURCES = {
    'BADSPACE':'fb52834c18c6ab1d0a0c0df09e9db4a0e578ddc7244656c075d4ab35ba410044',
    'SPACERACE':'b0858a7a0044cfe83240c58ef8408e3758c6ead7c55af1bd63fa9daf27d87c64',
    'LAUNCHED':'f72afe8d8b70d5dd437a65e110f30ed0dd09f8252945e4b79f230e4616c6737b',
    'NOFURTHER':'31fee19ab5b62e9be404bc6bfba069164645211a5c17bcad337f0ad151f94679',
    'SPACERETURNS':'55569f9db9b0930cac78f901a0e0c4d0a758f5408bddbaeff92e56af68528852',
    'SPACEDESTROYED':'735a70a9192b7b758f5c717ca6fea505c9dad4338fe0273c2dd89e7551c2eef8',
    'NOSPACESHIPS':'b49256ff98ffcff01e9883a2ab25574fbdb2ea767a697d65e4e8d7e9e7ed4deb',
}
# Original LABELS.TXT lines191–194; do not let a variable verb absorb a choice.
CAPTURE_VERBS = ('capture', 'liberate', 'captured', 'liberated')
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
                               source_line=index,notice_icon_bounds=proven_notice_icon(row,observation['sha256'])))
    return result


def _body_pattern(body, values, *, minimum_anchors=5, terminal_dot_optional=True):
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
    if len(re.sub(r'[^a-z]', '', anchors)) < minimum_anchors:
        return None
    expression=''.join(chunks)
    # Original006/734 omits only the last printed dot. Preserve every lexical
    # token and internal punctuation; these are already whitelisted notices
    # with no choices and one independently observed OK control.
    if terminal_dot_optional and text.endswith('.') and expression.endswith(r'\.'):
        expression=expression[:-2]+r'\.?'
    return re.compile(expression)


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
        pinned_hash = (COMBAT_NOTICE_RESOURCES.get(tag) or TRADE_NOTICE_RESOURCES.get(tag)
                       or FOREIGN_NOTICE_RESOURCES.get(tag) or SPACE_NOTICE_RESOURCES.get(tag)
                       or ORDER_NOTICE_RESOURCES.get(tag) or PHILOSOPHY_NOTICE_RESOURCES.get(tag))
        pinned = pinned_hash is not None
        if pinned and hashlib.sha256(json.dumps(resource, sort_keys=True,
                separators=(',', ':'), ensure_ascii=False).encode()).hexdigest() != pinned_hash:
            continue
        tag_values = placeholder_values.get(tag, {})
        if not isinstance(tag_values, dict):
            continue
        if tag == 'CITYCAPTURE':
            tag_values = {**tag_values, 'STRING3': CAPTURE_VERBS}
        if tag in ('BUILT', 'BUILT2', 'BUILT3') and not tag_values.get('STRING3'):
            continue
        # TOOKCIV has only "take" as fixed prose. Its complete source hash and
        # exact distinctive title permit four letters for that template alone.
        pattern = _body_pattern(body, tag_values, minimum_anchors=4 if tag=='TOOKCIV' else 5,
                                terminal_dot_optional=not pinned)
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
        artwork=[]
        if tag=='CIVADVANCE':
            for row in body_rows:
                box=row.get('notice_icon_bounds')
                prose=[r for r in body_rows if r is not row]
                if (box and prose and top<=box[1] and box[1]+box[3]<=bottom
                        and box[0]+box[2]<min(r['bounds'][0] for r in prose)):
                    artwork.append(row)
            if len(artwork)>1:continue
            body_rows=[r for r in body_rows if r not in artwork]
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
        matches.append((resource, heading, body_rows,artwork))
    if len(matches) != 1:
        return result
    resource, heading, body_rows,artwork = matches[0]
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
    if artwork:result['evidence']['decorative_icon']={'source':'Original 72x40 gold-framed icon; 832 exact border pixels',
        'source_image_sha256':observation['sha256'],'bounds':artwork[0]['notice_icon_bounds'],
        'ignored_raw_ocr':artwork[0]['text'],'source_line':artwork[0]['source_line']}
    if resource['tag'] in RULE_REJECTIONS:
        result['native_rejection'] = dict(tag=resource['tag'], body=observed_body,
            title=heading['text'], source='original GAME.TXT',
            template_sha256=result['evidence']['template_sha256'],
            observation_sha256=observation['sha256'])
    return result
