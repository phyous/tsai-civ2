"""Source-bound public historian reports; printed gaps are never filled in."""
import hashlib
import json
import re
import unicodedata

SOURCE = 'Original HISTORY, HISTORIANS, HISTORIES and HISTORYRANK resources'
# Measured original headings in005/430,004/988,006/1040,008/165,009/207. Keep raw OCR.
TITLE_ALIASES = {'ciadization i', 'crnlization i', 'cindivationl', 'civlivaition i', 'cimlivation'}


def _normal(text):
    return ' '.join(unicodedata.normalize('NFKC', text).translate(
        str.maketrans({'“':'"', '”':'"', '‘':"'", '’':"'"})).casefold().split()).strip(' .:!?')


def _distance(a, b):
    previous = list(range(len(b)+1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(x != y)))
        previous = current
    return previous[-1]


def classify_history_notice(observation, rows, game_text, resources):
    if (observation.get('width'), observation.get('height')) != (640, 480):
        return None
    templates = [t for t in resources if t['tag'] == 'HISTORY']
    expected = "%string1 completes his epic history: 'the %string2 civilizations in the world'"
    if (len(templates) != 1 or _normal(templates[0]['title']) != 'civilization ii'
            or templates[0]['width'] != 480 or templates[0]['options'] or templates[0]['buttons']
            or templates[0]['listbox'] or _normal(templates[0]['body'].replace('^', ' ')) != expected):
        return None

    def section(tag):
        matches = re.findall(r'(?ms)^@'+re.escape(tag)+r'\s*\n(.*?)(?=^@|\Z)', game_text or '')
        if len(matches) != 1:
            return []
        return [s.strip() for s in matches[0].splitlines() if s.strip() and not s.lstrip().startswith(';')]

    authors, categories, ranks = section('HISTORIANS'), section('HISTORIES'), section('HISTORYRANK')
    if (not authors or authors[0] != str(len(authors)-1) or len(authors) < 2
            or not categories or len(ranks) != 7 or len(set(ranks)) != 7):
        return None
    controls = [r for r in rows if r['normal'] in
                {'ok', 'cancel', 'yes', 'no', 'help', 'close', 'continue', 'back', 'next', 'done', 'exit'}]
    if len(controls) != 1 or controls[0]['text'] != 'OK':
        return None
    ok = controls[0]
    headers = [r for r in rows if any(r['normal'] == _normal(a+' completes his epic history:') for a in authors[1:])]
    if len(headers) != 1:
        return None
    header = headers[0]
    y = header['center'][1]
    if not 90 <= y <= 300 or not 310 <= header['center'][0] <= 330:
        return None
    category = [r for r in rows if r['normal'].strip('"\'').replace(' ', '') in
                {_normal('The '+c+' Civilizations in the World').replace(' ', '') for c in categories}
                and 16 <= r['center'][1]-y <= 26 and abs(r['center'][0]-header['center'][0]) <= 8]
    title = [r for r in rows if 16 <= y-r['center'][1] <= 30
             and 270 <= r['bounds'][0] <= 290 and 65 <= r['bounds'][2] <= 100
             and abs(r['center'][0]-header['center'][0]) <= 8
             and (r['normal'] in TITLE_ALIASES or _distance(r['normal'], 'civilization ii') <= 3)]
    visible = [r for r in rows if y+35 <= r['center'][1] < ok['center'][1]-15
               and 75 <= r['bounds'][0] <= 95]
    if (len(title) != 1 or len(category) != 1 or not 1 <= len(visible) <= 7
            or not 310 <= ok['center'][0] <= 330
            or not 16 <= ok['center'][1]-max(r['center'][1] for r in visible) <= 44):
        return None
    numbers = []
    for r in visible:
        match = re.fullmatch(r'([1-7])\. the ([a-z]+) civilization of the ([a-z][a-z -]{1,59})', r['normal'])
        if not match or _normal(ranks[int(match[1])-1]) != match[2]:
            return None
        numbers.append(int(match[1]))
    if numbers != sorted(set(numbers)) or any(a['center'][1] >= b['center'][1] for a, b in zip(visible, visible[1:])):
        return None
    inside = [r for r in rows if 75 <= r['center'][0] <= 565 and y-35 <= r['center'][1] <= ok['center'][1]+10]
    allowed = [*title, header, *category, *visible, ok]
    if (any(r not in allowed for r in inside) or any(r['confidence'] < .8 for r in allowed)
            or observation.get('ocr', {}).get('conflicts')):
        return None
    button = {k:ok[k] for k in ('text', 'center', 'source_line', 'confidence')}
    button.update(control='button', enabled=None)
    body = [header, *category, *visible]
    return {'button':button, 'title':title[0]['text'], 'evidence':{
        'source':SOURCE, 'template_sha256':hashlib.sha256(json.dumps(templates[0], sort_keys=True).encode()).hexdigest(),
        'game_text_sha256':hashlib.sha256(game_text.encode()).hexdigest(),
        'image_sha256':observation['sha256'], 'observed_body':'\n'.join(r['text'] for r in body),
        'source_lines':[r['source_line'] for r in body], 'observed_rows':[r['text'] for r in allowed],
        'scope':'Acknowledge the visible report only; missing civilizations and ranks remain unknown'}}
