"""Date-only city caption recovery from the optional original regular atlas.

Candidates use only the observed era and a single same-length digit change.
No city identity, native state, or expected campaign date enters this reader.
"""
from copy import deepcopy
import re
from zipfile import BadZipFile
from .dates import city_date_match, date_parts
from .gdi_text import (_sources, _sha, REGULAR_ATLAS_ID,
                       REGULAR_ATLAS_SHA256, REGULAR_METRICS_SHA256)
from .gdi_titles import _controls, _render, _maskrows, PALETTE

PREFIX_PALETTE = PALETTE | {97,105,113,121}


def _numbers(raw):
    values = {raw}
    for i in range(len(raw)):
        for digit in '0123456789':
            value = raw[:i] + digit + raw[i+1:]
            if value[0] != '0':
                values.add(value)
    return sorted(values)


def _pixels(image, x, y, rendered, right=0, palette=PALETTE):
    """Whole field mask, including blank vertical/right margins; no left clip.

    The preceding city word can touch the leading comma's left edge. That
    comma is part of the complete candidate, not an optional substring.
    """
    w,h,black,gray = rendered
    crop = image.crop((x,y-3,x+w+right,y+h+3))
    colors = crop.getcolors(crop.width*crop.height)
    if not colors or any(r != g or r != b or r not in palette for _,(r,g,b) in colors):
        return None
    channel = crop.getchannel('R')
    if _maskrows(channel.point(lambda v:255 if v == 0 else 0)) != [0]*3+black+[0]*3:
        return None
    actual_gray = _maskrows(channel.point(lambda v:255 if v == 134 else 0))
    if any((v & actual_gray[i+3]) != v for i,v in enumerate(gray)):
        return None
    return {'bounds':[x,y,w,h], 'region':[x,y-3,w+right,h+6],
            'region_rgb_sha256':_sha(crop.tobytes()),
            'palette':sorted(v[0] for _,v in colors)}


def _date_field(text, context=None):
    """Compose the preceding observed glyph's shadow before field extraction."""
    rendered=_render(text)
    if context is None:return rendered
    w,h,_,_=rendered
    cw,ch,black,gray=_render(context+text)
    if ch!=h or not 0<cw-w<=24:raise ValueError('Uncalibrated adjacent glyph geometry')
    shift=cw-w;mask=(1<<w)-1
    return w,h,[(v>>shift)&mask for v in black],[(v>>shift)&mask for v in gray]


def recover_caption_date(image, rows, executable=None, directory=None, evidence=None):
    """Change only the observed year digits after one unique complete match."""
    if image.size != (640,480) or (evidence or {}).get('conflicts') or _controls(rows) is None:
        return False
    headers = [(r,city_date_match(r['text'])) for r in rows
               if r.get('confidence',0) >= .8 and 100 <= r['bounds'][0] <= 125
               and 32 <= r['bounds'][1] <= 56 and 350 <= r['bounds'][2] <= 500
               and 8 <= r['bounds'][3] <= 24 and r['bounds'][0]+r['bounds'][2] <= 635]
    if len(headers) != 1 or headers[0][1] is None:
        return False
    old,match = headers[0]
    raw,era = date_parts(match[2])
    if not 1 <= len(raw) <= 5 or raw[0] == '0':
        return False
    # Require the actual native field's trailing punctuation in the OCR row.
    # The pixels independently require both commas, including the city separator.
    if not old['text'][match.end(2):].startswith(','):
        return False
    try:
        _,labels = _sources()
        if labels.splitlines().count('City of') != 1:
            return False
        prefix = _render('City of')
    except (OSError,ValueError,KeyError,BadZipFile):
        return False
    image = image.convert('RGB');x,y,w,h = old['bounds'];prefixes = []
    for px in range(max(100,x-6),min(130,x+6)+1):
        for py in range(max(35,y-4),min(56,y+4)+1):
            # The caption's left edge crosses the native window's grayscale
            # bevel; these four additional background grays are measured there.
            proof = _pixels(image,px,py,prefix,palette=PREFIX_PALETTE)
            if proof is not None:
                prefixes.append(proof)
    if len(prefixes) != 1:
        return False
    anchor = prefixes[0];px,py,pw,ph = anchor['bounds']
    # The measured native caption uses one regular-font baseline. Both the
    # prefix and complete date start at its top; unknown layouts abstain.
    left,right = px+pw+1,min(x+w,635)
    band = image.crop((left,py-3,right,py+25))
    black_rows = _maskrows(band.getchannel('R').point(lambda v:255 if v == 0 else 0))
    candidates = _numbers(raw);matches = [];used_context=None
    contexts=[None]
    if re.fullmatch('[A-Za-z]',match[1][-1:]):contexts.append(match[1][-1])
    for context in contexts:
        for number in candidates:
            text = f', A.D. {number},' if era == 'AD' else f', {number} B.C.,'
            try:
                rendered = _date_field(text,context)
            except ValueError:
                continue
            rw,rh,black,gray = rendered
            if not 1 <= rw <= 130 or not 1 <= rh <= 22:continue
            expected = [0]*3+black+[0]*3
            mask = (1 << (rw+3))-1
            for shift in range(band.width-rw-3+1):
                if any(((black_rows[i] >> shift) & mask) != value for i,value in enumerate(expected)):continue
                proof = _pixels(image,left+shift,py,rendered,right=3)
                if proof is not None:matches.append((number,proof,context))
    unique={}
    for number,proof,context in matches:
        key=(number,tuple(proof['bounds']),proof['region_rgb_sha256'])
        unique.setdefault(key,(number,proof,context))
    matches=list(unique.values())
    if len(matches) != 1 or matches[0][0] == raw:
        return False
    number,date_proof,used_context = matches[0]
    digits = re.search(r'[0-9]+',match[2])
    start,end = match.start(2)+digits.start(),match.start(2)+digits.end()
    row = deepcopy(old)
    row['text'] = old['text'][:start]+number+old['text'][end:]
    proof = dict(preprocessing='original_gdi_caption_date',text=row['text'],confidence=1,
                 raw_date=match[2],observed_era=era,previous_digits=raw,read_digits=number,
                 candidate_count=len(candidates),prefix=anchor,date=date_proof,
                 atlas_id=REGULAR_ATLAS_ID,atlas_sha256=REGULAR_ATLAS_SHA256,
                 metrics_sha256=REGULAR_METRICS_SHA256,
                 comparison='complete black date mask with both commas and blank margins; all predicted gray134 pixels; calibrated grayscale palette',
                 extra_black_pixels=0,missing_black_pixels=0,missing_predicted_gray_pixels=0,
                 scope='Date digits only. City name, era and remaining observed caption bytes unchanged.')
    if used_context is not None:
        proof['adjacent_observed_city_glyph']=used_context
        proof['adjacent_glyph_scope']='Compose the observed last city glyph before extracting the complete date field, preserving its shadow overlap at the leading comma. No date pixels are ignored; the city name is not decoded or changed.'
    row['provenance'] = deepcopy(old.get('provenance',[]))+[proof]
    row['caption_year_gdi'] = deepcopy(proof)
    if 'normal' in row:
        row['normal'] = row['text'].casefold().strip(' .:!?')
    rows[rows.index(old)] = row
    if evidence is not None:
        evidence.setdefault('passes',[]).append('original_gdi_caption_date')
    return True
