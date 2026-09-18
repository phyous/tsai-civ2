"""Exact original title pixels above a complete PROMOTED informational notice."""
from copy import deepcopy
import re
from zipfile import BadZipFile
from .gdi_text import (_sources, _sha, _canonical, REGULAR_ATLAS_ID,
                       REGULAR_ATLAS_SHA256, REGULAR_METRICS_SHA256)
from .gdi_titles import _render, _maskrows, PALETTE

SOURCE_SHA256 = '104c1d26e73dc17b890436f2535cdae9990b9b81e75ba9b8cfb2e7fdb8b12f7d'
TITLE_REGION = (171, 186, 491, 211)


def recover_promotion_title(image, rows, executable=None, directory=None, evidence=None, *, game_text=None):
    if image.size != (640, 480) or (evidence or {}).get('conflicts'):
        return False
    controls = [r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','continue')]
    if (len(controls) != 1 or controls[0]['text'] != 'OK' or controls[0].get('confidence', 0) < .8
            or not 312 <= controls[0]['center'][0] <= 329 or not 276 <= controls[0]['center'][1] <= 288):
        return False
    titles = [r for r in rows if r.get('confidence', 0) >= .8 and 316 <= r['center'][0] <= 326
              and 194 <= r['center'][1] <= 204 and 80 <= r['bounds'][2] <= 160]
    if len(titles) != 1 or titles[0]['text'] == 'Defense Minister':
        return False
    old = titles[0]
    body = sorted([r for r in rows if 171 <= r['center'][0] <= 491 and 211 < r['center'][1] < 270],
                  key=lambda r: r['center'][1])
    if (len(body) != 2 or any(r.get('confidence', 0) < .8 for r in body)
            or not re.fullmatch(r'For valor in combat, our [A-Za-z][A-Za-z -]{0,60} unit has', body[0]['text'])
            or body[1]['text'] != 'been promoted to Veteran status.'):
        return False
    if game_text is None:
        try:
            game_text, _ = _sources()
        except (OSError, ValueError, KeyError, BadZipFile):
            return False
    from .dialogs import dialog_resources, classify_dialog
    sources = [r for r in dialog_resources(game_text) if r['tag'] == 'PROMOTED']
    if (len(sources) != 1 or _sha(_canonical(sources[0])) != SOURCE_SHA256
            or sum(line.strip() == '@PROMOTED' for line in game_text.splitlines()) != 1):
        return False
    crop = image.convert('RGB').crop(TITLE_REGION)
    colors = crop.getcolors(crop.width * crop.height)
    if not colors or any(r != g or r != b or r not in PALETTE for _, (r,g,b) in colors):
        return False
    gray = crop.getchannel('R')
    actual = _maskrows(gray.point(lambda v: 255 if v == 0 else 0))
    gray134 = _maskrows(gray.point(lambda v: 255 if v == 134 else 0))
    try:
        w, h, black, gray = _render('Defense Minister')
    except ValueError:
        return False
    matches = []
    for x in range(crop.width - w + 1):
        shifted = [v << x for v in black]
        for y in range(crop.height - h + 1):
            if (actual == [0]*y + shifted + [0]*(crop.height-h-y)
                    and all(((v << x) & gray134[y+i]) == (v << x) for i,v in enumerate(gray))):
                matches.append([TITLE_REGION[0]+x, TITLE_REGION[1]+y, w, h])
    if len(matches) != 1:
        return False
    x,y,w,h = matches[0]
    if abs(x+w/2-old['center'][0]) > 4 or abs(y+h/2-old['center'][1]) > 4:
        return False
    row = deepcopy(old)
    row.update(text='Defense Minister', confidence=1, bounds=[x,y,w,h], center=[round(x+w/2),round(y+h/2)],
               x=x/640,y=y/480,width=w/640,height=h/480)
    row['provenance'] = deepcopy(old.get('provenance', [])) + [dict(
        preprocessing='original_gdi_promotion_title', text='Defense Minister', confidence=1,
        normalized_bounds=[x/640,y/480,w/640,h/480], source_template='PROMOTED', source_sha256=SOURCE_SHA256,
        atlas_id=REGULAR_ATLAS_ID, atlas_sha256=REGULAR_ATLAS_SHA256, metrics_sha256=REGULAR_METRICS_SHA256,
        region=list(TITLE_REGION), region_rgb_sha256=_sha(crop.tobytes()),
        comparison='complete black mask and all predicted gray134 pixels; calibrated grayscale palette',
        extra_black_pixels=0, missing_black_pixels=0, missing_predicted_gray_pixels=0)]
    proposed = deepcopy(rows); proposed[rows.index(old)] = row
    # The temporary RGB digest is only an internal preflight identity. The
    # ordinary pipeline keeps the original PNG hash and observed body bytes.
    result = classify_dialog(dict(width=640,height=480,sha256=_sha(image.convert('RGB').tobytes()),lines=proposed),
                             game_text=game_text)
    if (not result.get('supported') or result.get('resource_tag') != 'PROMOTED'
            or result.get('requires_model') or result.get('mechanical_action') != 'acknowledge_information'
            or [o['text'] for o in result.get('options', [])] != ['OK']):
        return False
    rows[:] = proposed
    if evidence is not None:
        evidence.setdefault('passes', []).append('original_gdi_promotion_title')
    return True
