"""Original-game image observations; OCR is evidence, not a game-state oracle."""
from __future__ import annotations
import hashlib
from copy import deepcopy
from functools import lru_cache
import math
from pathlib import Path
import re
import subprocess
import tempfile
from PIL import Image
from .ocr_worker import run_ocr
from .gdi_text import recover_quoted_herald
from .gdi_bodies import recover_herald_paragraph
from .promotion_notice import recover_promotion_title
from .gdi_titles import annotate_production_titles,annotate_production_crop_anchor
from .gdi_dates import recover_caption_date
from .founding_frame import annotate_founding_frame
from .unit_economy import recover_disband_warning
from .gdi_treaty import recover_treaty_between
from .dates import DATE_PATTERN,city_date_match,date_parts
from .map_badges import annotate_badges
from .tax_controls import annotate_tax_controls
from .notice_icons import annotate_notice_icons
from .footer_pixels import annotate_footer

ROOT = Path(__file__).resolve().parents[1]
SHORT_CONTROLS = {text.casefold(): text for text in
                  ('OK', 'Cancel', 'Yes', 'No', 'Help', 'Close', 'Next', 'Back', 'Done', 'Continue')}
STATUS_CROP = (466, 440, 640, 480)
STATUS_PHRASES = ('End of Turn', '(Press ENTER)')


def _run_ocr(executable, path):
    return run_ocr(executable, path)


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
               for value in values) or any(not -limit <= value <= 1+1e-6
                   for value,limit in zip(values[:4],(1/width,1/height,1e-6,1e-6))) or not 0 <= values[4] <= 1:
            raise ValueError('Invalid normalized OCR geometry')
        # Vision can place a border-touching box slightly outside the image:
        # original012/128 has x=-0.105 source pixels. Intersect only a negative
        # origin within one source pixel; reject substantive/outward geometry.
        x, y, w, h = [min(1,max(0,value)) for value in values[:4]]
        if values[0]<0:w+=values[0]
        if values[1]<0:h+=values[1]
        confidence = values[4]
        if w <= 0 or h <= 0 or x + w > 1.001 or y + h > 1.001:
            raise ValueError('OCR geometry outside source image')
        row['bounds'] = [round(x * width), round(y * height), round(w * width), round(h * height)]
        row['center'] = [round((x + w / 2) * width), round((y + h / 2) * height)]
        row['provenance'] = [dict(preprocessing=preprocessing, text=row['text'], confidence=confidence,
                                  normalized_bounds=[x, y, w, h])]
        if values[0]<0 or values[1]<0:
            row['provenance'][0]['edge_clamp']={'raw_normalized_bounds':values[:4],
                                               'maximum_negative_origin_source_pixels':1}
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
                    previous['confidence'] = candidate['confidence']
                    previous['normalization'] = 'same-control ASCII OK corroboration'
                else:
                    previous['confidence'] = max(previous['confidence'], candidate['confidence'])
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
    limit = 3 if phrase == STATUS_PHRASES[0] else 4
    # The separately read pair is exact; this only identifies the overlapping
    # old row. A damaged first glyph (e.g. Bnd) must not discard actual pixels.
    return _near_text(compact, expected, limit)


def _recover_status(rows, raw, conflicts, *, crop=STATUS_CROP, name='status_white_4x', scale=4, threshold=240):
    """Recover the pair atomically from actual OCR of the white-glyph crop."""
    left,top,right,bottom=crop;cw,ch=right-left,bottom-top
    def in_crop(row):
        x,y,w,h=row['bounds']
        return x>=left and y>=top and x+w<=right+1 and y+h<=bottom+1
    local = _prepare_rows(raw, cw, ch, name)
    if len(local) != 2 or {row['text'].strip() for row in local} != set(STATUS_PHRASES):
        return
    candidates = []
    for phrase in STATUS_PHRASES:
        observed = next(row for row in local if row['text'].strip() == phrase)
        x, y, w, h = observed['provenance'][0]['normalized_bounds']
        mapped = dict(observed, x=(left + x * cw) / 640, y=(top + y * ch) / 480,
                      width=w * cw / 640, height=h * ch / 480)
        candidate = _prepare_rows([mapped], 640, 480, name)[0]
        candidate['provenance'][0].update(crop=list(crop), scale=scale,
                                          normalized_crop_bounds=[x, y, w, h],
                                          transform=f'RGB channels >={threshold} to black; others white; grayscale; bicubic')
        bx,by,bw,bh=candidate['bounds']
        if candidate['confidence'] < .8 or not (bx>=left and by>=top and bx+bw<=right+1 and by+bh<=bottom+1):
            return
        candidates.append(candidate)
    if (candidates[0]['center'][1] >= candidates[1]['center'][1]
            or _overlap(candidates[0], candidates[1])):
        return
    replacements = []
    for candidate, phrase in zip(candidates, STATUS_PHRASES):
        other_phrase=STATUS_PHRASES[1] if phrase==STATUS_PHRASES[0] else STATUS_PHRASES[0]
        def neighboring_line_edge(row):
            _,y,_,h=row['bounds'];_,cy,_,ch=candidate['bounds']
            return (in_crop(row) and _status_near_match(row['text'],other_phrase)
                    and min(y+h,cy+ch)-max(y,cy)<=2
                    and abs(row['center'][1]-candidate['center'][1])>=8)
        # Native12px text boxes can overlap their adjacent line by one pixel.
        # Exclude only that bounded edge of the separately corroborated pair.
        overlaps = [index for index, row in enumerate(rows)
                    if _overlap(row, candidate) and not neighboring_line_edge(row)]
        nearby = [index for index, row in enumerate(rows) if in_crop(row) and _status_near_match(row['text'], phrase)]
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


def _recover_expanded_status(image,rows,executable,directory,evidence):
    """Two independent white-glyph reads with four pixels of upper padding.

    Some original footer glyphs touch the old crop's first row. This is a
    bounded alternate framing, not a replacement inferred from a game turn.
    """
    if image.size!=(640,480) or not _status_recovery_needed(rows,640,480):return
    crop=(466,436,640,480);source=image.crop(crop).convert('RGB')
    pixels=list(source.getdata())
    if sum(min(p)>=230 for p in pixels)<40:return
    readings=[]
    for threshold in (230,240):
        name=f'status_padded_white{threshold}_3x';path=Path(directory)/(name+'.png')
        mask=Image.new('L',source.size)
        mask.putdata([0 if min(p)>=threshold else 255 for p in pixels])
        mask.resize((source.width*3,source.height*3),Image.Resampling.BICUBIC).save(path)
        evidence['passes'].append(name);raw=_run_ocr(executable,path)
        local=_prepare_rows(raw,source.width,source.height,name)
        if (len(local)!=2 or {r['text'].strip() for r in local}!=set(STATUS_PHRASES)
                or any(r['confidence']<.8 for r in local)):return
        readings.append((raw,local,name,threshold))
    a,b=readings
    if any(not _same_location(next(r for r in a[1] if r['text'].strip()==phrase),
                             next(r for r in b[1] if r['text'].strip()==phrase)) for phrase in STATUS_PHRASES):return
    for raw,_,name,threshold in readings:
        _recover_status(rows,raw,evidence['conflicts'],crop=crop,name=name,scale=3,threshold=threshold)


def _crop_text(image, row, name, executable, directory, evidence, *, white=False, padding=(6,3), grayscale=False, white_threshold=None, black_threshold=None, scale=None):
    """Read actual row pixels again; preserve source coordinates and provenance."""
    x,y,w,h=row['bounds']
    px,py=padding
    box=(max(0,x-px),max(0,y-py),min(image.width,x+w+px),min(image.height,y+h+py))
    crop=image.crop(box);scale=(4 if white else 3) if scale is None else scale
    if type(scale) is not int or scale not in (2,3,4):raise ValueError('Unsupported bounded OCR scale')
    if black_threshold is not None and (type(black_threshold) is not int or black_threshold!=70 or white or white_threshold is not None or grayscale):
        raise ValueError('Unsupported bounded black-glyph transform')
    if black_threshold is not None:crop=crop.convert('L').point(lambda value:0 if value<=black_threshold else 255)
    elif white:crop=crop.point(lambda v:0 if v>=230 else 255).convert('L')
    elif white_threshold is not None:
        rgb=crop.convert('RGB');crop=Image.new('L',rgb.size)
        crop.putdata([0 if min(pixel)>=white_threshold else 255 for pixel in rgb.getdata()])
    elif grayscale:crop=crop.convert('L')
    crop.resize((crop.width*scale,crop.height*scale),
        Image.Resampling.NEAREST if white else Image.Resampling.BICUBIC).save(Path(directory)/(name+'.png'))
    evidence['passes'].append(name)
    raw=_run_ocr(executable,Path(directory)/(name+'.png'))
    prepared=_prepare_rows(raw,box[2]-box[0],box[3]-box[1],name)
    result=[]
    for local in prepared:
        nx,ny,nw,nh=local['provenance'][0]['normalized_bounds']
        mapped={**local,'x':(box[0]+nx*(box[2]-box[0]))/image.width,
            'y':(box[1]+ny*(box[3]-box[1]))/image.height,
            'width':nw*(box[2]-box[0])/image.width,'height':nh*(box[3]-box[1])/image.height}
        candidate=_prepare_rows([mapped],image.width,image.height,name)[0]
        candidate['provenance'][0].update(crop=list(box),scale=scale,
            normalized_crop_bounds=[nx,ny,nw,nh],transform='RGB>=230 inverted to black; nearest' if white else
            (f'L<={black_threshold} to black; others white; bicubic enlargement' if black_threshold is not None else
             f'all RGB channels>={white_threshold} to black; bicubic enlargement' if white_threshold is not None else
             ('grayscale; bicubic enlargement' if grayscale else 'bicubic enlargement')))
        result.append(candidate)
    return result


def _replace_crop_row(rows, index, candidates, predicate):
    if len(candidates)!=1:return False
    old,new=rows[index],candidates[0]
    if new['confidence']<.8 or not _same_location(old,new) or not predicate(old['text'],new['text']):
        return False
    new['provenance']=old['provenance']+new['provenance']
    new['normalization']='independent OCR of same original row pixels'
    rows[index]=new
    return True


@lru_cache(maxsize=1)
def _research_names():
    """Original public advance labels; never derive names from game state."""
    try:
        from .boot import original_rules
        from .save import parse_rules
        return frozenset(r['name'].casefold() for r in parse_rules(original_rules()).get('advances',[])
                         if r.get('name'))
    except (OSError,ValueError,KeyError):
        return frozenset()


def _recover_research_rows(image,rows,executable,directory,evidence):
    """Re-read selected white research text only in a corroborated native list."""
    if image.size!=(640,480):return
    titles=[r for r in rows if re.fullmatch(r'wh(?:at|ait) discovery shall our wise men p(?:ur|or)sue[?!]?',r['text'],re.I)
            and r['confidence']>=.8 and 60<r['center'][1]<350]
    if len(titles)!=1:return
    title=titles[0];names=_research_names()
    buttons=[r for r in rows if r['text'].strip().casefold() in ('help','goal','ok') and r['center'][1]>title['center'][1]]
    if (not names or len(buttons)!=3 or {r['text'].strip().casefold() for r in buttons}!={'help','goal','ok'}
            or any(r['confidence']<.8 for r in buttons)
            or max(r['center'][1] for r in buttons)-min(r['center'][1] for r in buttons)>8):return
    bottom=min(r['center'][1] for r in buttons)
    body=[r for r in rows if title['center'][1]+8<r['center'][1]<bottom-8
          and abs(r['center'][0]-title['center'][0])<150]
    if sum(r['text'].casefold() in names and r['confidence']>=.8 for r in body)<2:return
    for index,row in enumerate(rows):
        if (row not in body or row['confidence']<.8 or row['text'].casefold() in names
                or not re.fullmatch(r'[A-Za-z ]{5,80}',row['text'])):continue
        x,y,w,h=row['bounds'];pixels=list(image.convert('RGB').crop((x,y,x+w,y+h)).getdata())
        if not pixels or sum(min(p)>=230 for p in pixels)/len(pixels)<.08:continue
        first=_crop_text(image,row,f'research_name_{index}_2x',executable,directory,evidence,padding=(3,3),scale=2)
        second=_crop_text(image,row,f'research_name_{index}_gray_2x',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
        if (len(first)==len(second)==1 and first[0]['text']==second[0]['text']
                and second[0]['confidence']>=.8 and _same_location(row,second[0])
                and _replace_crop_row(rows,index,first,lambda old,new:new.casefold() in names
                                      and _near_text(old.casefold(),new.casefold(),2))):
            rows[index]['provenance']+=second[0]['provenance']
            # The crop establishes the label, not a new target. Keep the
            # original independently observed row hit point and its geometry.
            for key in ('x','y','width','height','bounds','center'):
                rows[index][key]=row[key]


def _recover_exchange_advance_row(image,rows,executable,directory,evidence):
    """Read the selected TAKECIV label twice; no trade authority is inferred."""
    if image.size!=(640,480):return
    titles=[r for r in rows if re.fullmatch(r'Select [A-Za-z]{9,14} Advance',r['text'])
            and _near_text(r['text'].split()[1].casefold(),'civilization',3)
            and 378<=r['bounds'][0]<=398 and 144<=r['bounds'][1]<=149 and r['confidence']>=.8]
    buttons=[r for r in rows if r['text'] in ('OK','Goal','Help','Cancel','Yes','No')]
    if (len(titles)!=1 or len(buttons)!=2 or {r['text'] for r in buttons}!={'Goal','OK'}
            or any(r['confidence']<.8 or not 449<=r['center'][1]<=466 for r in buttons)):return
    if image.convert('RGB').crop((580,170,627,183)).getextrema()!=((105,105),)*3:return
    names=_research_names()
    selected=[r for r in rows if 309<=r['bounds'][0]<=316 and 168<=r['bounds'][1]<=173
              and 173<=r['center'][1]<=180 and r['bounds'][2]<=260 and r['confidence']>=.8]
    if len(selected)!=1 or not names:return
    old=selected[0]
    if old['text'].casefold() in names or not re.fullmatch('[A-Za-z ]{5,80}',old['text']):return
    readings=[]
    for scale,padding,threshold in ((3,(6,6),230),(2,(6,3),190)):
        a=_crop_text(image,old,f'exchange_advance_white{threshold}_{scale}x',executable,directory,evidence,
                     padding=padding,scale=scale,white_threshold=threshold)
        if (len(a)!=1 or a[0]['confidence']<.8
                or a[0]['text'].casefold() not in names or not _near_text(old['text'].casefold(),a[0]['text'].casefold(),2)
                or not _same_location(old,a[0])):return
        readings.append(a[0])
    if len({r['text'] for r in readings})!=1:return
    fresh=dict(readings[0]);fresh['provenance']=old['provenance']+[p for r in readings for p in r['provenance']]
    for key in ('x','y','width','height','bounds','center'):fresh[key]=old[key]
    rows[rows.index(old)]=fresh


@lru_cache(maxsize=1)
def _production_names():
    """Public original label vocabulary only; no save state or guessed words."""
    try:
        from .boot import original_rules
        from .save import parse_rules
        rules=parse_rules(original_rules())
        return frozenset(r['name'].casefold() for table in ('units','improvements')
                         for r in rules.get(table,[]) if r.get('name'))
    except (OSError,ValueError,KeyError):
        return frozenset()


def _stat_reading(text):
    # A native right column borders the scrollbar. OCR can append its vertical
    # stroke or one extra close-paren; retain these raw readings in provenance.
    # The observed defense * / OCR % suffix is opaque display text, never a
    # numeric value or an inferred ability. Do not drop it during re-reading.
    cleaned=text.strip().rstrip('|').strip()
    if cleaned.endswith('))'):cleaned=cleaned[:-1]
    return cleaned if re.fullmatch(r'\(\d+\s+(?:Turns?|Tums?)(?:,\s*ADM:\s*\d+/\d+[*%]?/\d+\s+HP:\s*\d+/\d+)?\),?',cleaned,re.I) else None


def _stat_numbers_compatible(old,new):
    previous,fresh=re.findall(r'\d+',old),re.findall(r'\d+',new)
    marker=re.search(r'ADM:\s*\d+/\d+([*%])/\d+',old,re.I)
    if marker and not re.search(r'ADM:\s*\d+/\d+[*%]/\d+',new,re.I):return False
    # Original008/382 reads the second ADM slash as 7: 0/171. Only
    # two agreeing actual crops can supply the replacement caller-side;
    # unchanged turn/HP values and one unique separator position are required.
    pattern=r'^\((\d+) (?:Turns?|Tums?), ADM: ([0-9/]+) HP: (\d+)/(\d+)\)$'
    a,b=re.fullmatch(pattern,old),re.fullmatch(pattern,new)
    if (a and b and (a[1],a[3],a[4])==(b[1],b[3],b[4])
            and a[2].count('/')==1 and b[2].count('/')==2
            and sum(c=='7' and a[2][:i]+'/'+a[2][i+1:]==b[2] for i,c in enumerate(a[2]))==1):
        return True
    return (previous==fresh or
            (len(fresh)==1 and '/' in old.split()[0]) or
            (len(previous)==len(fresh)==1 and not old.startswith('(') and previous[0]=='1'+fresh[0]))


def _recover_city_section_labels(image,rows,executable,directory,evidence):
    """Read native city headings from their pixels, never complete truncated text."""
    if image.size!=(640,480):return
    exact={r['text'].strip().casefold() for r in rows if r['confidence']>=.8}
    if not {'food storage','city resources','resource map','buy','change','exit'}<=exact:return
    for index,row in enumerate(rows):
        x,y,w,h=row['bounds']
        if not (260<=row['center'][1]<=310 and h<=24 and row['confidence']>=.8):continue
        expected='Units Supported' if 0<=x<200 else 'Units Present' if 200<=x<440 else None
        if expected is None or row['text'].casefold()==expected.casefold() or not _near_text(row['text'].casefold(),expected.casefold(),2):continue
        first=_crop_text(image,row,f'city_section_{index}_3x',executable,directory,evidence,padding=(3,3))
        second=_crop_text(image,row,f'city_section_{index}_gray_3x',executable,directory,evidence,padding=(3,3),grayscale=True)
        if (len(first)==len(second)==1 and first[0]['text']==second[0]['text']==expected
                and second[0]['confidence']>=.8 and _same_location(row,second[0])):
            if _replace_crop_row(rows,index,first,lambda old,new:new==expected):
                rows[index]['provenance']+=second[0]['provenance']


def _recover_name_city_title(image,rows,executable,directory,evidence):
    """Read the original default-name form's title; never supply its value."""
    if image.size!=(640,480):return
    expected='What Shall We Name This City?'
    controls=[r for r in rows if r['text'].strip().casefold() in ('ok','cancel','yes','no','help','goal','auto')]
    fields=[r for r in rows if r['text'].strip().casefold()=='city name:']
    if (len(controls)!=2 or {r['text'].casefold() for r in controls}!={'ok','cancel'}
            or len(fields)!=1 or abs(controls[0]['center'][1]-controls[1]['center'][1])>8):return
    for index,row in enumerate(rows):
        if (row['text']==expected or row['confidence']<.8 or not 100<=row['center'][1]<=350
                or not 280<=row['center'][0]<=360 or not _near_text(row['text'],expected,3)
                or not row['center'][1]<fields[0]['center'][1]<min(r['center'][1] for r in controls)):continue
        first=_crop_text(image,row,'name_city_title_3x',executable,directory,evidence,padding=(3,3))
        second=_crop_text(image,row,'name_city_title_gray_3x',executable,directory,evidence,padding=(3,3),grayscale=True)
        if (len(first)==len(second)==1 and first[0]['text']==second[0]['text']==expected
                and second[0]['confidence']>=.8 and _same_location(row,second[0])
                and _replace_crop_row(rows,index,first,lambda old,new:new==expected)):
            rows[index]['provenance']+=second[0]['provenance']


def _recover_governance_labels(image,rows,executable,directory,evidence):
    """Read damaged government headings/council prose from the same pixels."""
    if image.size!=(640,480):return
    if not any(r['text'].strip().casefold()=='ok' for r in rows):return
    for index,row in enumerate(rows):
        text=row['text'].strip()
        government=(80<=row['center'][1]<=350 and row['confidence']>=.8
                    and _near_text(text.casefold(),'select type of government',5))
        council=(row['confidence']>=.8 and text.startswith('The High Council of ')
                 and len(text)<120 and row['bounds'][2]<400)
        if not government and not council:continue
        if government and text=='Select Type of Government':continue
        if council and ' is meeting in' in text:continue
        first=_crop_text(image,row,f'governance_{index}_3x',executable,directory,evidence,padding=(6,6))
        second=_crop_text(image,row,f'governance_{index}_gray_3x',executable,directory,evidence,padding=(6,6),grayscale=True)
        if (len(first)!=1 or len(second)!=1 or first[0]['text']!=second[0]['text']
                or second[0]['confidence']<.8 or not _same_location(row,second[0])):continue
        new=first[0]['text']
        valid=(new=='Select Type of Government' if government else
               new.startswith('The High Council of ') and ' is meeting in' in new and _near_text(text,new,2))
        if valid and _replace_crop_row(rows,index,first,lambda old,new:True):
            rows[index]['provenance']+=second[0]['provenance']


def _recover_council_title(image,rows,executable,directory,evidence):
    """Read the complete council heading/date; both choices remain unchanged."""
    from .dates import DATE_PATTERN,date_parts
    if image.size!=(640,480):return
    # A radio marker may be absent from OCR. It remains only a crop locator;
    # no marker or choice text is removed or rewritten here.
    consult=[r for r in rows if r['text'] in ('O Consult High Council.','Consult High Council.') and r['confidence']>=.8]
    decline=[r for r in rows if re.fullmatch(r'(?:[•○●] )?No thanks, too busy\.',r['text']) and r['confidence']>=.8]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help')]
    if len(consult)!=1 or len(decline)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    if not any(r['text'].startswith('The High Council of ') and r['text'].endswith(' is meeting in') for r in rows):return
    if not any(r['text'] in ('on the state of your realm.','their views on the state of your realm.') for r in rows):return
    candidates=[]
    for index,old in enumerate(rows):
        match=re.fullmatch(rf'(.+?)\s+({DATE_PATTERN})',old['text'],re.I)
        if (match and date_parts(match[2]) and ':' not in match[1] and old['confidence']>=.8
                and 300<=old['center'][0]<=340 and 8<=old['center'][1]<=35
                and _near_text(match[1].casefold(),'the high council',6)):
            candidates.append((index,old,date_parts(match[2])))
    if len(candidates)!=1:return
    index,old,date=candidates[0]
    a=_crop_text(image,old,'council_title_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
    b=_crop_text(image,old,'council_title_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(old,b[0]) or not _same_location(a[0],b[0])):return
    matched=re.fullmatch(rf'(.+?)(?::\s*|\s+)({DATE_PATTERN})',a[0]['text'],re.I)
    if (not matched or date_parts(matched[2])!=date
            or not _near_text(matched[1].casefold(),'the high council',4)):return
    if _replace_crop_row(rows,index,a,lambda raw,fresh:True):
        rows[index]['provenance']+=b[0]['provenance']
        rows[index]['council_title_recovery']={'source_image_sha256':evidence.get('source_image_sha256'),
            'date_parts':list(date),'scope':'Complete paired title reads only; full original council body and both choices still required.'}


def _recover_tax_context(image,rows,executable,directory,evidence):
    if image.size!=(640,480):return
    # Vision can split a single row at the colon (original 50% tax display).
    # Join only the two actual, adjacent high-confidence readings; retain both
    # original row provenances and never manufacture a numeric value.
    for label in list(rows):
        if (label['text'] not in ('Taxes:','Science:','Luxuries:') or label['confidence']<.8
                or not 220<=label['bounds'][0]<=300 or not 220<=label['center'][1]<=330):continue
        x,y,w,h=label['bounds']
        values=[r for r in rows if r is not label and r['confidence']>=.8
                and re.fullmatch(r'(?:100|[0-9]{1,2})%',r['text'])
                and -3<=r['bounds'][0]-(x+w)<=12 and abs(r['center'][1]-label['center'][1])<=3]
        if len(values)!=1:continue
        value=values[0];vx,vy,vw,vh=value['bounds'];top=min(y,vy);bottom=max(y+h,vy+vh)
        if bottom-top>22:continue
        joined=dict(label,text=label['text']+' '+value['text'],bounds=[x,top,vx+vw-x,bottom-top],
                    center=[round((x+vx+vw)/2),round((top+bottom)/2)],
                    confidence=min(label['confidence'],value['confidence']),
                    provenance=label['provenance']+value['provenance'],
                    tax_label_parts=[{'text':r['text'],'bounds':r['bounds']} for r in (label,value)])
        rows[rows.index(label)]=joined;rows.remove(value)
    if not all(any(re.fullmatch(name+r':\s*\d{1,3}%',r['text']) for r in rows)
               for name in ('Taxes','Science','Luxuries')):return
    # The ornamental original title is a separate crop; rates are never
    # changed to match it. Actual paired reads, not a title alias, must restore
    # the sentence structure used by the source-bound dialog classifier.
    title_text='How Shall We Distribute The Wealth'
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help')]
    if len(controls)==1 and controls[0]['text'].casefold()=='ok':
        for index,row in enumerate(rows):
            if (not 90<=row['center'][1]<=125 or not 280<=row['center'][0]<=350
                    or row['confidence']<.8 or not _near_text(row['text'].casefold(),title_text.casefold(),8)
                    or _near_text(row['text'].casefold(),title_text.casefold(),4)):continue
            first=_crop_text(image,row,'tax_title_rgb3',executable,directory,evidence,padding=(3,3))
            second=_crop_text(image,row,'tax_title_gray3',executable,directory,evidence,padding=(3,3),grayscale=True)
            if (len(first)!=1 or len(second)!=1 or first[0]['text']!=second[0]['text']
                    or min(first[0]['confidence'],second[0]['confidence'])<.8
                    or not _same_location(row,second[0]) or not _same_location(first[0],second[0])):continue
            match=re.fullmatch(r'How Shall We ([A-Za-z]+) The Wealth',first[0]['text'])
            if match and _near_text(match[1].casefold(),'distribute',2):
                if _replace_crop_row(rows,index,first,lambda old,new:True):
                    rows[index]['provenance']+=second[0]['provenance']
    for index,row in enumerate(rows):
        text=row['text']
        if not (110<=row['center'][1]<=165 and row['confidence']>=.8
                and 'Maximum Rate:' in text and '%' in text):continue
        first=_crop_text(image,row,'tax_government_3x',executable,directory,evidence,padding=(6,6))
        second=_crop_text(image,row,'tax_government_gray_3x',executable,directory,evidence,padding=(6,6),grayscale=True)
        if (len(first)!=1 or len(second)!=1 or first[0]['text']!=second[0]['text']
                or second[0]['confidence']<.8 or not _same_location(row,second[0])):continue
        if not re.fullmatch(r'Government: (?:Anarchy|Despotism|Monarchy|Communism|Fundamentalism|Republic|Democracy) Maximum Rate: \d{1,3}%',first[0]['text']):continue
        if _replace_crop_row(rows,index,first,lambda old,new:_near_text(old,new,3)):
            rows[index]['provenance']+=second[0]['provenance']


def _recover_locator_names(image,rows,executable,directory,evidence):
    if image.size!=(640,480):return
    if not any(re.match(r'Where in the (?:heck|beck) is',r['text']) for r in rows):return
    controls={r['text'].casefold() for r in rows if r['center'][1]>370}
    if not {'zoom to city','ok','cancel'}<=controls:return
    for index,row in enumerate(rows):
        if (not 135<=row['bounds'][0]<=160 or not 100<=row['bounds'][1]<=350
                or row['confidence']<.8 or not re.fullmatch('[A-Za-z ]{3,40}',row['text'])):continue
        first=_crop_text(image,row,f'locator_name_{index}_3x',executable,directory,evidence,padding=(3,3))
        second=_crop_text(image,row,f'locator_name_{index}_gray_3x',executable,directory,evidence,padding=(3,3),grayscale=True)
        if (len(first)!=1 or len(second)!=1 or first[0]['text']!=second[0]['text']
                or second[0]['confidence']<.8 or not _same_location(row,second[0])
                or not re.fullmatch('[A-Za-z ]{3,40}',first[0]['text'])):continue
        if first[0]['text']!=row['text'] and _replace_crop_row(rows,index,first,lambda old,new:_near_text(old,new,1)):
            rows[index]['provenance']+=second[0]['provenance']


def _recover_domestic_title(image,rows,executable,directory,evidence):
    if image.size!=(640,480):return
    if not any(r['text'].casefold()=='ok' for r in rows):return
    for index,row in enumerate(rows):
        if (not 100<=row['center'][1]<=320 or not 260<=row['center'][0]<=380
                or row['confidence']<.8 or row['text']=='Domestic Advisor'
                or not _near_text(row['text'].casefold(),'domestic advisor',2)):continue
        first=_crop_text(image,row,'domestic_title_3x',executable,directory,evidence,padding=(3,3))
        second=_crop_text(image,row,'domestic_title_gray_3x',executable,directory,evidence,padding=(3,3),grayscale=True)
        if (len(first)!=1 or len(second)!=1 or first[0]['text']!=second[0]['text']
                or second[0]['confidence']<.8 or not _same_location(row,second[0])):continue
        if first[0]['text']=='Domestic Advisor' and _replace_crop_row(rows,index,first,lambda old,new:True):
            rows[index]['provenance']+=second[0]['provenance']


def _recover_stolen_advance_notice(image,rows,executable,directory,evidence):
    """Read the complete stolen-advance heading and its terminal punctuation."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['confidence']>=.8 and 180<=r['center'][1]<=240
            and 300<=r['center'][0]<=340 and _near_text(r['text'].casefold(),'civilization advance stolen!',5)]
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','continue')]
    if len(titles)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    title,ok=titles[0],controls[0]
    if abs(title['center'][0]-ok['center'][0])>8 or not 40<=ok['center'][1]-title['center'][1]<=80:return
    bodies=[r for r in rows if 176<=r['bounds'][0]<=190 and title['center'][1]<r['center'][1]<ok['center'][1]
            and r['confidence']>=.8 and re.fullmatch(r'[A-Za-z -]{2,60} take [A-Za-z ]{2,60}[l!]',r['text'])]
    if len(bodies)!=1:return
    body=bodies[0];wanted=body['text'][:-1]+'!';new=[]
    for old,name in ((title,'title'),(body,'body')):
        a=_crop_text(image,old,'stolen_advance_'+name+'_rgb3',executable,directory,evidence,padding=(3,3))
        b=_crop_text(image,old,'stolen_advance_'+name+'_gray3',executable,directory,evidence,padding=(3,3),grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        if name=='title' and a[0]['text'] not in ('Civilization Advance Stolen!','Cialization Advance Stolen!'):return
        if name=='body' and a[0]['text']!=wanted:return
        new.append((old,a[0],b[0]))
    for old,a,b in new:
        a['provenance']=old['provenance']+a['provenance']+b['provenance']
        rows[rows.index(old)]=a


def _recover_capture_notice_title(image,rows,executable,directory,evidence):
    """Read the complete capture title/prose while preserving names and amounts."""
    if image.size!=(640,480):return
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','continue')]
    titles=[r for r in rows if r['confidence']>=.8 and 100<=r['center'][1]<=160
            and 300<=r['center'][0]<=340 and _near_text(r['text'].casefold(),'defense minister',6)]
    if len(controls)!=1 or controls[0]['text']!='OK' or len(titles)!=1:return
    old=titles[0];ok=controls[0]
    if abs(old['center'][0]-ok['center'][0])>8:return
    body=sorted([r for r in rows if 296<=r['bounds'][0]<=320
                 and old['center'][1]<r['center'][1]<ok['center'][1]-12],key=lambda r:r['center'][1])
    if len(body)!=2 or any(r['confidence']<.8 for r in body):return
    match=re.fullmatch(r'([A-Za-z -]{2,60} (?:capture|liberate|captured|liberated) [A-Za-z -]{2,60})[.,] ([0-9]{1,6} gold pieces)',body[0]['text'])
    if not match or body[1]['text'] not in ('plundered.','Splundered.'):return
    tasks=[]
    if old['text'] not in ('Defense Minister','Defense Mfinister'):
        tasks.append((old,'title',4,('Defense Minister','Defense Mfinister')))
    for row,name,wanted in ((body[0],'body',match[1]+'. '+match[2]),(body[1],'tail','plundered.')):
        if row['text']!=wanted:tasks.append((row,name,3,(wanted,)))
    recovered=[]
    for row,name,scale,wanted in tasks:
        a=_crop_text(image,row,f'capture_{name}_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
        b=_crop_text(image,row,f'capture_{name}_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or a[0]['text'] not in wanted
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(row,a[0]) or not _same_location(a[0],b[0])):return
        recovered.append((row,a[0],b[0]))
    for row,a,b in recovered:
        a['provenance']=row['provenance']+a['provenance']+b['provenance']
        rows[rows.index(row)]=a


def _recover_civil_war_notice(image,rows,executable,directory,evidence):
    """Read the measured three-line civil-war notice without guessing nations."""
    if image.size!=(640,480):return
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','continue')]
    titles=[r for r in rows if r['confidence']>=.8 and 185<=r['center'][1]<=201
            and 300<=r['center'][0]<=340 and _near_text(r['text'].casefold(),'defense minister',4)]
    if len(controls)!=1 or controls[0]['text']!='OK' or len(titles)!=1:return
    title=titles[0];ok=controls[0]
    if not 278<=ok['center'][1]<=296 or abs(title['center'][0]-ok['center'][0])>8:return
    body=sorted([r for r in rows if 116<=r['bounds'][0]<=124
                 and title['center'][1]+10<r['center'][1]<ok['center'][1]-12],key=lambda r:r['center'][1])
    if (len(body)!=3 or any(r['confidence']<.8 for r in body)
            or any(not 16<=b['center'][1]-a['center'][1]<=25 for a,b in zip(body,body[1:]))):return
    nation=re.fullmatch(r'The ([A-Za-z -]{2,40}) empire is swept by Civil War triggered by the fall',body[0]['text'])
    if (not nation
            or body[1]['text']!='of their capital! When the dust settles the empire has been'):return
    pattern=r'split into loyal \(([A-Za-z -]{2,40})\) and rebel \(([A-Za-z -]{2,40})\) factions\.'
    tail=re.fullmatch(pattern,body[2]['text'])
    if not tail or (title['text']=='Defense Minister' and tail[1]==nation[1]):return
    recovered=[]
    for row,name,scale in ((title,'title',3),(body[2],'tail',2)):
        a=_crop_text(image,row,f'civil_war_{name}_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
        b=_crop_text(image,row,f'civil_war_{name}_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(row,a[0]) or not _same_location(a[0],b[0])):return
        if name=='title':
            if a[0]['text'] not in ('Defense Minister','Defense Bfinister'):return
        else:
            fresh=re.fullmatch(pattern,a[0]['text'])
            if (not fresh or fresh[1]!=nation[1] or fresh[2]!=tail[2]
                    or not _near_text(fresh[1],tail[1],1)):return
        recovered.append((row,a[0],b[0]))
    for row,a,b in recovered:
        a['provenance']=row['provenance']+a['provenance']+b['provenance']
        rows[rows.index(row)]=a


def _recover_foreign_completion_title(image,rows,executable,directory,evidence):
    """Read Foreign Advisor only above complete observed completion prose."""
    if image.size!=(640,480):return
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','continue')]
    pattern=r'(.{1,60}) \(([^()]{1,40})\) (builds|completes) (.{1,60}?)(\.)?'
    bodies=[r for r in rows if re.fullmatch(pattern,r['text'])
            and r['confidence']>=.8]
    if len(controls)!=1 or controls[0]['text']!='OK' or len(bodies)!=1:return
    titles=[(i,r) for i,r in enumerate(rows) if r['confidence']>=.8
            and _near_text(r['text'].casefold(),'foreign advisor',2)
            and abs(r['center'][0]-controls[0]['center'][0])<=8
            and 12<=bodies[0]['center'][1]-r['center'][1]<=40
            and bodies[0]['center'][1]<controls[0]['center'][1]]
    if len(titles)!=1:return
    index,old=titles[0]
    body=bodies[0];match=re.fullmatch(pattern,body['text']);body_reads=[]
    if match[5] is None:
        for scale in (3,2):
            a=_crop_text(image,body,f'foreign_completion_body_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
            b=_crop_text(image,body,f'foreign_completion_body_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
            if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                    or min(a[0]['confidence'],b[0]['confidence'])<.8
                    or not _same_location(body,a[0]) or not _same_location(a[0],b[0])):return
            fresh=re.fullmatch(pattern,a[0]['text'])
            if (not fresh or fresh[5]!='.' or any(fresh[n]!=match[n] for n in (1,3,4))
                    or not _near_text(match[2],fresh[2],1)):return
            body_reads.extend((a[0],b[0]))
        if len({r['text'] for r in body_reads})!=1:return
    if old['text']=='Foreign Advisor':
        if body_reads:
            fresh=body_reads[0];fresh['provenance']=[p for r in body_reads for p in r['provenance']]
            _replace_crop_row(rows,rows.index(body),[fresh],lambda before,after:True)
        return
    a=_crop_text(image,old,'foreign_completion_title_rgb3',executable,directory,evidence,padding=(3,3))
    b=_crop_text(image,old,'foreign_completion_title_gray3',executable,directory,evidence,padding=(3,3),grayscale=True)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or a[0]['text']!='Foreign Advisor'
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(old,b[0]) or not _same_location(a[0],b[0])):return
    if _replace_crop_row(rows,index,a,lambda before,after:True):rows[index]['provenance']+=b[0]['provenance']
    if body_reads:
        fresh=body_reads[0];fresh['provenance']=[p for r in body_reads for p in r['provenance']]
        _replace_crop_row(rows,rows.index(body),[fresh],lambda before,after:True)


def _recover_saved_caption(image,rows,executable,directory,evidence):
    """Read the original save acknowledgement's heading; never acknowledge it."""
    if image.size!=(640,480):return
    if (not any('of the romans' in r['text'].casefold() for r in rows)
            or len([r for r in rows if r['text'].strip().casefold()=='ok'])!=1):return
    for index,row in enumerate(rows):
        old=row['text'].casefold().strip(' .!')
        if (not 170<=row['center'][1]<=240 or not 260<=row['center'][0]<=380
                or not _near_text(old,'game saved',2) or old.startswith('game sa')):continue
        for padding in ((3,3),(2,2),(6,6)):
            try:
                first=_crop_text(image,row,f'saved_caption_{padding[0]}_3x',executable,directory,evidence,padding=padding)
                second=_crop_text(image,row,f'saved_caption_gray_{padding[0]}_3x',executable,directory,evidence,padding=padding,grayscale=True)
            except ValueError:continue
            if len(first)!=1 or len(second)!=1 or first[0]['text']!=second[0]['text']:continue
            fresh=first[0]['text'].casefold().strip(' .!')
            if (fresh.startswith('game sa') and _near_text(fresh,'game saved',2)
                    and second[0]['confidence']>=.8 and _same_location(row,second[0])):
                if _replace_crop_row(rows,index,first,lambda old,new:True):
                    rows[index]['provenance']+=second[0]['provenance']
                    break


def _recover_revolt_notice_title(image,rows,executable,directory,evidence):
    """Recover the post-revolution acknowledgement title, never a Yes choice."""
    if image.size!=(640,480):return
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help')]
    if len(controls)!=1 or controls[0]['text']!='OK':return
    a=[r for r in rows if re.fullmatch(r'The .+ are revolting! Citizens',r['text']) and r['confidence']>=.8]
    b=[r for r in rows if r['text']=='demand new government.' and r['confidence']>=.8]
    if len(a)!=1 or len(b)!=1 or not 12<=b[0]['center'][1]-a[0]['center'][1]<=28:return
    headings=[(i,r) for i,r in enumerate(rows) if r['confidence']>=.8
              and re.fullmatch('[A-Za-z]{5,16}!',r['text'])
              and 16<=a[0]['center'][1]-r['center'][1]<=40
              and abs(r['center'][0]-controls[0]['center'][0])<=8]
    if len(headings)!=1 or headings[0][1]['text']=='Revolution!':return
    index,title=headings[0]
    rgb=_crop_text(image,title,'revolt_notice_rgb3',executable,directory,evidence,padding=(3,3))
    gray=_crop_text(image,title,'revolt_notice_gray3',executable,directory,evidence,padding=(3,3),grayscale=True)
    if (len(rgb)==len(gray)==1 and rgb[0]['text']==gray[0]['text']=='Revolution!'
            and min(rgb[0]['confidence'],gray[0]['confidence'])>=.8
            and _same_location(title,gray[0]) and _same_location(rgb[0],gray[0])):
        if _replace_crop_row(rows,index,rgb,lambda old,new:True):rows[index]['provenance']+=gray[0]['provenance']


def _recover_revolution_title(image,rows,executable,directory,evidence):
    """Read the original title from two crops after its complete form is seen."""
    if image.size!=(640,480):return
    first=[r for r in rows if r['text'].strip().casefold()=='do we want a revolution to']
    second=[r for r in rows if re.fullmatch(r'overthrow the [a-z ]+\?',r['text'].strip(),re.I)]
    yesno=[r for r in rows if re.fullmatch(r'(?:[O0•○●]\s+)?(?:Yes|No)',r['text'].strip(),re.I)]
    okay=[r for r in rows if r['text'].strip()=='OK']
    if len(first)!=1 or len(second)!=1 or len(yesno)!=2 or len(okay)!=1:return
    if {re.sub(r'^[O0•○●]\s+','',r['text'].strip()).casefold() for r in yesno}!={'yes','no'}:return
    a,b=first[0],second[0];ok=okay[0]
    if (not 12<=b['center'][1]-a['center'][1]<=28
            or any(r['confidence']<.8 or not b['center'][1]<r['center'][1]<ok['center'][1] for r in yesno)
            or any(r['confidence']<.8 for r in (a,b,ok))):return
    headings=[(i,r) for i,r in enumerate(rows) if re.fullmatch('[A-Za-z]{5,16}',r['text'])
              and 16<=a['center'][1]-r['center'][1]<=40
              and abs(r['center'][0]-ok['center'][0])<=8]
    if len(headings)!=1 or headings[0][1]['text']=='Revolution':return
    index,title=headings[0]
    rgb=_crop_text(image,title,'revolution_title_3x',executable,directory,evidence)
    gray=_crop_text(image,title,'revolution_title_gray_3x',executable,directory,evidence,grayscale=True)
    if (len(rgb)!=1 or len(gray)!=1 or rgb[0]['text']!=gray[0]['text']
            or not _near_text(rgb[0]['text'].casefold(),'revolution',2)
            or gray[0]['confidence']<.8 or not _same_location(title,gray[0])):return
    if _replace_crop_row(rows,index,rgb,lambda old,new:True):
        rows[index]['provenance']+=gray[0]['provenance']


def _recover_exchange_body(image,rows,executable,directory,evidence):
    """Two independent pixel reads of an observed herald trade's prose.

    Options are not synthesized or changed here. The source classifier must
    subsequently match the complete GAME body and each visible alternative.
    """
    if image.size!=(640,480):return
    titles=[r for r in rows if 200<=r['bounds'][1]<=350 and 457<=r['center'][0]<=481
            and r['confidence']>=.8 and r['text'].casefold().endswith(' emissary')]
    options=[r for r in rows if 330<=r['bounds'][0]<=350
             and r['text'].casefold().startswith(('"no. we do not need','"okay, let','"will you accept'))]
    if len(titles)!=1 or len(options) not in (2,3):return
    title=titles[0];first_option=min(r['bounds'][1] for r in options)
    body=[r for r in rows if r['bounds'][0]>=300 and title['center'][1]<r['center'][1]
          and r['bounds'][1]+r['bounds'][3]<=first_option]
    body.sort(key=lambda r:r['center'][1])
    if (not 3<=len(body)<=6 or not body[0]['text'].casefold().startswith('"we note that your primitive civilization')
            or not ' '.join(r['text'] for r in body).casefold().endswith('exchange knowledge with us?"')):return
    box=(max(0,min(r['bounds'][0] for r in body)-6),max(0,body[0]['bounds'][1]-4),
         min(640,max(r['bounds'][0]+r['bounds'][2] for r in body)+8),
         min(first_option,body[-1]['bounds'][1]+body[-1]['bounds'][3]+6))
    readings=[]
    for gray in (False,True):
        name='exchange_body_gray_3x' if gray else 'exchange_body_3x'
        crop=image.crop(box)
        if gray:crop=crop.convert('L')
        target=Path(directory)/(name+'.png')
        crop.resize((crop.width*3,crop.height*3),Image.Resampling.BICUBIC).save(target)
        evidence['passes'].append(name)
        raw=_prepare_rows(_run_ocr(executable,target),crop.width,crop.height,name)
        mapped=[]
        for local in raw:
            x,y,w,h=local['provenance'][0]['normalized_bounds']
            row=_prepare_rows([dict(text=local['text'],confidence=local['confidence'],
                x=(box[0]+x*crop.width)/640,y=(box[1]+y*crop.height)/480,
                width=w*crop.width/640,height=h*crop.height/480)],640,480,name)[0]
            row['provenance'][0].update(crop=list(box),scale=3,normalized_crop_bounds=[x,y,w,h],
                transform=('grayscale; ' if gray else '')+'bicubic enlargement')
            mapped.append(row)
        readings.append(sorted(mapped,key=lambda r:r['center'][1]))
    first,second=readings
    if len(first)!=len(second) or len(first)!=len(body):return
    if any(a['text']!=b['text'] or min(a['confidence'],b['confidence'])<.8
           or not _same_location(a,b) or not _same_location(old,a)
           for old,a,b in zip(body,first,second)):return
    for old,a,b in zip(body,first,second):
        a['provenance']=old['provenance']+a['provenance']+b['provenance']
        rows[rows.index(old)]=a


def _recover_exchange_requested_advance(image,rows,executable,directory,evidence):
    """Read one damaged advance name in a complete observed exchange proposal."""
    if image.size!=(640,480):return
    titles=[r for r in rows if 200<=r['bounds'][1]<=350 and 457<=r['center'][0]<=481
            and r['confidence']>=.8 and r['text'].endswith(' Emissary')]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help')]
    options=[r for r in rows if 330<=r['bounds'][0]<=350 and r['confidence']>=.8
             and (re.fullmatch(r'"No\. We do not need [A-Za-z ]{2,60}\."',r['text'])
                  or r['text']=='"Okay, let\'s exchange knowledge."'
                  or re.fullmatch(r'"Will you accept [A-Za-z ]{2,60} instead\?"',r['text']))]
    if len(titles)!=1 or len(controls)!=1 or controls[0]['text']!='OK' or len(options) not in (2,3):return
    title=titles[0];bottom=min(r['bounds'][1] for r in options)
    body=sorted([r for r in rows if 304<=r['bounds'][0]<=315
                 and title['center'][1]<r['center'][1] and r['bounds'][1]+r['bounds'][3]<=bottom],key=lambda r:r['center'][1])
    if (not 3<=len(body)<=6 or any(r['confidence']<.8 for r in body)
            or not body[0]['text'].startswith('"We note that your primitive civilization')
            or body[-1]['text']!='exchange knowledge with us?"'):return
    pattern=r'secret of ([A-Za-z ]{2,60})[.,] Do you care to'
    candidates=[(r,re.fullmatch(pattern,r['text']))for r in body]
    candidates=[(r,m)for r,m in candidates if m]
    if len(candidates)!=1:return
    old,match=candidates[0];names=_research_names()
    if match[1].casefold() in names and old['text']==f'secret of {match[1]}. Do you care to':return
    if sum(_near_text(match[1].casefold(),name,1)for name in names)!=1:return
    a=_crop_text(image,old,'exchange_requested_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
    b=_crop_text(image,old,'exchange_requested_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
    fresh=re.fullmatch(r'secret of ([A-Za-z ]{2,60})\. Do you care to',a[0]['text'])
    if not fresh or fresh[1].casefold() not in names or not _near_text(match[1].casefold(),fresh[1].casefold(),1):return
    a[0]['provenance']=old['provenance']+a[0]['provenance']+b[0]['provenance']
    rows[rows.index(old)]=a[0]


def _recover_cancel_treaty_body(image,rows,executable,directory,evidence):
    """Read source words/punctuation while retaining the treaty choice and target."""
    if image.size!=(640,480):return
    titles=[r for r in rows if 200<=r['bounds'][1]<=380 and 450<=r['center'][0]<=485
            and r['confidence']>=.8 and r['text'].endswith(' Emissary')]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help')]
    no=[r for r in rows if re.fullmatch(r'"Never! The [A-Za-z ]{2,40} are our friends\."',r['text'])]
    yes=[r for r in rows if re.fullmatch(r'"Yes! Let us teach the [A-Za-z ]{2,40} a lesson!"',r['text'])]
    if len(titles)!=1 or len(controls)!=1 or controls[0]['text']!='OK' or len(no)!=1 or len(yes)!=1:return
    title=titles[0];bottom=min(no[0]['bounds'][1],yes[0]['bounds'][1])
    body=sorted([r for r in rows if 300<=r['bounds'][0]<=315
                 and title['center'][1]<r['center'][1] and r['bounds'][1]+r['bounds'][3]<=bottom],key=lambda r:r['center'][1])
    if len(body)!=3 or any(r['confidence']<.8 for r in [*body,*no,*yes,*controls]):return
    middle=re.fullmatch(r'the ([A-Za-z ]{2,40})\. We [A-Za-z]{2,16} you cancel this treaty',body[1]['text'])
    first='"You have made peace with our evil neighbors:';last='at once!"'
    if (not middle or no[0]['text']!=f'"Never! The {middle[1]} are our friends."'
            or yes[0]['text']!=f'"Yes! Let us teach the {middle[1]} a lesson!"'
            or not body[0]['text'].startswith('"You have made peace with our evil ')
            or not _near_text(body[0]['text'],first,1)
            or not body[2]['text'].startswith('at once') or not _near_text(body[2]['text'],last,2)):return
    recovered=[]
    for old,wanted,name in ((body[0],first,'intro'),(body[2],last,'tail')):
        if old['text']==wanted:continue
        if name=='intro':
            a=_crop_text(image,old,'cancel_treaty_intro_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
            b=_crop_text(image,old,'cancel_treaty_intro_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
        else:
            a=_crop_text(image,old,'cancel_treaty_tail_black2',executable,directory,evidence,padding=(3,3),scale=2,black_threshold=70)
            b=_crop_text(image,old,'cancel_treaty_tail_black3',executable,directory,evidence,padding=(3,3),scale=3,black_threshold=70)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=wanted or b[0]['text']!=wanted
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        recovered.append((old,a[0],b[0]))
    for old,a,b in recovered:
        a['provenance']=old['provenance']+a['provenance']+b['provenance']
        rows[rows.index(old)]=a


def _recover_tribute_tail(image,rows,executable,directory,evidence):
    """Read TRIBUTE1's punctuation/radio label, never its amount or answer."""
    if image.size!=(640,480):return
    titles=[r for r in rows if 200<=r['bounds'][1]<=380 and 450<=r['center'][0]<=485
            and r['confidence']>=.8 and r['text'].endswith(' Emissary')]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help')]
    no=[r for r in rows if r['text']=='"We laugh at your petty boasts."']
    pay=[(r,re.fullmatch(r'(?:[O○●•] )?Pay ([0-9]{1,6}) gold in tribute\.',r['text']))for r in rows]
    pay=[(r,m)for r,m in pay if m]
    if len(titles)!=1 or len(controls)!=1 or controls[0]['text']!='OK' or len(no)!=1 or len(pay)!=1:return
    title=titles[0];payment,amount=pay[0];bottom=min(no[0]['bounds'][1],payment['bounds'][1])
    body=sorted([r for r in rows if 304<=r['bounds'][0]<=315
                 and title['center'][1]<r['center'][1] and r['bounds'][1]+r['bounds'][3]<=bottom],key=lambda r:r['center'][1])
    if (len(body)!=4 or any(r['confidence']<.8 for r in [*body,*no,payment,*controls])
            or body[0]['text']!='"Your pathetic civilization is hardly worth'
            or body[1]['text']!='conquering. We might forego this pleasure for'
            or body[2]['text']!=f'the time being in exchange for {amount[1]} gold in'
            or body[3]['text'] not in ('tribute"','tribute."')):return
    recovered=[]
    for old,wanted,name in ((body[3],'tribute."','tail'),(payment,f'Pay {amount[1]} gold in tribute.','payment')):
        if old['text']==wanted:continue
        a=_crop_text(image,old,f'tribute_{name}_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
        b=_crop_text(image,old,f'tribute_{name}_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=wanted or b[0]['text']!=wanted
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        recovered.append((old,a[0],b[0]))
    for old,a,b in recovered:
        a['provenance']=old['provenance']+a['provenance']+b['provenance']
        rows[rows.index(old)]=a


def _recover_government_offer(image,rows,executable,directory,evidence):
    """Recover the actual AUTOREV prose and two radio choices, not answers."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['confidence']>=.8 and 100<=r['center'][1]<=220
            and _near_text(r['text'].casefold(),'civ rules: governments',4)]
    choices=[r for r in rows if r['confidence']>=.8 and 180<=r['bounds'][0]<=230
             and 240<=r['center'][1]<=350
             and (re.match(r'^[•○●o)]*\s*No,',r['text']) or 'Begin revolution.' in r['text'])]
    if len(titles)!=1 or len(choices)!=2:return
    body=[r for r in rows if 170<=r['bounds'][0]<300 and titles[0]['center'][1]<r['center'][1]<min(c['bounds'][1] for c in choices)]
    body.sort(key=lambda r:r['center'][1]);choices.sort(key=lambda r:r['center'][1])
    if not 3<=len(body)<=7 or not body[0]['text'].startswith('You have just acquired knowledge'):return
    left=sorted(r['bounds'][0] for r in body)[len(body)//2]-2
    right=max(r['bounds'][0]+r['bounds'][2] for r in body)+6
    groups=[(body,(left,body[0]['bounds'][1]-4,right,min(c['bounds'][1] for c in choices)-4),'body'),
            (choices,(min(c['bounds'][0] for c in choices)-6,choices[0]['bounds'][1]-5,right+1,
                      choices[-1]['bounds'][1]+choices[-1]['bounds'][3]+5),'choices')]
    for old_rows,box,part in groups:
        readings=[]
        for gray in (False,True):
            name=f'government_offer_{part}'+('_gray_3x' if gray else '_3x')
            crop=image.crop(box)
            if gray:crop=crop.convert('L')
            target=Path(directory)/(name+'.png');crop.resize((crop.width*3,crop.height*3),Image.Resampling.BICUBIC).save(target)
            evidence['passes'].append(name)
            raw=_prepare_rows(_run_ocr(executable,target),crop.width,crop.height,name);mapped=[]
            for local in raw:
                x,y,w,h=local['provenance'][0]['normalized_bounds']
                r=_prepare_rows([dict(text=local['text'],confidence=local['confidence'],
                    x=(box[0]+x*crop.width)/640,y=(box[1]+y*crop.height)/480,
                    width=w*crop.width/640,height=h*crop.height/480)],640,480,name)[0]
                r['provenance'][0].update(crop=list(box),scale=3,normalized_crop_bounds=[x,y,w,h],
                    transform=('grayscale; ' if gray else '')+'bicubic enlargement')
                mapped.append(r)
            readings.append(sorted(mapped,key=lambda r:r['center'][1]))
        first,second=readings
        if len(first)!=len(second) or len(first)!=len(old_rows):continue
        if any(a['text']!=b['text'] or min(a['confidence'],b['confidence'])<.8 or not _same_location(a,b)
               or abs(old['center'][1]-a['center'][1])>4 or a['bounds'][0]<old['bounds'][0]-4
               or a['bounds'][0]+a['bounds'][2]>old['bounds'][0]+old['bounds'][2]+6
               for old,a,b in zip(old_rows,first,second)):continue
        for old,a,b in zip(old_rows,first,second):
            a['provenance']=old['provenance']+a['provenance']+b['provenance'];rows[rows.index(old)]=a


def _recover_history_rows(image,rows,executable,directory,evidence):
    if image.size!=(640,480) or not any('completes his' in r['text'] for r in rows):return
    for index,old in enumerate(rows):
        if not ('completes his' in old['text'] or re.match(r'[1-7]\. The ',old['text'])):continue
        a=_crop_text(image,old,'history_rgb_'+str(index),executable,directory,evidence,padding=((2,2) if 'completes his' in old['text'] else (4,3)))
        b=_crop_text(image,old,'history_gray_'+str(index),executable,directory,evidence,padding=((2,2) if 'completes his' in old['text'] else (4,3)),grayscale=True)
        if (len(a)==len(b)==1 and a[0]['text']==b[0]['text'] and b[0]['confidence']>=.8
                and _same_location(a[0],b[0])
                and _replace_crop_row(rows,index,a,lambda previous,fresh: (
                    ('completes his' in previous and 'completes his' in fresh) or
                    (bool(re.match(r'[1-7]\. The ',fresh)) and previous.split('.',1)[0]==fresh.split('.',1)[0])))):
            rows[index]['provenance']+=b[0]['provenance']


def _recover_missing_history_rank(image,rows,executable,directory,evidence):
    """Read an omitted printed rank; never infer one from a rank adjective."""
    if image.size!=(640,480):return
    headings=[r for r in rows if re.fullmatch(r'[A-Za-z -]+ completes his epic history:',r['text'])]
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','exit')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    heading,ok=headings[0],controls[0]
    for index,old in enumerate(rows):
        x,y,w,h=old['bounds']
        if (not re.fullmatch(r'The [A-Za-z]+ Civilization of the [A-Za-z -]+',old['text'])
                or not 90<=x<=110 or not 10<=h<=24
                or not heading['center'][1]+35<=old['center'][1]<ok['center'][1]-15):continue
        a=_crop_text(image,old,'history_rank_rgb2',executable,directory,evidence,padding=(x-76,3),scale=2)
        b=_crop_text(image,old,'history_rank_gray2',executable,directory,evidence,padding=(x-76,3),scale=2,grayscale=True)
        if (len(a)!=2 or len(b)!=2 or [r['text'] for r in a]!=[r['text'] for r in b]
                or not re.fullmatch('[1-7]\\.',a[0]['text']) or a[1]['text']!=old['text']
                or min(r['confidence'] for r in a+b)<.8
                or not all(_same_location(p,q) for p,q in zip(a,b))):continue
        if any(not (76<=r[0]['bounds'][0]<=85 and 0<=r[1]['bounds'][0]-r[0]['bounds'][0]-r[0]['bounds'][2]<=8
                    and abs(r[0]['center'][1]-r[1]['center'][1])<=3 and _same_location(old,r[1])) for r in (a,b)):continue
        left=a[0]['bounds'][0];top=min(r['bounds'][1] for r in a)
        right=max(r['bounds'][0]+r['bounds'][2] for r in a);bottom=max(r['bounds'][1]+r['bounds'][3] for r in a)
        fresh=dict(a[1],text=a[0]['text']+' '+a[1]['text'],bounds=[left,top,right-left,bottom-top],
            center=[round((left+right)/2),round((top+bottom)/2)],x=left/640,y=top/480,
            width=(right-left)/640,height=(bottom-top)/480,
            provenance=old['provenance']+[p for r in a+b for p in r['provenance']])
        rows[index]=fresh


def _recover_history_title(image,rows,executable,directory,evidence):
    """Re-read a historian window title; keep both actual crop readings."""
    if image.size!=(640,480):return
    headers=[r for r in rows if re.fullmatch(r'.{1,40} completes his epic history:?',r['text'])]
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','close','exit')]
    if len(headers)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    header=headers[0];y=header['center'][1]
    categories=[r for r in rows if 'Civilizations in the World' in r['text']
                and 16<=r['center'][1]-y<=26 and abs(r['center'][0]-header['center'][0])<=8]
    if len(categories)!=1:return
    from .history_notice import _distance,_normal
    for index,old in enumerate(rows):
        x,_,w,h=old['bounds']
        if (not 270<=x<=290 or not 65<=w<=100 or h>24
                or not 16<=y-old['center'][1]<=30
                or abs(old['center'][0]-header['center'][0])>8
                or _distance(_normal(old['text']),'civilization ii')<=3):continue
        for scale,padding in ((2,(3,3)),(3,(3,3)),(2,(6,6))):
            a=_crop_text(image,old,f'history_title_rgb{scale}'+('_pad6' if padding[0]==6 else ''),executable,directory,evidence,padding=padding,scale=scale)
            b=_crop_text(image,old,f'history_title_gray{scale}'+('_pad6' if padding[0]==6 else ''),executable,directory,evidence,padding=padding,scale=scale,grayscale=True)
            if (len(a)==len(b)==1 and a[0]['text']==b[0]['text']
                    and min(a[0]['confidence'],b[0]['confidence'])>=.8
                    and _distance(_normal(a[0]['text']),'civilization ii')<=3
                    and _same_location(a[0],b[0]) and _same_location(old,b[0])):
                if _replace_crop_row(rows,index,a,lambda previous,fresh:True):rows[index]['provenance']+=b[0]['provenance']
                break


def _recover_acquisition_line(image,rows,executable,directory,evidence):
    if image.size!=(640,480):return
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Close')]
    if len(controls)!=1 or controls[0]['text']!='OK':return
    for index,old in enumerate(rows):
        x,y,w,h=old['bounds']
        if (not 185<=x<=215 or not 200<=y<=245 or w>310 or h>24
                or not re.fullmatch(r'.{1,40} acquire .{1,81}',old['text'])
                or not 24<=controls[0]['center'][1]-old['center'][1]<=64):continue
        a=_crop_text(image,old,'acquisition_line_rgb3',executable,directory,evidence,padding=(3,3))
        b=_crop_text(image,old,'acquisition_line_gray3',executable,directory,evidence,padding=(3,3),grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8 or not _same_location(a[0],b[0])
                or not _same_location(old,b[0]) or not re.fullmatch(r'.{1,40} acquire .{1,80}!',a[0]['text'])):continue
        if _replace_crop_row(rows,index,a,lambda previous,fresh:True):rows[index]['provenance']+=b[0]['provenance']


def _recover_discovery_punctuation(image,rows,executable,directory,evidence):
    """Read the final period twice without changing the observed advance name."""
    if image.size!=(640,480):return
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help')]
    titles=[r for r in rows if _near_text(r['text'].casefold(),'civilization advance',3)
            and r['confidence']>=.8 and 280<=r['center'][0]<=360]
    prose=[r for r in rows if re.fullmatch(r'.{1,40} wise men discover the secret of',r['text'])
           and r['confidence']>=.8]
    if (len(controls)!=1 or controls[0]['text']!='OK' or len(titles)!=1 or len(prose)!=1
            or not titles[0]['center'][1]<prose[0]['center'][1]<controls[0]['center'][1]):return
    names=_research_names()
    # The complete discovery sentence and independently visible advance name
    # locate a title reread; only an existing source-classifier spelling wins.
    from .native_events import TITLE_ALIASES
    allowed={'civilization advance',*TITLE_ALIASES['CIVADVANCE']}
    complete_names=[r for r in rows if r['confidence']>=.8 and r['text'].endswith('.')
                    and r['text'][:-1].casefold() in names
                    and prose[0]['center'][1]<r['center'][1]<controls[0]['center'][1]]
    title=titles[0]
    if title['text'].casefold() not in allowed and len(complete_names)==1:
        a=_crop_text(image,title,'discovery_title_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
        b=_crop_text(image,title,'discovery_title_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
        if (len(a)==len(b)==1 and a[0]['text']==b[0]['text'] and a[0]['text'].casefold() in allowed
                and min(a[0]['confidence'],b[0]['confidence'])>=.8
                and _same_location(title,a[0]) and _same_location(a[0],b[0])):
            if _replace_crop_row(rows,rows.index(title),a,lambda old,new:True):a[0]['provenance']+=b[0]['provenance']
    for index,row in enumerate(rows):
        text=row['text'];x,y,w,h=row['bounds']
        if (row['confidence']<.8 or not text.endswith(':') or text[:-1].casefold() not in names
                or not prose[0]['center'][1]<row['center'][1]<controls[0]['center'][1]
                or not 185<=x<=215 or not 200<=y<=280 or w>310 or h>24):continue
        expected=text[:-1]+'.'
        first=_crop_text(image,row,'discovery_period_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
        second=_crop_text(image,row,'discovery_period_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
        if (len(first)==len(second)==1 and first[0]['text']==second[0]['text']==expected
                and min(first[0]['confidence'],second[0]['confidence'])>=.8
                and _same_location(row,second[0]) and _same_location(first[0],second[0])):
            if _replace_crop_row(rows,index,first,lambda old,new:new==expected):rows[index]['provenance']+=second[0]['provenance']


def _recover_production_change_prose(image,rows,executable,directory,evidence):
    if image.size!=(640,480):return
    from .production_change import TITLE_READINGS
    if not any(r['text'].casefold() in TITLE_READINGS for r in rows):return
    if (sum('Continue producing ' in r['text'] for r in rows)!=1
            or sum(r['text'].startswith('Switch to ') and r['text'].endswith('% penalty.') for r in rows)!=1):return
    old='Sire, if we change ou production between items';expected='Sire, if we change our production between items'
    for index,row in enumerate(rows):
        if row['text']!=old or not 145<=row['bounds'][0]<=170 or not 160<=row['center'][1]<=210:continue
        a=_crop_text(image,row,'production_change_body_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
        b=_crop_text(image,row,'production_change_body_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
        if (len(a)==len(b)==1 and a[0]['text']==b[0]['text']==expected
                and min(a[0]['confidence'],b[0]['confidence'])>=.8 and _same_location(row,b[0])
                and _same_location(a[0],b[0]) and _replace_crop_row(rows,index,a,lambda previous,fresh:fresh==expected)):
            rows[index]['provenance']+=b[0]['provenance']


def _recover_gape_boundary(image,rows,executable,directory,evidence):
    """Recover only an independently read sentence boundary in GAPE prose."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['text'].endswith(' Emissary') and r['confidence']>=.8]
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help')]
    if len(titles)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    for index,row in enumerate(rows):
        match=re.fullmatch(r'wonders of (.{1,80}) Absolutely no',row['text'])
        if (not match or row['confidence']<.8 or row['bounds'][0]<300
                or not titles[0]['center'][1]<row['center'][1]<controls[0]['center'][1]):continue
        expected='wonders of '+match[1]+'. Absolutely no'
        a=_crop_text(image,row,'gape_boundary_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
        b=_crop_text(image,row,'gape_boundary_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
        if (len(a)==len(b)==1 and a[0]['text']==b[0]['text']==expected
                and min(a[0]['confidence'],b[0]['confidence'])>=.8
                and _same_location(row,b[0]) and _same_location(a[0],b[0])):
            if _replace_crop_row(rows,index,a,lambda old,new:True):rows[index]['provenance']+=b[0]['provenance']

    prose=sorted([r for r in rows if titles[0]['center'][1]<r['center'][1]<controls[0]['center'][1]-12
                  and 302<=r['bounds'][0]<=316],key=lambda r:r['center'][1])
    if (len(prose)!=4 or prose[0]['text']!='"You are invited to gape with awe and'
            or not re.fullmatch(r'amazement as the [A-Za-z ]{2,40} demonstrate the',prose[1]['text'])
            or not re.fullmatch(r'wonders of [A-Za-z ]{2,60}\. Absolutely no scribes',prose[2]['text'])
            or prose[3]['text']!='will he allowed."'
            or any(r['confidence']<.8 for r in prose)
            or any(not 16<=b['center'][1]-a['center'][1]<=26 for a,b in zip(prose,prose[1:]))):return
    old=prose[3]
    a=_crop_text(image,old,'gape_tail_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
    b=_crop_text(image,old,'gape_tail_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
    if (len(a)==len(b)==1 and a[0]['text']==b[0]['text']=='will be allowed."'
            and min(a[0]['confidence'],b[0]['confidence'])>=.8
            and _same_location(old,b[0]) and _same_location(a[0],b[0])):
        index=rows.index(old)
        if _replace_crop_row(rows,index,a,lambda before,after:True):rows[index]['provenance']+=b[0]['provenance']


def _recover_upgrade_boundaries(image,rows,executable,directory,evidence):
    """Read original upgrade punctuation and radio text together, from pixels."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['text']=='Domestic Advisor' and r['confidence']>=.8]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Exit')]
    if len(titles)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    title,ok=titles[0],controls[0]
    panel=sorted([r for r in rows if title['center'][1]<r['center'][1]<ok['center'][1]
                  and 216<=r['bounds'][0]<=280],key=lambda r:r['center'][1])
    if (len(panel)!=4 or any(r['confidence']<.8 for r in panel)
            or not re.fullmatch(r'Production orders in [A-Za-z][A-Za-z -]{1,59} upgraded from',panel[0]['text'])
            or not re.fullmatch(r'[A-Za-z][A-Za-z -]{1,59} to [A-Za-z][A-Za-z -]{1,59}[.,]',panel[1]['text'])
            or not re.fullmatch(r'(?:[O○●•©)]{1,2} )?Zoom to City',panel[2]['text'])
            or not re.fullmatch(r'(?:[O○●•] )?Continue',panel[3]['text'])
            or any(not 16<=b['center'][1]-a['center'][1]<=32 for a,b in zip(panel,panel[1:]))):return
    repairs=[]
    if panel[1]['text'].endswith(','):repairs.append((panel[1],panel[1]['text'][:-1]+'.','tail'))
    if panel[2]['text'].startswith('©) '):
        repairs.append((panel[2],'Zoom to City','zoom'))
        if panel[3]['text']!='Continue':repairs.append((panel[3],'Continue','continue'))
    replacements=[]
    for old,expected,name in repairs:
        a=_crop_text(image,old,f'upgrade_{name}_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
        b=_crop_text(image,old,f'upgrade_{name}_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or a[0]['text']!=expected
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        fresh=dict(a[0]);fresh['provenance']=old['provenance']+a[0]['provenance']+b[0]['provenance']
        replacements.append((rows.index(old),fresh))
    # The short-control pass may have reported Continue against its native
    # radio prefix. Only this now twice-read same control resolves that exact
    # conflict; preserve the conflicting read as evidence, never erase it.
    resolved=[]
    for index,fresh in replacements:
        old=rows[index]
        if fresh['text']=='Continue' and re.fullmatch(r'[O○●•] Continue',old['text']):
            for conflict in evidence.get('conflicts',[]):
                bounds=conflict.get('bounds',[])
                if (conflict.get('text')!='Continue' or conflict.get('reason')!='contradictory overlapping native text'
                        or not isinstance(bounds,list) or len(bounds)!=4 or any(type(v)is not int for v in bounds)
                        or bounds[2]<=0 or bounds[3]<=0):continue
                other={'bounds':bounds,'center':[round(bounds[0]+bounds[2]/2),round(bounds[1]+bounds[3]/2)]}
                if _same_location(old,other) and _same_location(fresh,other):resolved.append(conflict)
        rows[index]=fresh
    if resolved:
        evidence.setdefault('resolved_control_conflicts',[]).extend(deepcopy(resolved))
        evidence['conflicts']=[c for c in evidence['conflicts'] if c not in resolved]


def _recover_production_upgrade_city(image,rows,executable,directory,evidence):
    """Read a changed city spelling at two scales; never take its name from state."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text']=='Domestic Advisor' and r['confidence']>=.8]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Exit')]
    choices=[r for r in rows if re.fullmatch(r'(?:[O○●•] )?(?:Zoom to City|Continue)',r['text'])]
    if (len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK' or len(choices)!=2
            or {re.sub(r'^[O○●•] ','',r['text']) for r in choices}!={'Zoom to City','Continue'}):return
    candidates=[(i,r,m) for i,r in enumerate(rows)
                if (m:=re.fullmatch(r'Production orders in ([A-Za-z][A-Za-z -]{1,59}) upgraded from',r['text']))
                and r['confidence']>=.8 and 216<=r['bounds'][0]<=240
                and headings[0]['center'][1]+10<r['center'][1]<min(c['center'][1] for c in choices)-25]
    if len(candidates)!=1:return
    index,old,match=candidates[0]
    tails=[r for r in rows if re.fullmatch(r'[A-Za-z][A-Za-z -]{1,59} to [A-Za-z][A-Za-z -]{1,59}\.',r['text'])
           and r['confidence']>=.8 and 216<=r['bounds'][0]<=240 and 16<=r['center'][1]-old['center'][1]<=28]
    if len(tails)!=1:return
    readings=[]
    for scale in (3,2):
        a=_crop_text(image,old,f'upgrade_city_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
        b=_crop_text(image,old,f'upgrade_city_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        fresh=re.fullmatch(r'Production orders in ([A-Za-z][A-Za-z -]{1,59}) upgraded from',a[0]['text'])
        if not fresh or not _near_text(match[1].casefold(),fresh[1].casefold(),1) or fresh[1]==match[1]:return
        readings.append((a[0],b[0]))
    if readings[0][0]['text']!=readings[1][0]['text']:return
    # Keep the native reading. A cropped pair can share a font error, so only
    # the source-bound classifier may resolve a unique owned city from these
    # competing actual readings. Neither supplies a name from unseen state.
    old['production_upgrade_city_reading']={
        'source_sha256':evidence.get('source_image_sha256'),
        'native_text':old['text'],'row_bounds':list(old['bounds']),
        'text':readings[0][0]['text'],
        'readings':[p for pair in readings for r in pair for p in r['provenance']]}


def _recover_support_notice(image,rows,executable,directory,evidence):
    """Two real crops restore an observed support-loss report, not an action."""
    if image.size!=(640,480):return
    choices=[r for r in rows if re.fullmatch(r'(?:[Oo0•○●]\s+)?(?:Zoom to City|Continue)',r['text'])]
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help')]
    if (len(choices)!=2 or {re.sub(r'^[Oo0•○●]\s+','',r['text']) for r in choices}!={'Zoom to City','Continue'}
            or len(controls)!=1 or controls[0]['text']!='OK'):return
    body=[(i,r,m) for i,r in enumerate(rows)
          if (m:=re.fullmatch(r"(.+) can't support (.+)[,.] Unit dis[bh]anded\.",r['text']))
          and r['confidence']>=.8 and r['center'][1]<min(c['center'][1] for c in choices)]
    if len(body)!=1:return
    bi,br,match=body[0]
    titles=[(i,r) for i,r in enumerate(rows) if r['confidence']>=.8
            and _near_text(r['text'].casefold(),'military advisor',3)
            and 16<=br['center'][1]-r['center'][1]<=40
            and abs(r['center'][0]-controls[0]['center'][0])<=8]
    if len(titles)!=1:return
    expected_body=match[1]+" can't support "+match[2]+'. Unit disbanded.'
    replacements=[]
    tasks=[(*titles[0],'Military Advisor','title'),(bi,br,expected_body,'body')]
    # A lowercase radio glyph is only a crop locator: require both actual
    # readings of the complete original label before the classifier sees it.
    tasks.extend((rows.index(r),r,r['text'][2:],'option') for r in choices if r['text'].startswith('o '))
    for index,row,expected,name in tasks:
        a=_crop_text(image,row,'support_'+name+'_rgb2',executable,directory,evidence,padding=(6,6),scale=2)
        b=_crop_text(image,row,'support_'+name+'_gray2',executable,directory,evidence,padding=(6,6),scale=2,grayscale=True)
        def valid():
            return (len(a)==len(b)==1 and a[0]['text']==b[0]['text']==expected
                    and min(a[0]['confidence'],b[0]['confidence'])>=.8
                    and _same_location(row,b[0]) and _same_location(a[0],b[0]))
        if not valid() and len(a)==len(b)==1 and a[0]['text']==b[0]['text']:
            if name=='title' and _near_text(a[0]['text'].casefold(),'military advisor',3):
                a=_crop_text(image,row,'support_title_rgb4',executable,directory,evidence,padding=(3,3),scale=4)
                b=_crop_text(image,row,'support_title_gray4',executable,directory,evidence,padding=(3,3),scale=4,grayscale=True)
            elif name=='body' and a[0]['text'] in (row['text'],expected.replace('disbanded','dishanded')):
                a=_crop_text(image,row,'support_body_black70_2x',executable,directory,evidence,padding=(6,6),scale=2,black_threshold=70)
                b=_crop_text(image,row,'support_body_black70_3x',executable,directory,evidence,padding=(6,6),scale=3,black_threshold=70)
        if not valid():return
        a[0]['provenance']=row['provenance']+a[0]['provenance']+b[0]['provenance'];replacements.append((index,a[0]))
    for index,row in replacements:rows[index]=row


def _recover_travellers_title(image,rows,executable,directory,evidence):
    """Read a public wonder report; preserve every nation and project name."""
    if image.size!=(640,480):return
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help')]
    if len(controls)!=1 or controls[0]['text']!='OK':return
    bodies=[r for r in rows if re.match(r'The .+ have (?:undertaken|changed|abandoned|ahandoned|nearly completed) ',r['text'])
            and r['confidence']>=.8]
    if len(bodies)!=1:return
    headings=[r for r in rows if r['confidence']>=.8
              and _near_text(r['text'].casefold(),'travellers report',3)
              and 16<=bodies[0]['center'][1]-r['center'][1]<=40
              and abs(r['center'][0]-controls[0]['center'][0])<=8]
    if len(headings)!=1:return
    title=headings[0];tasks=[]
    if title['text']!='Travellers Report':tasks.append((title,'title','Travellers Report'))
    damaged=re.fullmatch(r'The ([A-Za-z -]{2,60}) have ahandoned their great project,',bodies[0]['text'])
    if damaged:
        tails=[r for r in rows if 196<=r['bounds'][0]<=210
               and 15<=r['center'][1]-bodies[0]['center'][1]<=26
               and r['center'][1]<controls[0]['center'][1] and r['confidence']>=.8
               and re.fullmatch(r"[A-Za-z0-9 '&().-]{2,80}\.",r['text'])]
        if len(tails)!=1:return
        tasks.append((bodies[0],'abandon_body','The '+damaged[1]+' have abandoned their great project,'))
    if ' have changed projects from ' in bodies[0]['text']:
        tails=[r for r in rows if 196<=r['bounds'][0]<=210
               and 15<=r['center'][1]-bodies[0]['center'][1]<=26
               and r['center'][1]<controls[0]['center'][1] and r['confidence']>=.8]
        if len(tails)==1:
            tail=tails[0];text=bodies[0]['text']+' '+tail['text']
            switched=re.fullmatch(r"The ([A-Za-z -]{2,60}) have changed projects from ([A-Za-z0-9 '&()-]{2,80}) to ([A-Za-z0-9 '&()-]{2,80})[lI]",text)
            names=_production_names()
            if switched and switched[2].casefold() in names and switched[3].casefold() in names:
                tasks.append((tail,'switch_punctuation',tail['text'][:-1]+'!'))
    recovered=[]
    for old,name,wanted in tasks:
        a=_crop_text(image,old,f'travellers_{name}_rgb3',executable,directory,evidence,padding=(3,3))
        b=_crop_text(image,old,f'travellers_{name}_gray3',executable,directory,evidence,padding=(3,3),grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or a[0]['text']!=wanted
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,b[0]) or not _same_location(a[0],b[0])):return
        recovered.append((old,a[0],b[0]))
    for old,a,b in recovered:
        a['provenance']=old['provenance']+a['provenance']+b['provenance']
        rows[rows.index(old)]=a


def _recover_changed_wonder_tail(image,rows,executable,directory,evidence):
    """Split measured colored art from a complete four-read wonder notice."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['text']=='Travellers Report' and r['confidence']>=.8]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Continue')]
    firsts=[r for r in rows if re.fullmatch(r'The [A-Za-z -]{2,50} have changed projects from .{1,60}',r['text'])
            and r['confidence']>=.8 and 195<=r['bounds'][0]<=205]
    if len(titles)!=1 or len(controls)!=1 or controls[0]['text']!='OK' or len(firsts)!=1:return
    title,ok,first=titles[0],controls[0],firsts[0]
    if (abs(title['center'][0]-ok['center'][0])>8 or not 16<=first['center'][1]-title['center'][1]<=36):return
    tails=[r for r in rows if r['confidence']>=.8 and 16<=r['center'][1]-first['center'][1]<=26
           and r['center'][1]<ok['center'][1]-12 and re.fullmatch(r'[A-Za-z]{1,8}to .{1,60}',r['text'])]
    if len(tails)!=1:return
    old=tails[0];x,y,w,h=old['bounds'];left=first['bounds'][0]
    if not (20<=left-x<=60 and 14<=h<=24 and left+30<=x+w<=520):return
    strip=image.convert('RGB').crop((x,y,left,y+h));pixels=list(strip.getdata())
    chromatic=sum(max(c)-min(c)>=24 for c in pixels)
    if chromatic*2<=len(pixels):return
    target=re.fullmatch(r'[A-Za-z]{1,8}to (.{1,60})',old['text'])[1].rstrip('!.')
    crop=deepcopy(old);crop.update(bounds=[left,y,x+w-left,h],center=[round((left+x+w)/2),round(y+h/2)],
                                x=left/640,width=(x+w-left)/640)
    readings=[]
    for scale in (2,3):
        a=_crop_text(image,crop,f'changed_wonder_tail_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
        b=_crop_text(image,crop,f'changed_wonder_tail_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(crop,a[0]) or not _same_location(a[0],b[0])):return
        fresh=re.fullmatch(r'to (.{1,60})!',a[0]['text'])
        if not fresh or not _near_text(target,fresh[1],2):return
        readings.extend((a[0],b[0]))
    if len({r['text'] for r in readings})!=1:return
    fresh=readings[0];fresh['provenance']=old['provenance']+[p for r in readings for p in r['provenance']]
    fresh['wonder_art_split']={'source_image_sha256':evidence.get('source_image_sha256'),
        'original_bounds':list(old['bounds']),'text_crop_bounds':list(crop['bounds']),
        'art_bounds':[x,y,left-x,h],'art_rgb_sha256':hashlib.sha256(strip.tobytes()).hexdigest(),
        'chromatic_pixels':chromatic,'pixel_count':len(pixels),'rgb_spread_threshold':24,
        'scope':'Colored artwork split only; four complete actual text reads and full original notice still required.'}
    rows[rows.index(old)]=fresh


def _recover_population_decrease_option(image,rows,executable,directory,evidence):
    """Read an accented radio label; retain the actual population-loss choice."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['text']=='Domestic Advisor' and r['confidence']>=.8]
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help')]
    if len(titles)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    title,ok=titles[0],controls[0]
    if abs(title['center'][0]-ok['center'][0])>8:return
    panel=[r for r in rows if title['center'][1]<r['center'][1]<ok['center'][1]
           and abs(r['center'][0]-title['center'][0])<=225]
    panel.sort(key=lambda r:r['center'][1])
    if (len(panel)!=3 or not re.fullmatch(r'Population decrease in [A-Za-z][A-Za-z -]{0,59}\.',panel[0]['text'])
            or panel[1]['text'] not in ('Zoom to City','• Zoom to City') or panel[2]['text']!='O Contínue'
            or any(r['confidence']<.8 for r in [*panel,ok])):return
    old=panel[2];index=rows.index(old)
    a=_crop_text(image,old,'population_continue_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
    b=_crop_text(image,old,'population_continue_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or a[0]['text']!='Continue'
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(old,b[0]) or not _same_location(a[0],b[0])):return
    if _replace_crop_row(rows,index,a,lambda before,after:after=='Continue'):
        rows[index]['provenance']+=b[0]['provenance']


def _recover_population_notice(image,rows,executable,directory,evidence):
    """Read original milestone punctuation without changing its digits."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['text']=='Domestic Advisor' and r['confidence']>=.8]
    bodies=[r for r in rows if re.fullmatch(r"The population of(?: |')the fertile .+ empire now exceeds",r['text'])
            and r['confidence']>=.8]
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help')]
    if len(titles)!=1 or len(bodies)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    body=bodies[0]
    if "of'the" in body['text']:
        tails=[r for r in rows if re.fullmatch(r'\d{1,3}(?:[,.]\d{3})+ citizens\.',r['text'])
               and r['confidence']>=.8 and abs(r['bounds'][0]-body['bounds'][0])<=6
               and 17<=r['center'][1]-body['center'][1]<=26]
        if (len(tails)!=1 or not 140<=body['bounds'][0]<=155 or not 200<=body['bounds'][1]<=213
                or not titles[0]['center'][1]<body['center'][1]<tails[0]['center'][1]<controls[0]['center'][1]
                or abs(titles[0]['center'][0]-controls[0]['center'][0])>6):return
        wanted=body['text'].replace("of'the",'of the')
        a=_crop_text(image,body,'population_body_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
        b=_crop_text(image,body,'population_body_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=wanted or b[0]['text']!=wanted
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(body,a[0]) or not _same_location(a[0],b[0])):return
        index=rows.index(body)
        if _replace_crop_row(rows,index,a,lambda old,new:True):rows[index]['provenance']+=b[0]['provenance']
        bodies=[rows[index]]
    for index,row in enumerate(rows):
        if (row['confidence']<.8 or not re.fullmatch(r'\d{1,3}(?:\.\d{3})+ citizens\.',row['text'])
                or not titles[0]['center'][1]<bodies[0]['center'][1]<row['center'][1]<controls[0]['center'][1]
                or abs(row['bounds'][0]-bodies[0]['bounds'][0])>6):continue
        a=_crop_text(image,row,'population_rgb3',executable,directory,evidence,padding=(3,3))
        b=_crop_text(image,row,'population_gray3',executable,directory,evidence,padding=(3,3),grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(row,b[0]) or not _same_location(a[0],b[0])
                or not re.fullmatch(r'\d{1,3}(?:,\d{3})+ citizens\.',a[0]['text'])
                or re.findall(r'\d+',row['text'])!=re.findall(r'\d+',a[0]['text'])):continue
        if _replace_crop_row(rows,index,a,lambda old,new:True):rows[index]['provenance']+=b[0]['provenance']


def _recover_map_menu_label(image,rows,executable,directory,evidence):
    """Recover a clipped menu label from pixels; no modal/map guard is relaxed."""
    if image.size!=(640,480):return
    menu=' '.join(r['text'].casefold() for r in rows if 18<=r['center'][1]<=38)
    if not all(re.search(r'\b'+word+r'\b',menu) for word in ('kingdom','view','orders','advisors','civilopedia')):return
    candidates=[(i,r) for i,r in enumerate(rows) if r['text']=='ame'
                and 6<=r['bounds'][0]<=20 and 20<=r['bounds'][1]<=26
                and 24<=r['bounds'][2]<=40 and 8<=r['bounds'][3]<=16]
    if len(candidates)!=1 or re.search(r'\bgame\b',menu):return
    index,old=candidates[0]
    a=_crop_text(image,old,'map_menu_rgb3',executable,directory,evidence,padding=(6,3),scale=3)
    b=_crop_text(image,old,'map_menu_gray3',executable,directory,evidence,padding=(6,3),grayscale=True,scale=3)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!='Game' or b[0]['text']!='Game'
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(old,b[0]) or not _same_location(a[0],b[0])):return
    if _replace_crop_row(rows,index,a,lambda before,after:True):rows[index]['provenance']+=b[0]['provenance']


def _recover_map_heading(image,rows,executable,directory,evidence):
    """Read the original map-pane heading twice; no native state supplies text."""
    if image.size!=(640,480):return
    menu=' '.join(r['text'].casefold() for r in rows if 18<=r['center'][1]<=38)
    if not all(re.search(r'\b'+word+r'\b',menu) for word in ('game','view','orders','advisors','civilopedia')):return
    if (len([r for r in rows if r['text'].casefold().strip('!') in ('world','workd','workl','work') and 500<=r['center'][0]<=600 and 40<=r['center'][1]<=64])!=1
            or len([r for r in rows if _near_text(r['text'],'Status',1) and 500<=r['center'][0]<=600 and 176<=r['center'][1]<=202])!=1):return
    candidates=[(i,r) for i,r in enumerate(rows) if r['text']!='Roman Map'
                and r['confidence']>=.8 and _near_text(r['text'],'Roman Map',1)
                and 180<=r['bounds'][0]<=210 and 40<=r['bounds'][1]<=52
                and 60<=r['bounds'][2]<=100 and 8<=r['bounds'][3]<=20]
    if len(candidates)!=1:return
    index,old=candidates[0]
    a=_crop_text(image,old,'map_heading_rgb3',executable,directory,evidence,padding=(3,3))
    b=_crop_text(image,old,'map_heading_gray3',executable,directory,evidence,padding=(3,3),grayscale=True)
    previous=[]
    if (len(a)==len(b)==1 and a[0]['text']==b[0]['text'] and a[0]['text']!='Roman Map'
            and _near_text(a[0]['text'],'Roman Map',1)
            and min(a[0]['confidence'],b[0]['confidence'])>=.8
            and _same_location(old,b[0]) and _same_location(a[0],b[0])):
        previous=a[0]['provenance']+b[0]['provenance']
        a=_crop_text(image,old,'map_heading_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
        b=_crop_text(image,old,'map_heading_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or a[0]['text']!='Roman Map'
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(old,b[0]) or not _same_location(a[0],b[0])):return
    if _replace_crop_row(rows,index,a,lambda before,after:True):rows[index]['provenance']+=previous+b[0]['provenance']


def _recover_status_population(image,rows,executable,directory,evidence):
    """Resolve one punctuation-shaped digit only from four complete reads."""
    if image.size!=(640,480):return
    status=[r for r in rows if _near_text(r['text'],'Status',1)
            and 500<=r['center'][0]<=600 and 176<=r['center'][1]<=202]
    if len(status)!=1:return
    for index,old in enumerate(rows):
        match=re.fullmatch(r'([0-9:]{1,3}(?:,[0-9]{3})+) People',old['text'])
        x,y,w,h=old['bounds']
        if (not match or match[1].count(':')!=1 or old['confidence']<.8
                or not 470<=x<=485 or not 202<=y<=212 or not 60<=w<=160 or not 8<=h<=16):continue
        readings=[]
        for scale in (3,2):
            a=_crop_text(image,old,f'status_population_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
            b=_crop_text(image,old,f'status_population_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
            if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                    or min(a[0]['confidence'],b[0]['confidence'])<.8
                    or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):break
            fresh=re.fullmatch(r'([0-9]{1,3}(?:,[0-9]{3})+) People',a[0]['text'])
            if (not fresh or len(fresh[1])!=len(match[1])
                    or any(before!=':' and before!=after for before,after in zip(match[1],fresh[1]))):break
            readings.extend((a[0],b[0]))
        if len(readings)!=4 or len({r['text'] for r in readings})!=1:continue
        fresh=readings[0];fresh['provenance']=[p for r in readings for p in r['provenance']]
        _replace_crop_row(rows,index,[fresh],lambda before,after:True)


def _recover_treasury_marker(image,rows,executable,directory,evidence):
    """Recover a status layout marker; native memory/save remains the amount source."""
    if image.size!=(640,480):return
    pattern=r'[0-9ile,]{1,16}\s+(?:gold|cold)(?:\s+[0-9.]+)?'
    for index,old in enumerate(rows):
        x,y,w,h=old['bounds']
        if (not x>=470 or not 220<=y<=242 or w>168 or h>24
                or not re.search(r'(?<![A-Za-z])(?:gold|cold)\b',old['text'],re.I)
                or re.fullmatch(pattern,old['text'].casefold())):continue
        readings=[_crop_text(image,old,'treasury_marker_'+name,executable,directory,evidence,
                            padding=(3,3),grayscale=gray) for name,gray in (('rgb3',False),('gray3',True))]
        a,b=readings
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(a[0],b[0]) or not _same_location(old,b[0])
                or not re.fullmatch(pattern,a[0]['text'].casefold())):continue
        if _replace_crop_row(rows,index,a,lambda before,after:True):rows[index]['provenance']+=b[0]['provenance']


def _recover_lettered_status_year(image,rows,executable,directory,evidence):
    """Unreadable year letters need six complete source-pixel date readings."""
    for index,old in enumerate(rows):
        x,y,w,h=old['bounds']
        if (not re.fullmatch(r'ALD\. [A-Za-z]{1,5}',old['text'])
                or not 470<=x<=485 or not 210<=y<=232
                or not 35<=w<=85 or not 8<=h<=20):continue
        readings=[]
        for scale in (2,3,4):
            for gray in (False,True):
                values=_crop_text(image,old,f'status_letter_year_{"gray" if gray else "rgb"}{scale}',
                    executable,directory,evidence,padding=(3,3),scale=scale,grayscale=gray)
                if len(values)!=1 or values[0]['confidence']<.8 or not _same_location(old,values[0]):break
                readings.append(values[0])
            if len(readings)!=2*(scale-1):break
        if (len(readings)!=6 or len({r['text'] for r in readings})!=1
                or not all(_same_location(readings[0],r) for r in readings[1:])):continue
        fresh=date_parts(readings[0]['text'])
        if fresh is None or fresh[1]!='AD' or not 1<=len(fresh[0])<=4:continue
        chosen=dict(readings[0]);chosen['provenance']=[p for r in readings for p in r['provenance']]
        _replace_crop_row(rows,index,[chosen],lambda before,after:True)


def _recover_punctuated_status_year(image,rows,executable,directory,evidence):
    """Read a colon-shaped year glyph at three scales, without a state date."""
    for index,old in enumerate(rows):
        match=re.fullmatch(r'A\.D\. ([0-9]{2}:[0-9]{2})',old['text']);x,y,w,h=old['bounds']
        if (not match or old['confidence']<.8 or not 470<=x<=485
                or not 210<=y<=232 or not 35<=w<=85 or not 8<=h<=20):continue
        readings=[]
        for scale in (2,3,4):
            for gray in (False,True):
                values=_crop_text(image,old,f'status_colon_year_{"gray" if gray else "rgb"}{scale}',
                    executable,directory,evidence,padding=(3,3),scale=scale,grayscale=gray)
                if len(values)!=1 or values[0]['confidence']<.8 or not _same_location(old,values[0]):break
                readings.append(values[0])
            if len(readings)!=2*(scale-1):break
        if (len(readings)!=6 or len({r['text'] for r in readings})!=1
                or not all(_same_location(readings[0],r) for r in readings[1:])):continue
        fresh=date_parts(readings[0]['text'])
        if (fresh is None or fresh[1]!='AD' or len(fresh[0])!=4
                or fresh[0][0]!=match[1][0] or fresh[0][-2:]!=match[1][-2:]
                or not _near_text(match[1],fresh[0],2)):continue
        chosen=dict(readings[0]);chosen['provenance']=[p for r in readings for p in r['provenance']]
        _replace_crop_row(rows,index,[chosen],lambda before,after:True)


def _recover_status_year(image,rows,executable,directory,evidence):
    """Read malformed status dates twice, preserving readable digits and era.

    The original changes to era-first captions after B.C. Two agreeing pixel
    reads may repair at most two damaged digits, including the observed single
    ``J`` in ``A.D. J``; native-state dates never supply the replacement.
    """
    if image.size!=(640,480):return
    _recover_lettered_status_year(image,rows,executable,directory,evidence)
    _recover_punctuated_status_year(image,rows,executable,directory,evidence)
    # A syntactically valid 1 can be a misread printed 7. Four complete
    # source-pixel reads, across two scales, must prove the sole digit change.
    for index,old in enumerate(rows):
        parts=date_parts(old['text']);x,y,w,h=old['bounds']
        # Do not replace the stronger six-read consensus using a new crop.
        if any(str(p.get('preprocessing','')).startswith(('status_letter_year_','status_colon_year_'))
               for p in old.get('provenance',[])):continue
        if (parts is None or parts[1]!='AD' or '1' not in parts[0] or old['confidence']<.8
                or not x>=470 or not 210<=y<=232 or w>160 or h>24):continue
        reads=[]
        for scale in (3,2):
            for gray in (False,True):
                values=_crop_text(image,old,f'status_seven_{"gray" if gray else "rgb"}{scale}',
                    executable,directory,evidence,padding=(3,3),scale=scale,grayscale=gray)
                if len(values)!=1 or values[0]['confidence']<.8 or not _same_location(old,values[0]):break
                reads.append(values[0])
            if len(reads)!=2*(1 if scale==3 else 2):break
        if (len(reads)!=4 or len({r['text'] for r in reads})!=1
                or not all(_same_location(reads[0],r) for r in reads[1:])):continue
        fresh=date_parts(reads[0]['text'])
        if (fresh is None or fresh[1]!=parts[1] or len(fresh[0])!=len(parts[0])
                or sum(a!=b for a,b in zip(parts[0],fresh[0]))!=1
                or not all(a==b or (a,b)==('1','7') for a,b in zip(parts[0],fresh[0]))):continue
        chosen=dict(reads[0]);chosen['provenance']=[p for r in reads for p in r['provenance']]
        _replace_crop_row(rows,index,[chosen],lambda before,after:True)
    era_pattern=r'([BВ]\.?\s*[CС]\.?|A\.?\s*D\.?)'
    year_pattern=r'([0-9A-Za-zА-Яа-я]{1,5})'
    era_glyphs=str.maketrans({'В':'B','в':'b','С':'C','с':'c'})
    def era(text):return re.sub(r'[^A-Za-z]','',text.translate(era_glyphs)).upper()
    for index,old in enumerate(rows):
        x,y,w,h=old['bounds']
        ambiguous_era=False
        suffix=re.fullmatch(year_pattern+r'\s+'+era_pattern,old['text'],re.I)
        prefix=re.fullmatch(era_pattern+r'\s*'+year_pattern,old['text'],re.I)
        number,old_era=(suffix[1],era(suffix[2])) if suffix else ((prefix[2],era(prefix[1])) if prefix else (None,None))
        trailing_mark=re.fullmatch(rf'({DATE_PATTERN})\s*[()]',old['text'],re.I)
        if number is None and trailing_mark:
            parts=date_parts(trailing_mark[1])
            if parts is not None:number,old_era=parts
        damaged_prefix=re.fullmatch(r'([A-Za-z0-9.]{2,6})\s+([0-9]{1,5})',old['text'])
        if damaged_prefix is None:
            damaged_prefix=re.fullmatch(r'([A-Za-z0-9]\.[A-Za-z]\.)\s*([0-9]{1,5})',old['text'])
        if number is None and damaged_prefix:
            candidates=[value for value in ('AD','BC') if _near_text(era(damaged_prefix[1]),value,1)]
            if len(candidates)==1:number,old_era=damaged_prefix[2],candidates[0]
            elif len(candidates)==2:number,ambiguous_era=damaged_prefix[2],True
        raw=re.fullmatch(r'([0-9]{1,5})\s+[^\s]{1,8}',old['text'])
        if raw is not None and number is None:number=raw[1]
        if number is None:continue
        damaged=sum(not c.isdigit() for c in number)
        if damaged and (not 1<=damaged<=2 or not (any(c.isdigit() for c in number)
                or prefix is not None and old_era=='AD' and re.fullmatch('[IJl]',number))):continue
        if (not x>=470 or not 210<=y<=232 or w>160 or h>24 or date_parts(old['text']) is not None):continue
        def compatible(parts):
            digits,new_era=parts
            return (len(digits)==len(number)
                    and all(not before.isdigit() or before==after for before,after in zip(number,digits))
                    and (old_era is None or new_era==old_era))
        def agrees(a,b):
            return (len(a)==len(b)==1 and a[0]['text']==b[0]['text']
                    and min(a[0]['confidence'],b[0]['confidence'])>=.8
                    and _same_location(a[0],b[0]) and _same_location(old,b[0]))
        era_readings=[];split_date=None
        for scale in (3,2):
            a=_crop_text(image,old,f'status_year_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
            b=_crop_text(image,old,f'status_year_gray{scale}',executable,directory,evidence,padding=(3,3),grayscale=True,scale=scale)
            # An era and its digits may be two adjacent OCR rows. They only
            # permit another crop scale; replacement still needs two actual
            # complete-row reads, not assembled or state-supplied date text.
            if scale==3 and len(a)==len(b)==2 and [r['text'] for r in a]==[r['text'] for r in b]:
                split=date_parts(' '.join(r['text'] for r in a))
                if (split is not None and compatible(split)
                        and min(r['confidence'] for r in [*a,*b])>=.8
                        and all(_same_location(p,q) for p,q in zip(a,b))
                        and all(abs(parts[0]['center'][1]-parts[1]['center'][1])<=3
                                and -2<=parts[1]['bounds'][0]-parts[0]['bounds'][0]-parts[0]['bounds'][2]<=8
                                and all(x-3<=r['bounds'][0] and r['bounds'][0]+r['bounds'][2]<=x+w+3
                                        and abs(r['center'][1]-old['center'][1])<=5 for r in parts) for parts in (a,b))):
                    split_date=split
                    continue
            if not agrees(a,b):break
            complete=date_parts(a[0]['text'])
            if split_date is not None and complete is not None and complete!=split_date:break
            # The native joined date can misread both its initial A and a 7
            # as 1. A second enlargement must independently read the whole
            # same date; neither the turn counter nor native state supplies it.
            if (scale==3 and complete is not None and damaged_prefix is not None
                    and not re.search(r'\s',old['text']) and old_era==complete[1]
                    and len(number)==len(complete[0])
                    and sum(left!=right for left,right in zip(number,complete[0]))==1
                    and all(left==right or (left,right)==('1','7') for left,right in zip(number,complete[0]))):
                c=_crop_text(image,old,'status_year_confirm_rgb4',executable,directory,evidence,padding=(3,3),scale=4)
                d=_crop_text(image,old,'status_year_confirm_gray4',executable,directory,evidence,padding=(3,3),scale=4,grayscale=True)
                if (agrees(c,d) and date_parts(c[0]['text'])==complete):
                    a[0]['provenance']+=c[0]['provenance']+d[0]['provenance']
                    if _replace_crop_row(rows,index,a,lambda before,after:True):rows[index]['provenance']+=b[0]['provenance']
                break
            corroborated=date_parts(a[0]['text'].translate(era_glyphs))
            if (complete is None and scale==3 and a[0]['text']!=old['text']
                    and corroborated is not None and compatible(corroborated)):
                a=_crop_text(image,old,'status_year_wide_rgb3',executable,directory,evidence,padding=(6,3),scale=3)
                b=_crop_text(image,old,'status_year_wide_gray3',executable,directory,evidence,padding=(6,3),grayscale=True,scale=3)
                if not agrees(a,b):break
                complete=date_parts(a[0]['text'])
            if complete is None:
                if scale==3 and a[0]['text']==old['text']:continue
                break
            if ambiguous_era:
                if not compatible(complete):break
                if scale==3:
                    era_readings=[a[0],b[0]]
                    continue
                if not era_readings and split_date is not None:
                    c=_crop_text(image,old,'status_year_era_rgb4',executable,directory,evidence,padding=(3,3),scale=4)
                    d=_crop_text(image,old,'status_year_era_gray4',executable,directory,evidence,padding=(3,3),scale=4,grayscale=True)
                    if not agrees(c,d) or date_parts(c[0]['text'])!=complete:break
                    era_readings=[c[0],d[0]]
                if not era_readings or any(date_parts(r['text'])!=complete for r in era_readings):break
                a[0]['provenance']=[p for r in era_readings for p in r['provenance']]+a[0]['provenance']
            if compatible(complete) and _replace_crop_row(rows,index,a,lambda before,after:True):
                rows[index]['provenance']+=b[0]['provenance']
            break


def _recover_diplomacy_intro(image,rows,executable,directory,evidence):
    """Two measured black-glyph crops recover punctuation, never menu choices."""
    if image.size!=(640,480):return
    candidates=[r for r in rows if 300<=r['bounds'][0]<=316 and 270<=r['bounds'][1]<=330
                and re.fullmatch(r'You respond: "We[.\"]*',r['text'])]
    headings=[r for r in rows if r['text'].endswith(' Emissary') and r['confidence']>=.8]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if (len(candidates)!=1 or len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK'
            or abs(headings[0]['center'][0]-controls[0]['center'][0])>8):return
    old=candidates[0]
    if old['text']=='You respond: "We..."':return
    if not 16<=old['center'][1]-headings[0]['center'][1]<=36:return
    options=[r for r in rows if r['bounds'][0]>=330 and old['center'][1]<r['center'][1]<controls[0]['center'][1]
             and r['text'].startswith('"') and r['text'].endswith('"') and r['confidence']>=.8]
    if not 2<=len(options)<=9:return
    x,y,w,h=old['bounds']
    for framings in (((3,14),(2,16)),((3,20),(4,20))):
        readings=[]
        for pad,right in framings:
            box=(x-pad,y-pad,min(640,x+w+right),min(480,y+h+pad));crop=image.crop(box)
            name=f'diplomacy_intro_black_3x_pad{pad}_right{right}';target=Path(directory)/(name+'.png')
            crop.convert('L').point(lambda value:255 if value>70 else 0).resize(
                (crop.width*3,crop.height*3),Image.Resampling.BICUBIC).save(target)
            evidence['passes'].append(name);raw=_run_ocr(executable,target)
            if len(raw)!=1 or raw[0]['text']!='You respond: "We..."' or raw[0]['confidence']<.8:break
            try:
                local=_prepare_rows(raw,crop.width,crop.height,name)[0]
                nx,ny,nw,nh=local['provenance'][0]['normalized_bounds']
                mapped=_prepare_rows([dict(text=local['text'],confidence=local['confidence'],
                    x=(box[0]+nx*crop.width)/640,y=(box[1]+ny*crop.height)/480,
                    width=nw*crop.width/640,height=nh*crop.height/480)],640,480,name)[0]
            except ValueError:break
            mapped['provenance'][0].update(crop=list(box),scale=3,normalized_crop_bounds=[nx,ny,nw,nh],
                transform='L<=70 retained black, others white; bicubic enlargement')
            if not _same_location(old,mapped):break
            readings.append(mapped)
        if len(readings)!=2 or not _same_location(*readings):continue
        first,second=readings;first['provenance']=old['provenance']+first['provenance']+second['provenance']
        rows[rows.index(old)]=first
        return


def _recover_audience_title_fragments(image,rows,executable,directory,evidence):
    """Join a split audience title only after two complete, identical reads.

    Fragment text supplies a crop anchor, not a corrected tribe or attitude.
    The complete audience question and both alternatives remain source-bound
    by the dialog classifier after this same-pixel recovery.
    """
    if image.size!=(640,480):return
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','close','exit')]
    if len(controls)!=1 or controls[0]['text']!='OK':return
    ok=controls[0]
    if not 312<=ok['center'][0]<=328 or not 302<=ok['center'][1]<=322:return
    headings=sorted((r for r in rows if 150<=r['bounds'][1]<=174
                     and 150<=r['bounds'][0] and r['bounds'][0]+r['bounds'][2]<=490),
                    key=lambda r:r['bounds'][0])
    if len(headings)!=2:return
    first,last=headings
    if (not re.fullmatch(r'[A-Za-z][A-Za-z -]{1,30}',first['text'])
            or not re.fullmatch(r'[A-Za-z][A-Za-z -]{1,45} Emissary',last['text'])
            or abs(first['center'][1]-last['center'][1])>3
            or not -3<=last['bounds'][0]-first['bounds'][0]-first['bounds'][2]<=12):return
    x=min(r['bounds'][0] for r in headings);y=min(r['bounds'][1] for r in headings)
    right=max(r['bounds'][0]+r['bounds'][2] for r in headings)
    bottom=max(r['bounds'][1]+r['bounds'][3] for r in headings)
    anchor=dict(first,text=first['text']+' '+last['text'],bounds=[x,y,right-x,bottom-y],
                center=[round((x+right)/2),round((y+bottom)/2)])
    if abs(anchor['center'][0]-ok['center'][0])>8:return
    pane=sorted((r for r in rows if 150<=r['bounds'][0] and r['bounds'][0]+r['bounds'][2]<=490
                 and bottom<=r['bounds'][1] and r['center'][1]<ok['center'][1]-10),
                key=lambda r:(r['center'][1],r['center'][0]))
    if not 4<=len(pane)<=6 or any(r['confidence']<.8 for r in [*headings,*pane,ok]):return
    label=lambda r:re.sub(r'^[O○●•]\s+','',r['text'])
    if label(pane[-2])!='"Yes. I will grant an audience."':return
    refusal=re.fullmatch(r'"No\. Send (him|her) away\."',label(pane[-1]))
    if refusal is None:return
    body=' '.join(r['text'] for r in pane[:-2])
    if not re.fullmatch(r'An emissary from [A-Za-z][A-Za-z .\x27-]{1,100} of the '
                       r'[A-Za-z][A-Za-z -]{1,40} wishes to speak with you\. Will you receive '
                       +refusal.group(1)+r'\?',body):return
    a=_crop_text(image,anchor,'audience_title_fragments_rgb4',executable,directory,evidence,padding=(3,3),scale=4)
    b=_crop_text(image,anchor,'audience_title_fragments_gray4',executable,directory,evidence,padding=(3,3),scale=4,grayscale=True)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=anchor['text'] or b[0]['text']!=anchor['text']
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(anchor,a[0]) or not _same_location(a[0],b[0])):return
    fresh=a[0];fresh['provenance']=first['provenance']+last['provenance']+a[0]['provenance']+b[0]['provenance']
    fresh['normalization']='two independent complete reads of the same original split audience title pixels'
    indices=sorted((rows.index(first),rows.index(last)))
    rows.pop(indices[1]);rows.pop(indices[0]);rows.insert(indices[0],fresh)


def _recover_audience_radio(image,rows,executable,directory,evidence):
    """Re-read a malformed quoted audience alternative from its own pixels."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text'].endswith(' Emissary') and 130<=r['center'][1]<=200]
    buttons=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','close','exit')]
    if len(headings)!=1 or len(buttons)!=1 or buttons[0]['text']!='OK':return
    heading=headings[0];button=buttons[0]
    if abs(heading['center'][0]-button['center'][0])>8:return
    body=[r for r in rows if heading['center'][1]<r['center'][1]<button['center'][1]
          and abs(r['center'][0]-heading['center'][0])<=160]
    if not any(r['text'].startswith('An emissary from ') for r in body):return
    expected={'"Yes. I will grant an audience."','"No. Send him away."','"No. Send her away."'}
    for index,old in enumerate(rows):
        if old not in body or old['confidence']<.8 or old['bounds'][3]>24:continue
        wanted=None;scale=3
        if old['text'].startswith(('("',')"')) and old['text'][1:] in expected:
            wanted=old['text'][1:]
        elif re.match(r'^[O○●•] "\'',old['text']):
            # Actual011/3418: radio + opening double quote + spurious
            # apostrophe. Only locate pixels; both4x reads must supply the
            # complete exact alternative including its real quotation marks.
            candidate='"'+old['text'][4:]
            if candidate in expected:wanted=candidate;scale=4
        if wanted is None:continue
        a=_crop_text(image,old,f'audience_radio_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
        b=_crop_text(image,old,f'audience_radio_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
        if (len(a)==len(b)==1 and a[0]['text']==b[0]['text']==wanted
                and min(a[0]['confidence'],b[0]['confidence'])>=.8
                and _same_location(a[0],b[0]) and _same_location(old,b[0])):
            if _replace_crop_row(rows,index,a,lambda previous,fresh:True):rows[index]['provenance']+=b[0]['provenance']


def _recover_audience_body(image,rows,executable,directory,evidence):
    """Read the audience question punctuation from two actual pixel crops."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text'].endswith(' Emissary') and 130<=r['center'][1]<=200]
    buttons=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','close','exit')]
    if len(headings)!=1 or len(buttons)!=1 or buttons[0]['text']!='OK':return
    heading=headings[0];button=buttons[0]
    if abs(heading['center'][0]-button['center'][0])>8:return
    label=lambda r:re.sub(r'^[O○●•]\s+','',r['text'])
    choices=[r for r in rows if heading['center'][1]<r['center'][1]<button['center'][1]
             and label(r) in ('"Yes. I will grant an audience."','"No. Send her away."','"No. Send him away."')]
    choices.sort(key=lambda r:r['center'][1])
    if (len(choices)!=2 or label(choices[0])!='"Yes. I will grant an audience."'
            or label(choices[1]) not in ('"No. Send her away."','"No. Send him away."')):return
    gender='her' if label(choices[1])=='"No. Send her away."' else 'him'
    body=[r for r in rows if 150<=r['bounds'][0]<=165 and r['bounds'][0]+r['bounds'][2]<=482
          and heading['center'][1]<r['center'][1]<min(c['bounds'][1] for c in choices)]
    body.sort(key=lambda r:r['center'][1])
    if (len(body)!=3 or not re.fullmatch(r'An emissary from .+ of the',body[0]['text'])
            or not re.fullmatch(r'.+ wishes to speak with you[,.] Will you',body[1]['text'])
            or not re.fullmatch(r'receive [a-z?]{3,5}',body[2]['text'])
            or any(r['confidence']<.8 for r in [heading,*body,*choices,button])):return
    wanted=[body[1]['text'].replace(', Will you','. Will you'),f'receive {gender}?']
    if [r['text'] for r in body[1:]]==wanted:return
    recovered=[]
    for i,(old,text) in enumerate(zip(body[1:],wanted)):
        a=_crop_text(image,old,f'audience_body_{i}_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
        b=_crop_text(image,old,f'audience_body_{i}_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or a[0]['text']!=text
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(a[0],b[0]) or not _same_location(old,b[0])):return
        recovered.append((old,a[0],b[0]))
    for old,a,b in recovered:
        a['provenance']=old['provenance']+a['provenance']+b['provenance']
        rows[rows.index(old)]=a


def _recover_withdrawal_warning(image,rows,executable,directory,evidence):
    """Read two damaged VIOLATOR rows; every treaty term stays source-bound."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['text'].endswith(' Emissary')
            and 305<=r['center'][0]<=335 and 140<=r['center'][1]<=170]
    buttons=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help')]
    if (len(titles)!=1 or len(buttons)!=1 or buttons[0]['text']!='OK'
            or abs(buttons[0]['center'][0]-titles[0]['center'][0])>8
            or not 310<=buttons[0]['center'][1]<=340):return
    panel=[r for r in rows if 190<=r['bounds'][0]<=245
           and titles[0]['center'][1]<r['center'][1]<buttons[0]['center'][1]]
    panel.sort(key=lambda r:r['center'][1])
    if (len(panel)!=6 or panel[0]['text']!='"Your troops have violated the territory of our'
            or not re.fullmatch(r'city of [A-Za-z -]{2,60}\. By the terms of our peace',panel[1]['text'])
            or panel[2]['text'] not in ('treaty, you must withdraw inmediately or face','treaty, you must withdraw immediately or face',
                                      'freaty, you must withdraw immediately or face')
            or panel[3]['text']!='the consequences! Will you comply?"'
            or panel[4]['text'] not in ('O Withdraw troops to nearest city.','Withdraw troops to nearest city.')
            or panel[5]['text'] not in ('"No! We renounce this worthless treaty!"','• "No! We renounce this worthless treaty!"',
                                      'O "No! We renounce this worthless treaty!"')
            or any(r['confidence']<.8 for r in [*titles,*panel,*buttons])):return
    recovered=[]
    for i,wanted in ((2,'treaty, you must withdraw immediately or face'),(4,'Withdraw troops to nearest city.'),
                     (5,'"No! We renounce this worthless treaty!"')):
        old=panel[i]
        if old['text']==wanted:continue
        a=_crop_text(image,old,f'withdrawal_{i}_rgb3',executable,directory,evidence,padding=(4,4),scale=3)
        b=_crop_text(image,old,f'withdrawal_{i}_gray3',executable,directory,evidence,padding=(4,4),scale=3,grayscale=True)
        if (i==4 and len(a)==len(b)==1 and a[0]['text']==b[0]['text']=='Withdraw troopsto nearest city.'):
            a=_crop_text(image,old,'withdrawal_4_wide_rgb3',executable,directory,evidence,padding=(6,3),scale=3)
            b=_crop_text(image,old,'withdrawal_4_wide_gray3',executable,directory,evidence,padding=(6,3),scale=3,grayscale=True)
        prior=[]
        if (i==5 and old['text']=='O '+wanted and len(a)==len(b)==1
                and a[0]['text']==b[0]['text']=='• '+wanted
                and min(a[0]['confidence'],b[0]['confidence'])>=.8
                and _same_location(old,a[0]) and _same_location(a[0],b[0])):
            prior=a[0]['provenance']+b[0]['provenance']
            a=_crop_text(image,old,'withdrawal_5_rgb2',executable,directory,evidence,padding=(4,4),scale=2)
            b=_crop_text(image,old,'withdrawal_5_gray2',executable,directory,evidence,padding=(4,4),scale=2,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=wanted or b[0]['text']!=wanted
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        a[0]['provenance']=prior+a[0]['provenance']
        recovered.append((old,a[0],b[0]))
    for old,a,b in recovered:
        a['provenance']=old['provenance']+a['provenance']+b['provenance']
        rows[rows.index(old)]=a


def _recover_treaty_warning(image,rows,executable,directory,evidence):
    """Read spacing or final punctuation within the complete two-choice warning."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['text'] in ('Foreign Minister','Foreign Mfinister')
            and 305<=r['center'][0]<=335 and 145<=r['center'][1]<=185]
    buttons=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help')]
    if (len(titles)!=1 or len(buttons)!=1 or buttons[0]['text']!='OK'
            or abs(buttons[0]['center'][0]-titles[0]['center'][0])>8
            or not 300<=buttons[0]['center'][1]<=330):return
    panel=[r for r in rows if 190<=r['bounds'][0]<=245
           and titles[0]['center'][1]<r['center'][1]<buttons[0]['center'][1]]
    panel.sort(key=lambda r:r['center'][1])
    if (len(panel)!=5 or panel[0]['text'] not in ('We have signed a peace treaty withthe','We have signed a peace treaty with the')
            or not re.fullmatch(r'[A-Za-z -]{2,60}! Our reputation will be damaged if we',panel[1]['text'])
            or panel[2]['text'] not in ('break it!','breakit!') or panel[3]['text']!='Cancel action.'
            or panel[4]['text'] not in ('Break treaty.','Break treaty')
            or any(r['confidence']<.8 for r in [*titles,*panel,*buttons])):return
    for old,wanted,scale in ((panel[0],'We have signed a peace treaty with the',3),
                             (panel[2],'break it!',3),
                             (panel[4],'Break treaty.',2)):
        if old['text']==wanted:continue
        a=_crop_text(image,old,f'treaty_warning_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
        b=_crop_text(image,old,f'treaty_warning_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
        if (len(a)==len(b)==1 and a[0]['text']==b[0]['text']==wanted
                and min(a[0]['confidence'],b[0]['confidence'])>=.8
                and _same_location(old,a[0]) and _same_location(a[0],b[0])):
            index=rows.index(old)
            if _replace_crop_row(rows,index,a,lambda previous,fresh:True):rows[index]['provenance']+=b[0]['provenance']


def _recover_treaty_reminder(image,rows,executable,directory,evidence):
    """Read the printed treaty word without changing a nation or withdrawal term."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['text'].casefold() in ('foreign minister','foreign ifinister')
            and r['confidence']>=.8 and 300<=r['center'][0]<=340 and 100<=r['center'][1]<=240]
    buttons=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help')]
    if len(titles)!=1 or len(buttons)!=1 or buttons[0]['text']!='OK':return
    if abs(titles[0]['center'][0]-buttons[0]['center'][0])>8:return
    body=[r for r in rows if 190<=r['bounds'][0]<=204 and titles[0]['center'][1]<r['center'][1]<buttons[0]['center'][1]-12]
    body.sort(key=lambda r:r['center'][1])
    if (len(body)!=5 or body[0]['text']!='Remember, Sire, that by the terms of our'
            or body[2]['text']!='we must immediately withdraw all of our'
            or body[3]['text']!='military units from the vicinity (two square'
            or not re.fullmatch(r'radius\) of [A-Za-z -]{2,60} and all other [A-Za-z -]{2,60} cities\.',body[4]['text'])):return
    old=body[1];match=re.fullmatch(r'recently-signed peace freaty with the ([A-Za-z -]{2,60}),',old['text'])
    if not match:return
    wanted='recently-signed peace treaty with the '+match[1]+','
    a=_crop_text(image,old,'treaty_reminder_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
    b=_crop_text(image,old,'treaty_reminder_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
    if (len(a)==len(b)==1 and a[0]['text']==b[0]['text']==wanted
            and min(a[0]['confidence'],b[0]['confidence'])>=.8
            and _same_location(old,a[0]) and _same_location(a[0],b[0])):
        index=rows.index(old)
        if _replace_crop_row(rows,index,a,lambda previous,fresh:True):rows[index]['provenance']+=b[0]['provenance']


def _recover_intruder_notice(image,rows,executable,directory,evidence):
    """Read one clipped source word in a complete native treaty warning."""
    if image.size!=(640,480):return
    headings=[r for r in rows if len(r['text'].split())>=3
              and _near_text(r['text'].split()[-1],'Emissary',2) and r['confidence']>=.8
              and 280<=r['center'][0]<=350 and 150<=r['center'][1]<=210]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    title,ok=headings[0],controls[0]
    if abs(title['center'][0]-ok['center'][0])>8 or not 90<=ok['center'][1]-title['center'][1]<=130:return
    body=sorted((r for r in rows if 190<=r['bounds'][0]<=210
                 and title['center'][1]+12<r['center'][1]<ok['center'][1]-12),key=lambda r:r['center'][1])
    if (len(body)!=4 or body[0]['text']!='"Your troops have violated the territory of ou'
            or not re.fullmatch(r'city of [A-Za-z -]{2,60}\. By the terms of our peace',body[1]['text'])
            or body[2]['text']!='treaty, you must withdraw immediately or face'
            or body[3]['text']!='the consequences!"'):return
    recovered_title=None
    if not title['text'].endswith(' Emissary'):
        wanted_title=title['text'].rsplit(' ',1)[0]+' Emissary'
        a=_crop_text(image,title,'intruder_title_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
        b=_crop_text(image,title,'intruder_title_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or a[0]['text']!=wanted_title
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(title,a[0]) or not _same_location(a[0],b[0])):return
        recovered_title=(a,b)
    old=body[0];wanted='"Your troops have violated the territory of our'
    a=_crop_text(image,old,'intruder_first_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
    b=_crop_text(image,old,'intruder_first_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
    if (len(a)==len(b)==1 and a[0]['text']==b[0]['text']==wanted
            and min(a[0]['confidence'],b[0]['confidence'])>=.8
            and _same_location(old,a[0]) and _same_location(a[0],b[0])):
        index=rows.index(old)
        if _replace_crop_row(rows,index,a,lambda previous,fresh:True):rows[index]['provenance']+=b[0]['provenance']
        if recovered_title:
            a,b=recovered_title;index=rows.index(title)
            if _replace_crop_row(rows,index,a,lambda previous,fresh:True):rows[index]['provenance']+=b[0]['provenance']


def _recover_tech_demand_title(image,rows,executable,directory,evidence):
    """Read a demand's title without changing its complete technology terms."""
    if image.size!=(640,480):return
    heads=[r for r in rows if r['confidence']>=.8 and 290<=r['bounds'][1]<=330
           and 457<=r['center'][0]<=481 and len(r['text'].split())==3
           and _near_text(r['text'].split()[-1].casefold(),'emissary',2)]
    buttons=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(heads)!=1 or len(buttons)!=1 or buttons[0]['text']!='OK':return
    old=heads[0];words=old['text'].split()
    if old['text'].endswith(' Emissary') or not 449<=buttons[0]['center'][1]<=466:return
    if abs(old['center'][0]-buttons[0]['center'][0])>8:return
    panel=sorted([r for r in rows if 300<=r['bounds'][0]<=350
                  and old['center'][1]<r['center'][1]<buttons[0]['center'][1]-12],key=lambda r:r['center'][1])
    if len(panel)!=5 or any(r['confidence']<.8 for r in panel):return
    demand=re.fullmatch(r'"We know you have knowledge of ([A-Za-z ]{2,50})\.',panel[0]['text'])
    if (not demand or panel[1]['text']!='Give us the secret at once, or face the'
            or panel[2]['text']!='consequences!"'
            or not re.fullmatch(r'[O0©○●•)(\s]{0,5}"Consequences, schmonsequences!"',panel[3]['text'])
            or panel[4]['text']!='Give secret of '+demand[1]+'.'):return
    readings=[]
    for scale in (2,3):
        a=_crop_text(image,old,f'tech_demand_title_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
        b=_crop_text(image,old,f'tech_demand_title_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        fresh=a[0]['text'].split()
        if (len(fresh)!=3 or fresh[2]!='Emissary' or not re.fullmatch('[A-Za-z]{2,25}',fresh[1])
                or not _near_text(words[0].casefold(),fresh[0].casefold(),2)
                or not _near_text(words[1].casefold(),fresh[1].casefold(),2)):return
        readings.append((a[0],b[0]))
    if readings[0][0]['text']!=readings[1][0]['text']:return
    option=panel[3];choice='"Consequences, schmonsequences!"';option_reads=None
    if option['text']!=choice:
        a=_crop_text(image,option,'tech_demand_radio_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
        b=_crop_text(image,option,'tech_demand_radio_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or a[0]['text']!=choice
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(option,a[0]) or not _same_location(a[0],b[0])):return
        option_reads=(a[0],b[0])
    fresh=dict(readings[0][0]);fresh['provenance']=old['provenance']+[
        p for pair in readings for row in pair for p in row['provenance']]
    rows[rows.index(old)]=fresh
    if option_reads:
        a,b=option_reads;a['provenance']=option['provenance']+a['provenance']+b['provenance']
        rows[rows.index(option)]=a


def _recover_herald_title(image,rows,executable,directory,evidence):
    """Read a damaged Emissary suffix twice without changing nation or attitude."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r.get('confidence',0)>=.8 and 200<=r['bounds'][1]<=420
              and 420<=r['center'][0]<=485 and len(r['text'].split())>=3
              and _near_text(r['text'].split()[-1].casefold(),'emissary',2)]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    old=headings[0];ok=controls[0]
    if old['text'].endswith(' Emissary') or not 449<=ok['center'][1]<=466 or abs(old['center'][0]-ok['center'][0])>8:return
    wanted=old['text'].rsplit(' ',1)[0]+' Emissary'
    framings=[(2,(6,4))]
    if any(r['text']=='"We have prepared a permanent peace treaty'
           and old['center'][1]<r['center'][1]<old['center'][1]+40 for r in rows):
        framings.append((3,(6,3)))
    for scale,padding in framings:
        a=_crop_text(image,old,f'herald_title_rgb{scale}',executable,directory,evidence,padding=padding,scale=scale)
        b=_crop_text(image,old,f'herald_title_gray{scale}',executable,directory,evidence,padding=padding,scale=scale,grayscale=True)
        if (len(a)==len(b)==1 and a[0]['text']==b[0]['text']==wanted
                and min(a[0]['confidence'],b[0]['confidence'])>=.8
                and _same_location(old,a[0]) and _same_location(a[0],b[0])):
            index=rows.index(old)
            if _replace_crop_row(rows,index,a,lambda previous,fresh:True):rows[index]['provenance']+=b[0]['provenance']
            return


def _recover_gape_title(image,rows,executable,directory,evidence):
    """Two-scale heading reads above the complete no-scribes announcement."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['confidence']>=.8 and 340<=r['center'][1]<=353
              and 458<=r['center'][0]<=480 and len(r['text'].split())==3
              and _near_text(r['text'].split()[-1],'Emissary',2)]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    old,ok=headings[0],controls[0]
    if old['text'].endswith(' Emissary') or abs(old['center'][0]-ok['center'][0])>8 or not 450<=ok['center'][1]<=467:return
    body=sorted([r for r in rows if old['center'][1]<r['center'][1]<ok['center'][1]
                 and 302<=r['bounds'][0]<=316],key=lambda r:r['center'][1])
    if (len(body)!=4 or any(r['confidence']<.8 for r in body)
            or body[0]['text']!='"You are invited to gape with awe and'
            or not re.fullmatch(r'amazement as the [A-Za-z][A-Za-z -]{1,40} demonstrate the',body[1]['text'])
            or not re.fullmatch(r'wonders of [A-Za-z][A-Za-z -]{1,60}\. Absolutely no scribes',body[2]['text'])
            or body[3]['text']!='will be allowed."'
            or any(not 17<=b['center'][1]-a['center'][1]<=24 for a,b in zip(body,body[1:]))):return
    readings=[];previous=old['text'].split()
    for scale in (2,4):
        a=_crop_text(image,old,f'gape_title_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
        b=_crop_text(image,old,f'gape_title_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        fresh=a[0]['text'].split()
        if (len(fresh)!=3 or fresh[0]!=previous[0] or fresh[-1]!='Emissary'
                or not re.fullmatch('[A-Za-z]{2,40}',fresh[1])
                or not _near_text(previous[1],fresh[1],1)):return
        readings.extend((a[0],b[0]))
    if len({r['text'] for r in readings})!=1:return
    chosen=readings[0];chosen['provenance']=[p for r in readings for p in r['provenance']]
    _replace_crop_row(rows,rows.index(old),[chosen],lambda before,after:True)


def _recover_exchange_title(image,rows,executable,directory,evidence):
    """Read a damaged trade heading at two scales, preserving observed words."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['confidence']>=.8 and 200<=r['bounds'][1]<=350
              and 457<=r['center'][0]<=481 and len(r['text'].split())==3
              and not r['text'].endswith(' Emissary')
              and _near_text(r['text'].split()[-1].casefold(),'emissary',2)]
    buttons=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(buttons)!=1 or buttons[0]['text']!='OK':return
    old=headings[0]
    if not 449<=buttons[0]['center'][1]<=466 or abs(old['center'][0]-buttons[0]['center'][0])>8:return
    if not any(r['text'].startswith('"We note that your primitive civilization')
               and 300<=r['bounds'][0]<=316 and old['center'][1]<r['center'][1]<old['center'][1]+40 for r in rows):return
    words=old['text'].split();readings=[]
    for scale in (3,4):
        a=_crop_text(image,old,f'exchange_title_rgb{scale}',executable,directory,evidence,padding=(6,3),scale=scale)
        b=_crop_text(image,old,f'exchange_title_gray{scale}',executable,directory,evidence,padding=(6,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        fresh=a[0]['text'].split()
        if (len(fresh)!=3 or fresh[0]!=words[0] or fresh[2]!='Emissary'
                or not re.fullmatch('[A-Za-z]{2,25}',fresh[1])
                or not _near_text(words[1].casefold(),fresh[1].casefold(),2)):return
        readings.append((a[0],b[0]))
    if readings[0][0]['text']!=readings[1][0]['text']:return
    fresh=dict(readings[0][0]);fresh['provenance']=old['provenance']+[
        p for pair in readings for row in pair for p in row['provenance']]
    rows[rows.index(old)]=fresh


def _recover_herald_panel(image,rows,executable,directory,evidence):
    """Read the original fullscreen herald panel; never authorize its dismissal.

    Two panel reads must agree. Its button additionally needs two ASCII OK
    reads from observed pixel bounds. The classifier still verifies GAME.TXT.
    """
    if image.size!=(640,480):return
    headings=[r for r in rows if 330<=r['bounds'][1]<=420 and 427<=r['center'][0]<=481
              and r['confidence']>=.5 and r['text'].split()
              and _near_text(r['text'].split()[-1].casefold(),'emissary',2)]
    if len(headings)!=1:return
    # The original longer treaty notice is wider and centers its title/OK
    # near437; the narrow greeting centers near469. Both right edges are640.
    heading=headings[0]
    left=298 if heading['center'][0]>=457 else 2*heading['center'][0]-642
    box=(left,max(0,heading['bounds'][1]-8),640,480)
    if not 210<=left<=298 or box[3]-box[1]>160:return
    readings=[]
    for gray in (False,True):
        name='herald_panel_gray_3x' if gray else 'herald_panel_3x'
        crop=image.crop(box)
        if gray:crop=crop.convert('L')
        target=Path(directory)/(name+'.png')
        crop.resize((crop.width*3,crop.height*3),Image.Resampling.BICUBIC).save(target)
        evidence['passes'].append(name)
        raw=_prepare_rows(_run_ocr(executable,target),crop.width,crop.height,name)
        mapped=[]
        for local in raw:
            x,y,w,h=local['provenance'][0]['normalized_bounds']
            row=_prepare_rows([dict(text=local['text'],confidence=local['confidence'],
                x=(box[0]+x*crop.width)/640,y=(box[1]+y*crop.height)/480,
                width=w*crop.width/640,height=h*crop.height/480)],640,480,name)[0]
            row['provenance'][0].update(crop=list(box),scale=3,normalized_crop_bounds=[x,y,w,h],
                transform=('grayscale; ' if gray else '')+'bicubic enlargement')
            mapped.append(row)
        readings.append(sorted(mapped,key=lambda r:r['center'][1]))
    first,second=readings
    if not 3<=len(first)==len(second)<=8:return
    if any(a['text']!=b['text'] or not _same_location(a,b) for a,b in zip(first,second)):return
    if not first[0]['text'].casefold().endswith(' emissary'):return
    if any(r['confidence']<.8 for group in readings for r in group[:-1]):return
    if not all(_ok_lookalike(group[-1]['text']) and group[-1]['center'][1]>440 for group in readings):
        # Full-panel OCR can omit the separately observed wide OK button. Its
        # original bounds are an anchor only; two fresh button crops below
        # must independently read ASCII OK before any replacement occurs.
        anchors=[r for r in rows if r['text']=='OK' and r['confidence']>=.8
                 and 448<=r['center'][1]<=466 and abs(r['center'][0]-heading['center'][0])<=6]
        if (len(anchors)!=1 or any(r['confidence']<.8 for group in readings for r in group)
                or any(r['bounds'][1]+r['bounds'][3]>anchors[0]['bounds'][1] for group in readings for r in group)):
            return
        first.append(anchors[0]);second.append(anchors[0])
    buttons=[]
    for gray in (False,True):
        name='herald_ok_gray_3x' if gray else 'herald_ok_3x'
        candidates=_crop_text(image,first[-1],name,executable,directory,evidence,padding=(2,5),grayscale=gray)
        if (len(candidates)!=1 or candidates[0]['text']!='OK' or candidates[0]['confidence']<.8
                or not _same_location(first[-1],candidates[0])):return
        buttons.append(candidates[0])
    replacements=[]
    for a,b in zip(first[:-1],second[:-1]):
        prior=[r for r in rows if _same_location(r,a)]
        a['provenance']=[p for r in prior for p in r['provenance']]+a['provenance']+b['provenance']
        replacements.append(a)
    button=buttons[0];button['provenance']=first[-1]['provenance']+second[-1]['provenance']+button['provenance']+buttons[1]['provenance']
    replacements.append(button)
    rows[:]=[r for r in rows if not (r['bounds'][0]>=box[0] and r['bounds'][1]>=box[1])]+replacements


def _recover_cease_proposal(image,rows,executable,directory,evidence):
    """Read punctuation in the complete original cease-fire proposal/options."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text'].endswith(' Emissary') and r['confidence']>=.8
              and 420<=r['center'][0]<=445 and 320<=r['center'][1]<=340]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    heading,ok=headings[0],controls[0]
    if not 450<=ok['center'][1]<=468 or abs(heading['center'][0]-ok['center'][0])>8:return
    panel=sorted([r for r in rows if 298<=r['bounds'][0]<=345
                  and heading['center'][1]<r['center'][1]<ok['center'][1]-12],key=lambda r:r['center'][1])
    if len(panel)!=4 or any(r['confidence']<.8 or r['bounds'][3]>24 for r in panel):return
    first=re.fullmatch(r'[*"]The ([A-Za-z -]{2,60}) people grow weary of this endless',panel[0]['text'])
    accepted='"We accept--let us end this terrible war."'
    refusal='"Cowards! We shall fight to the bitter end!"'
    if (not first or panel[1]['text'] not in ('war. We suggest a cease fire.','war. We suggest a cease fire."')
            or panel[2]['text'] not in (accepted,accepted.replace('--','-'))
            or panel[3]['text'] not in (refusal,'• '+refusal,'O '+refusal)):return
    recovered=[]
    for old,name,scale,padding,wanted in (
            (panel[0],'intro',2,(3,3),'"The '+first[1]+' people grow weary of this endless'),
            (panel[1],'tail',3,(8,3),'war. We suggest a cease fire."'),
            (panel[2],'accept',3,(3,3),accepted)):
        if old['text']==wanted:continue
        a=_crop_text(image,old,f'cease_proposal_{name}_rgb{scale}',executable,directory,evidence,padding=padding,scale=scale)
        b=_crop_text(image,old,f'cease_proposal_{name}_gray{scale}',executable,directory,evidence,padding=padding,scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or a[0]['text']!=wanted
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
        recovered.append((old,a[0],b[0]))
    for old,a,b in recovered:
        a['provenance']=old['provenance']+a['provenance']+b['provenance']
        rows[rows.index(old)]=a


def _recover_herald_options(image,rows,executable,directory,evidence):
    """Recover quoted radio labels without changing any observed words.

    Actual paired crops supply punctuation and label geometry. The complete
    original resource body and every option still require classifier matching.
    """
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text'].endswith(' Emissary')
              and 200<=r['bounds'][1]<=420 and 420<=r['center'][0]<=485]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    heading=headings[0];ok=controls[0]
    if abs(heading['center'][0]-ok['center'][0])>8:return
    completion_context=any(r['text']=='You respond: "We..."' for r in rows)
    candidates=[r for r in rows if (re.match(r'^[O0©○●•)(\s]{1,5}"',r['text']) or r['text'].startswith('"\'')
                or (r['text'].startswith('"') and not r['text'].endswith('"'))
                or (completion_context and r['text']=='"Consider this discussion complete!"'))
                and r['confidence']>=.8
                and 290<=r['bounds'][0]<=350 and 100<=r['bounds'][2]<=350 and r['bounds'][3]<=24
                and heading['center'][1]+35<r['center'][1]<ok['center'][1]-12]
    if not 1<=len(candidates)<=9:return
    words=lambda text:re.findall(r'[A-Za-z0-9]+',text)
    for old in candidates:
        observed_words=words(old['text'][old['text'].index('"'):])
        completion_punctuation=completion_context and observed_words==['Consider','this','discussion','complete']
        # Some native OCR boxes stop before the closing quote at the right
        # frame. A wider horizontal crop still needs two complete identical
        # readings and every original word/number; keep the vertical crop low
        # enough to avoid absorbing the next radio row.
        variants=((4,6,6),(3,18,3)) if not old['text'].endswith('"') else ((3,3,3),(2,3,3),(3,6,6))
        if completion_punctuation:variants=(*variants,(3,18,3))
        for scale,pad,vertical in variants:
            name=f'herald_option_{rows.index(old)}_{scale}x_pad{pad}'+(f'x{vertical}' if pad!=vertical else '')
            try:
                a=_crop_text(image,old,name+'_rgb',executable,directory,evidence,padding=(pad,vertical),scale=scale)
                b=_crop_text(image,old,name+'_gray',executable,directory,evidence,padding=(pad,vertical),scale=scale,grayscale=True)
            except ValueError:
                evidence.setdefault('fallback_errors',[]).append({'pass_name':name,'error':'ValueError'})
                continue
            if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                    or min(a[0]['confidence'],b[0]['confidence'])<.8
                    or not re.fullmatch(r'"[A-Za-z0-9][^"\n]*"',a[0]['text'])
                    or words(a[0]['text'])!=observed_words
                    or (completion_punctuation and a[0]['text']!='"Consider this discussion complete."')
                    or not _same_location(a[0],b[0]) or not _same_location(old,b[0])):continue
            index=rows.index(old)
            if _replace_crop_row(rows,index,a,lambda previous,fresh:True):rows[index]['provenance']+=b[0]['provenance']
            break


def _recover_treaty_missing_ok(image,rows,executable,directory,evidence):
    """Locate an omitted treaty button by two actual bounded pixel reads."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text'].endswith(' Emissary') and r['confidence']>=.8
              and 330<=r['bounds'][1]<=350 and 430<=r['center'][0]<=445]
    if len(headings)!=1 or any(r['text'] in ('OK','Cancel','Yes','No','Help','Goal') for r in rows):return
    heading=headings[0]
    body=[r for r in rows if 302<=r['bounds'][0]<=320 and 355<=r['center'][1]<=440]
    body.sort(key=lambda r:r['center'][1])
    if (len(body)!=4 or any(r['confidence']<.8 for r in body)
            or body[0]['text']!='"We affirm this treaty of eternal friendship and'
            or not re.fullmatch(r'goodwill [bh]etween the people of the [A-Za-z -]{2,40} and',body[1]['text'])
            or not re.fullmatch(r'[A-Za-z -]{2,40} civilizations\. We shall withdraw ou[r]?',body[2]['text'])
            or not _near_text(body[3]['text'],'forces from your territory at once."',2)):return
    anchor={'bounds':[heading['center'][0]-21,448,44,24]};found=[]
    for scale in (3,4):
        values=_crop_text(image,anchor,f'treaty_missing_ok_{scale}x',executable,directory,evidence,padding=(0,0),scale=scale)
        if (len(values)!=1 or values[0]['text']!='OK' or values[0]['confidence']<.8
                or abs(values[0]['center'][0]-heading['center'][0])>4
                or not 454<=values[0]['center'][1]<=464 or values[0]['bounds'][2]>32
                or values[0]['bounds'][3]>18):return
        found.append(values[0])
    if not _same_location(*found):return
    found[0]['provenance']+=found[1]['provenance']
    rows.append(found[0])


def _recover_treaty_closing_rows(image,rows,executable,directory,evidence):
    """Read the printed withdrawal sentence of a source-bound treaty notice."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text'].endswith(' Emissary') and 330<=r['center'][1]<=380]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    heading=headings[0];ok=controls[0]
    body=[r for r in rows if heading['center'][1]<r['center'][1]<ok['center'][1]-12 and 302<=r['bounds'][0]<=320]
    if (len(body)!=4 or body[0]['text']!='"We affirm this treaty of eternal friendship and'
            or not re.match(r'goodwill [bh]etween the people of the ',body[1]['text'])
            or not body[1]['text'].endswith(' and')):return
    match=re.fullmatch(r'([A-Za-z -]+ civilizations\. We shall withdraw) ou[r]?',body[2]['text'])
    last='forces from your territory at once."'
    if match is None or not _near_text(body[3]['text'],last,2):return
    for old,wanted in ((body[1],re.sub(r'^goodwill hetween ','goodwill between ',body[1]['text'])),
                       (body[2],match[1]+' our'),(body[3],last)):
        if old['text']==wanted:continue
        name='treaty_closing_'+str(rows.index(old))
        a=_crop_text(image,old,name+'_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
        b=_crop_text(image,old,name+'_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=wanted or b[0]['text']!=wanted
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):continue
        index=rows.index(old)
        if _replace_crop_row(rows,index,a,lambda previous,fresh:True):rows[index]['provenance']+=b[0]['provenance']


    recover_treaty_between(image,rows,evidence)


def _recover_greeting_body(image,rows,executable,directory,evidence):
    """Recover greeting prose and its printed closing punctuation, not terms."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text'].endswith(' Emissary') and 370<=r['center'][1]<=400]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    heading=headings[0];ok=controls[0]
    body=[r for r in rows if heading['center'][1]<r['center'][1]<ok['center'][1]-12
          and 302<=r['bounds'][0]<=316]
    prefix='"I bear a message from our most wise'
    # GREETINGS00 has a variable leader name in the first line. It is already
    # exact here; preserve every observed letter and recover only the tail.
    if body and re.fullmatch(r'"Greetings from the most exalted [A-Za-z][A-Za-z \x27-]{1,60}:',body[0]['text']):
        prefix=body[0]['text']
    if body and re.fullmatch(r'"I bring tidings from [A-Za-z][A-Za-z \x27-]{1,60}, ruler and',body[0]['text']):
        prefix=body[0]['text']
    if body and re.fullmatch(r'"I speak for (?:he|she) who makes mortals tremble:',body[0]['text']):
        prefix=body[0]['text']
    if (len(body)!=2 or abs(heading['center'][0]-ok['center'][0])>8
            or not 16<=body[1]['center'][1]-body[0]['center'][1]<=26
            or not _near_text(body[0]['text'],prefix,3)
            or not re.fullmatch(r'[A-Za-z][A-Za-z :.-]{2,90} of the [A-Za-z .\"]{2,60}',body[1]['text'])):return
    first,tail=body
    if first['text']!=prefix:
        a=_crop_text(image,first,'greeting_intro_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
        b=_crop_text(image,first,'greeting_intro_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=prefix or b[0]['text']!=prefix
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(first,a[0]) or not _same_location(a[0],b[0])):return
        index=rows.index(first)
        if not _replace_crop_row(rows,index,a,lambda old,fresh:True):return
        rows[index]['provenance']+=b[0]['provenance']
    if tail['text'].endswith('..."'):return
    x,y,w,h=tail['bounds']
    scale=2 if prefix.startswith('"I bring tidings from ') else 3
    words=lambda text:re.findall(r'[A-Za-z]+',text)
    expected_words=words(tail['text']);leader_readings=[]
    def corroborate_leader(text):
        nonlocal expected_words
        incoming=words(text)
        if incoming==expected_words:return True
        # GREETINGS03 names a leader in one variable word. A measured glyph
        # disagreement needs separate RGB/gray reads before both full-tail
        # black-mask reads may establish the complete printed quotation.
        if (leader_readings or not prefix.startswith('"I speak for ')
                or len(incoming)!=5 or len(expected_words)!=5
                or incoming[2:4]!=['of','the']
                or any(incoming[i]!=expected_words[i] for i in (0,2,3,4))
                or not _near_text(incoming[1],expected_words[1],1)):return False
        a=_crop_text(image,tail,'greeting_leader_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
        b=_crop_text(image,tail,'greeting_leader_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text'] or words(a[0]['text'])!=incoming
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(tail,a[0]) or not _same_location(a[0],b[0])):return False
        leader_readings.extend((a[0],b[0]));expected_words=incoming
        return True
    def read_pair(scale):
        readings=[]
        for pad,right in ((3,37),(3,41)):
            box=(x-pad,y-pad,min(640,x+w+right),min(480,y+h+pad));crop=image.crop(box)
            name=f'greeting_tail_black{scale}_right'+str(right);target=Path(directory)/(name+'.png')
            crop.convert('L').point(lambda value:255 if value>70 else 0).resize(
                (crop.width*scale,crop.height*scale),Image.Resampling.BICUBIC).save(target)
            evidence['passes'].append(name);raw=_run_ocr(executable,target)
            if (len(raw)!=1 or raw[0]['confidence']<.8 or not raw[0]['text'].endswith('..."')
                    or not corroborate_leader(raw[0]['text'])):return None
            local=_prepare_rows(raw,crop.width,crop.height,name)[0]
            nx,ny,nw,nh=local['provenance'][0]['normalized_bounds']
            mapped=_prepare_rows([dict(text=local['text'],confidence=local['confidence'],
                x=(box[0]+nx*crop.width)/640,y=(box[1]+ny*crop.height)/480,
                width=nw*crop.width/640,height=nh*crop.height/480)],640,480,name)[0]
            mapped['provenance'][0].update(crop=list(box),scale=scale,normalized_crop_bounds=[nx,ny,nw,nh],
                transform='L<=70 retained black, others white; bicubic enlargement')
            if not _same_location(tail,mapped):return None
            readings.append(mapped)
        return readings
    readings=read_pair(scale)
    if readings is None:return
    a,b=readings
    # Spacing disagreement around fully observed punctuation permits one
    # alternate scale. It does not supply text: two fresh complete reads must
    # agree exactly, preserve every word, and retain their actual geometry.
    if (scale==3 and a['text']!=b['text'] and _same_location(a,b)
            and re.sub(r'\s+','',a['text'])==re.sub(r'\s+','',b['text'])):
        alternate=read_pair(2)
        if alternate is None:return
        readings+=alternate;a,b=alternate
    if a['text']!=b['text'] or not _same_location(a,b):return
    a['provenance']=tail['provenance']+[p for r in leader_readings+readings for p in r['provenance']]
    rows[rows.index(tail)]=a



def _recover_crusade_title(image,rows,executable,directory,evidence):
    """Read a damaged heading above a complete observed crusade proposal."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['confidence']>=.8 and 307<=r['center'][1]<=320
              and 425<=r['center'][0]<=445 and len(r['text'].split())==3
              and _near_text(r['text'].split()[-1],'Emissary',1)]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    old,ok=headings[0],controls[0]
    if old['text'].endswith(' Emissary') or abs(old['center'][0]-ok['center'][0])>8 or not 452<=ok['center'][1]<=469:return
    panel=sorted([r for r in rows if old['center'][1]<r['center'][1]<ok['center'][1]
                  and 300<=r['bounds'][0]<635],key=lambda r:r['center'][1])
    if len(panel)!=5 or any(r['confidence']<.8 for r in panel):return
    first,second,tail,no,yes=panel
    target=re.fullmatch(r'world of the evil ([A-Za-z][A-Za-z -]{1,45})\. We will sign an',second['text'])
    if (not target or first['text']!='"We invite you to join our crusade to rid the'
            or tail['text']!='alliance for the duration of the hostilities."'
            or no['text']!='"No, not interested."'
            or yes['text'] not in (f'Yes, declare war on {target[1]}.',f'• Yes, declare war on {target[1]}.')):return
    a=_crop_text(image,old,'crusade_title_rgb2',executable,directory,evidence,padding=(3,3),scale=2)
    b=_crop_text(image,old,'crusade_title_gray2',executable,directory,evidence,padding=(3,3),scale=2,grayscale=True)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
    previous=old['text'].split();fresh=a[0]['text'].split()
    if (len(fresh)!=3 or fresh[-1]!='Emissary' or not all(re.fullmatch('[A-Za-z]{2,30}',w)for w in fresh)
            or any(not _near_text(x,y,1)for x,y in zip(previous,fresh))):return
    choice_readings=None
    if yes['text'].startswith('• '):
        ca=_crop_text(image,yes,'crusade_choice_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
        cb=_crop_text(image,yes,'crusade_choice_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
        if (len(ca)!=1 or len(cb)!=1 or ca[0]['text']!=cb[0]['text'] or ca[0]['text']!=yes['text'][2:]
                or min(ca[0]['confidence'],cb[0]['confidence'])<.8
                or not _same_location(yes,ca[0]) or not _same_location(ca[0],cb[0])):return
        choice_readings=(ca[0],cb[0])
    if _replace_crop_row(rows,rows.index(old),a,lambda before,after:True):a[0]['provenance']+=b[0]['provenance']
    if choice_readings:
        ca,cb=choice_readings;ca['provenance']=yes['provenance']+ca['provenance']+cb['provenance']
        rows[rows.index(yes)]=ca


def _recover_golden_age_city_line(image,rows,executable,directory,evidence):
    """Read the native city/exclamation row of a complete Golden Age notice."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text']=='Golden Age of Philosophy']
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    title,ok=headings[0],controls[0]
    if (not 174<=title['bounds'][1]<=180 or not 290<=ok['bounds'][1]<=295
            or abs(title['center'][0]-ok['center'][0])>5):return
    panel=sorted([r for r in rows if title['center'][1]<r['center'][1]<ok['center'][1]
                  and 185<=r['bounds'][0]<510],key=lambda r:r['center'][1])
    if len(panel)!=4 or any(r['confidence']<.8 for r in panel):return
    first,city,third,last=panel
    if ([r['text'] for r in (first,third,last)]!=[
            'The Golden Age of Philosophy begins in the',
            'articulate scientific, moral, and metaphysical',
            'systems which endure for centuries to come.']
            or any(not 196<=r['bounds'][0]<=205 for r in panel)
            or any(not 17<=b['center'][1]-a['center'][1]<=24 for a,b in zip(panel,panel[1:]))):return
    pattern=r'([A-Za-z][A-Za-z -]{1,40}) city of ([A-Za-z][A-Za-z -]{1,50})! Great \1 thinkers'
    old=re.fullmatch(pattern.replace('! Great',' Great'),city['text'])
    if not old:return
    for scale in (3,2):
        a=_crop_text(image,city,f'golden_age_city_rgb{scale}',executable,directory,evidence,padding=(6,3),scale=scale)
        b=_crop_text(image,city,f'golden_age_city_gray{scale}',executable,directory,evidence,padding=(6,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(city,a[0]) or not _same_location(a[0],b[0])):return
        if scale==3 and a[0]['text']==city['text']:continue
        fresh=re.fullmatch(pattern,a[0]['text'])
        if not fresh or fresh[1]!=old[1] or not _near_text(old[2],fresh[2],2):return
        index=rows.index(city)
        if _replace_crop_row(rows,index,a,lambda previous,new:True):rows[index]['provenance']+=b[0]['provenance']
        return


def _recover_crusade_tail(image,rows,executable,directory,evidence):
    """Read the literal closing quote of the complete two-choice invitation."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text'].endswith(' Emissary') and 307<=r['center'][1]<=320]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return
    title,ok=headings[0],controls[0]
    if abs(title['center'][0]-ok['center'][0])>8 or not 452<=ok['center'][1]<=469:return
    panel=sorted([r for r in rows if title['center'][1]<r['center'][1]<ok['center'][1]
                  and 300<=r['bounds'][0]<635],key=lambda r:r['center'][1])
    if len(panel)!=5 or any(r['confidence']<.8 for r in panel):return
    first,second,tail,no,yes=panel
    if (first['text']!='"We invite you to join our crusade to rid the'
            or tail['text']!='for the duration of the hostilities.'
            or no['text']!='"No, not interested."'):return
    target=re.fullmatch(r'world of the evil ([A-Za-z][A-Za-z -]{1,45})\. We will sign an alliance',second['text'])
    if not target or yes['text']!=f'Yes, declare war on {target[1]}.':return
    if (any(not 306<=r['bounds'][0]<=318 for r in (first,second,tail))
            or not 17<=second['center'][1]-first['center'][1]<=26
            or not 16<=tail['center'][1]-second['center'][1]<=24
            or not 19<=no['center'][1]-tail['center'][1]<=31
            or not 20<=yes['center'][1]-no['center'][1]<=31):return
    wanted='for the duration of the hostilities."'
    a=_crop_text(image,tail,'crusade_tail_rgb4',executable,directory,evidence,padding=(3,3),scale=4)
    b=_crop_text(image,tail,'crusade_tail_gray4',executable,directory,evidence,padding=(3,3),scale=4,grayscale=True)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=wanted or b[0]['text']!=wanted
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(tail,a[0]) or not _same_location(a[0],b[0])):return
    index=rows.index(tail)
    if _replace_crop_row(rows,index,a,lambda old,new:True):rows[index]['provenance']+=b[0]['provenance']


def _recover_diplomacy_gift_row(image,rows,executable,directory,evidence):
    """Recover a doubled OCR glyph from two actual complete option reads."""
    if image.size!=(640,480) or len(rows)!=9:return
    ordered=sorted(rows,key=lambda row:(row['center'][1],row['center'][0]))
    if (not ordered[0]['text'].endswith(' Emissary')
            or not 240<=ordered[0]['bounds'][1]<=255
            or ordered[1]['text']!='You respond: "We..."'
            or [r['text'] for r in ordered[2:7]]!=[
                '"Consider this discussion complete."','"Suggest a permanent strategic alliance."',
                '"Demand tribute for our patience."','"Insist that you withdraw your troops."',
                '"Have a proposal to make..."']
            or ordered[7]['text']!='"Wish to offer you a gifft..."'
            or ordered[8]['text']!='OK' or not 450<=ordered[8]['center'][1]<=467):return
    old=ordered[7];expected='"Wish to offer you a gift..."'
    if not 330<=old['bounds'][0]<=350 or not 412<=old['bounds'][1]<=426:return
    a=_crop_text(image,old,'diplomacy_gift_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
    b=_crop_text(image,old,'diplomacy_gift_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=expected or b[0]['text']!=expected
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(old,a[0]) or not _same_location(a[0],b[0])):return
    index=rows.index(old)
    if _replace_crop_row(rows,index,a,lambda previous,fresh:True):
        rows[index]['provenance']+=b[0]['provenance']


def _recover_howdy_spacing(image,rows,executable,directory,evidence):
    """Read the observed HOWDYPEACE spacing twice; retain every actual word."""
    if image.size!=(640,480) or len(rows)!=4:return
    ordered=sorted(rows,key=lambda row:(row['center'][1],row['center'][0]))
    heading,first,tail,ok=ordered
    expected='"We are always pleased to speak with our'
    if (not heading['text'].endswith(' Emissary') or not 375<=heading['center'][1]<=395
            or first['text']!='"We are always pleased tospeak with our'
            or not re.fullmatch(r'friends the [A-Za-z][A-Za-z -]{1,50}\."',tail['text'])
            or ok['text']!='OK' or not 450<=ok['center'][0]<=485 or not 449<=ok['center'][1]<=468
            or not 300<=first['bounds'][0]<=314 or not 398<=first['bounds'][1]<=406
            or not 14<=tail['center'][1]-first['center'][1]<=26
            or abs(first['bounds'][0]-tail['bounds'][0])>6):return
    a=_crop_text(image,first,'howdy_spacing_rgb3',executable,directory,evidence,padding=(3,3),scale=3)
    b=_crop_text(image,first,'howdy_spacing_gray3',executable,directory,evidence,padding=(3,3),scale=3,grayscale=True)
    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=expected or b[0]['text']!=expected
            or min(a[0]['confidence'],b[0]['confidence'])<.8
            or not _same_location(first,a[0]) or not _same_location(a[0],b[0])):return
    index=rows.index(first)
    if _replace_crop_row(rows,index,a,lambda old,fresh:old.replace(' ','')==fresh.replace(' ','')):
        rows[index]['provenance']+=b[0]['provenance']


def _recover_split_production_title(image,rows,executable,directory,evidence):
    """Use only two actual adjacent heading fragments as a crop boundary."""
    if image.size!=(640,480):return
    buttons=[r for r in rows if r['text'].casefold() in ('auto','help','ok','cancel','yes','no')]
    if (len(buttons)!=3 or {r['text'].casefold() for r in buttons}!={'auto','help','ok'}
            or any(r['confidence']<.8 for r in buttons)
            or max(r['center'][1] for r in buttons)-min(r['center'][1] for r in buttons)>8):return
    # A second observed split has the complete What/shall fragment on the
    # left. Both distinct crop scales must independently read the full title
    # and agree on its city suffix; no native city name supplies any pixels.
    lefts=[r for r in rows if r['confidence']>=.8 and _near_text(r['text'].casefold(),'what shall',1)
           and 70<r['center'][1]<min(b['center'][1] for b in buttons)-20]
    if len(lefts)==1:
        left=lefts[0]
        rights=[r for r in rows if r is not left and r['confidence']>=.8
                and re.fullmatch(r'(?:we|me) [a-z]{3,7} in ([A-Za-z][A-Za-z -]{0,59})\??',r['text'],re.I)
                and -3<=r['bounds'][0]-(left['bounds'][0]+left['bounds'][2])<=8
                and abs(r['center'][1]-left['center'][1])<=3]
        if len(rights)==1:
            right=rights[0];original=re.fullmatch(r'(?:we|me) [a-z]{3,7} in (.+?)\??',right['text'],re.I)[1]
            x=left['bounds'][0];y=min(left['bounds'][1],right['bounds'][1])
            w=right['bounds'][0]+right['bounds'][2]-x;h=max(r['bounds'][1]+r['bounds'][3] for r in (left,right))-y
            if 10<=h<=24 and 80<=w<=400:
                area=dict(left,text=left['text']+' '+right['text'],bounds=[x,y,w,h],center=[round(x+w/2),round(y+h/2)],
                          provenance=left['provenance']+right['provenance'])
                readings=[]
                for scale,padding in ((3,(3,3)),(4,(4,3))):
                    a=_crop_text(image,area,f'split_complete_title_rgb{scale}',executable,directory,evidence,padding=padding,scale=scale)
                    b=_crop_text(image,area,f'split_complete_title_gray{scale}',executable,directory,evidence,padding=padding,scale=scale,grayscale=True)
                    if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                            or min(a[0]['confidence'],b[0]['confidence'])<.8
                            or not _same_location(area,a[0]) or not _same_location(a[0],b[0])):break
                    match=re.fullmatch(r'What shall\s*(?:we|me) ([a-z]{3,7}) in (.{1,60})\?',a[0]['text'],re.I)
                    if (not match or not _near_text(match[1].casefold(),'build',2)
                            or not _near_text(match[2].casefold(),original.casefold(),1)):break
                    readings.append((a[0],b[0],match[2]))
                if len(readings)==2 and readings[0][2].casefold()==readings[1][2].casefold():
                    fresh=dict(readings[0][0]);fresh['provenance']=area['provenance']+[
                        p for a,b,_ in readings for r in (a,b) for p in r['provenance']]
                    rows[rows.index(left)]=fresh;rows.remove(right)
    for right in list(rows):
        suffix=re.fullmatch(r'hall (?:we|me) [a-z]{3,7} in (.{1,60})\?',right['text'],re.I)
        if not suffix or right['confidence']<.8 or not 70<right['center'][1]<min(r['center'][1] for r in buttons)-20:continue
        lefts=[r for r in rows if r is not right and r['confidence']>=.8
               and re.fullmatch(r'[A-Za-z ]{2,12}',r['text']) and 8<=r['bounds'][2]<=80
               and -1<=right['bounds'][0]-(r['bounds'][0]+r['bounds'][2])<=8
               and abs(r['center'][1]-right['center'][1])<=3]
        if len(lefts)!=1:continue
        left=lefts[0];x=left['bounds'][0];y=min(left['bounds'][1],right['bounds'][1])
        w=right['bounds'][0]+right['bounds'][2]-x;h=max(r['bounds'][1]+r['bounds'][3] for r in (left,right))-y
        if not 10<=h<=24 or not 80<=w<=400:continue
        area=dict(left,text=left['text']+' '+right['text'],bounds=[x,y,w,h],center=[round(x+w/2),round(y+h/2)],
                  provenance=left['provenance']+right['provenance'])
        a=_crop_text(image,area,'split_production_title_rgb2',executable,directory,evidence,padding=(6,6),scale=2)
        b=_crop_text(image,area,'split_production_title_gray2',executable,directory,evidence,padding=(6,6),scale=2,grayscale=True)
        if len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']:continue
        match=re.fullmatch(r'What shall (?:we|me) ([a-z]{3,7}) in (.{1,60})\?',a[0]['text'],re.I)
        if (not match or not _near_text(match[1].casefold(),'build',2) or match[2]!=suffix[1]
                or min(a[0]['confidence'],b[0]['confidence'])<.8 or not _same_location(area,b[0])
                or not _same_location(a[0],b[0])):continue
        a[0]['provenance']=area['provenance']+a[0]['provenance']+b[0]['provenance']
        rows[rows.index(left)]=a[0];rows.remove(right)


def _recover_joined_production_title(image,rows,executable,directory,evidence):
    """Read a joined verb/preposition from two full-title pixel scales."""
    if image.size!=(640,480):return
    controls=[r for r in rows if r['text'] in ('Auto','Help','OK','Yes','No','Cancel')]
    if (len(controls)!=3 or {r['text'] for r in controls}!={'Auto','Help','OK'}
            or min(r['confidence'] for r in controls)<.8
            or max(r['center'][1] for r in controls)-min(r['center'][1] for r in controls)>8):return
    captions=[r for r in rows if city_date_match(r['text'],damaged_prefix=True)
              and r['confidence']>=.8 and 32<=r['bounds'][1]<=56]
    if len(captions)!=1:return
    candidates=[]
    for r in rows:
        m=re.fullmatch(r'What shall (?:we|me) ([a-z]{5,9}) ([A-Za-z][A-Za-z -]{0,59})[!?]',r['text'])
        if (m and _near_text(m[1],'buildin',3) and r['confidence']>=.8
                and 308<=r['center'][0]<=332 and 70<r['center'][1]<min(c['center'][1] for c in controls)-30
                and 10<=r['bounds'][3]<=24 and 120<=r['bounds'][2]<=400):candidates.append((r,m[2]))
    if len(candidates)!=1:return
    title,old_city=candidates[0];readings=[]
    for scale in (3,4):
        a=_crop_text(image,title,f'joined_production_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
        b=_crop_text(image,title,f'joined_production_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(title,a[0]) or not _same_location(a[0],b[0])):return
        m=re.fullmatch(r'Wh(?:at|ait) shall (?:we|me) ([a-z]{3,7}) in ([A-Za-z][A-Za-z -]{0,59})\?',a[0]['text'])
        if not m or not _near_text(m[1],'build',3) or not _near_text(m[2].casefold(),old_city.casefold(),2):return
        readings.append((a[0],b[0],m[2]))
    if readings[0][2]!=readings[1][2] or not readings[1][0]['text'].startswith('What shall '):return
    fresh=dict(readings[1][0]);fresh['provenance']=[p for a,b,_ in readings for r in (a,b) for p in r['provenance']]
    # Retain the full-image row's original geometry; enlarged OCR bounds can
    # include adjacent list pixels. Each actual crop geometry stays in provenance.
    fresh.update({k:deepcopy(title[k]) for k in ('bounds','center','x','y','width','height') if k in title})
    index=rows.index(title)
    if _replace_crop_row(rows,index,[fresh],lambda old,new:True):
        rows[index]['production_title_identity_consensus']={'city_text':readings[1][2],'independent_scales':2}


def _recover_founded_production_title(image,rows,executable,directory,evidence):
    """Broader suffix reading still needs a separate native founding notice."""
    if image.size!=(640,480):return
    pattern=r'What shall (?:we|me) ([a-z]{3,7}) in (.{1,60})\?'
    titles=[r for r in rows if re.fullmatch(pattern,r['text'],re.I) and r['confidence']>=.8 and 70<r['center'][1]<350]
    captions=[city_date_match(r['text'],damaged_prefix=True)
              for r in rows if r['confidence']>=.8 and 32<=r['bounds'][1]<=56]
    years=[m[2] for m in captions if m]
    if len(titles)!=1 or len(years)!=1:return
    title=titles[0];original=re.fullmatch(pattern,title['text'],re.I)
    if _near_text(original[1].casefold(),'build',2):return
    controls=[r for r in rows if r['text'].casefold() in ('auto','help','ok') and r['center'][1]>title['center'][1]]
    if len(controls)!=3 or {r['text'].casefold() for r in controls}!={'auto','help','ok'}:return
    if max(r['center'][1] for r in controls)-min(r['center'][1] for r in controls)>8:return
    readings=[]
    for scale,pad,max_verb_error in ((3,8,2),(4,3,3)):
        a=_crop_text(image,title,f'founded_production_rgb{scale}',executable,directory,evidence,padding=(pad,pad),scale=scale)
        b=_crop_text(image,title,f'founded_production_gray{scale}',executable,directory,evidence,padding=(pad,pad),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(title,a[0]) or not _same_location(a[0],b[0])):return
        match=re.fullmatch(pattern,a[0]['text'],re.I)
        if (not match or not _near_text(match[1].casefold(),'build',max_verb_error)
                or not _near_text(match[2].casefold(),original[2].casefold(),2)):return
        readings.append((a[0],b[0],match[2]))
    if readings[0][2].casefold()!=readings[1][2].casefold():return
    selected=dict(readings[0][0])
    selected['provenance']=[p for a,b,_ in readings for r in (a,b) for p in r['provenance']]
    index=rows.index(title)
    if _replace_crop_row(rows,index,[selected],lambda old,new:True):
        rows[index]['production_title_identity_consensus']={'city_text':readings[0][2],
            'independent_scales':2,'requires_founding_notice':True,'observed_year':years[0]}


def _recover_city_caption_year(image,rows,executable,directory,evidence):
    """Read date digits twice without changing the city, era, or remaining text."""
    if image.size!=(640,480):return
    for row in rows:
        old=city_date_match(row['text']);x,y,w,h=row['bounds']
        if not old or row['confidence']<.8 or not (32<=y<=56 and 350<=w<=500 and 8<=h<=24):continue
        old_number,old_era=date_parts(old[2])
        prefix={'bounds':[max(0,x-6),max(0,y-4),round(w*.42)+6,h+8]}
        found=[]
        for scale in (3,4):
            values=_crop_text(image,prefix,f'city_year_prefix_{scale}x',executable,directory,evidence,
                              padding=(0,0),scale=scale)
            if len(values)!=1:break
            fresh=values[0];match=city_date_match(fresh['text'])
            if not match:break
            number,era=date_parts(match[2])
            if (fresh['confidence']<.8 or not _near_text(old[1].casefold(),match[1].casefold(),2)
                    or old_era!=era or len(old_number)!=len(number) or not _near_text(old_number,number,1)
                    or not x-6<=fresh['bounds'][0]<=x+6 or abs(fresh['center'][1]-row['center'][1])>4):break
            found.append((number,fresh))
        if len(found)!=2 or found[0][0]!=found[1][0] or found[0][0]==old_number:continue
        digit_span=re.search(r'[0-9]+',old[2]).span()
        left,right=(old.start(2)+v for v in digit_span)
        row['text']=row['text'][:left]+found[0][0]+row['text'][right:]
        row['provenance']+=found[0][1]['provenance']+found[1][1]['provenance']
        row['caption_year_consensus']={'independent_scales':2,'old_year':old_number,'observed_year':found[0][0],
            'scope':'Only date digits; original city and remaining caption text unchanged'}


def _production_heading_read_locator(text):
    """Damaged first word locates pixels only; source title checks stay strict."""
    text=text.strip().rstrip('?')
    if not _near_text(text.split(' ',1)[0].casefold(),'what',2):return None
    return re.fullmatch(r'[a-z]{3,6} (?:shall|chall)\s*(?:we|me|te)\s+([a-z]{3,7}?)\s*in (.{1,60})',text,re.I)


def _recover_city_and_production_rows(image, rows, executable, directory, evidence):
    """Narrow native city/list layouts; no rules names or dates are invented."""
    if image.size!=(640,480):return
    if not any(_production_heading_read_locator(r['text']) for r in rows):
        annotate_production_crop_anchor(image,rows)
    def caption(text):return city_date_match(text,damaged_prefix=True)
    def number(match):return date_parts(match[2])[0]
    def era(match):return date_parts(match[2])[1]
    for index,row in enumerate(rows):
        previous=caption(row['text'])
        if previous and 32<=row['bounds'][1]<=56 and row['confidence']>=.8:
            def same_caption(old,new):
                fresh=caption(new)
                same_name=bool(fresh and previous[1].casefold()==fresh[1].casefold())
                # The original N can be read as HT. A different name must be
                # read at two distinct scales and keep the observed date exact.
                name_ok=bool(fresh and (same_name or (_near_text(previous[1].casefold(),fresh[1].casefold(),2)
                                                     and number(previous)==number(fresh))))
                return bool(fresh and new.casefold().startswith('city of ') and name_ok
                    and _near_text(number(previous),number(fresh),1)
                    and era(previous)==era(fresh))
            readings=[]
            framings=[(2,(3,3)),(3,(6,6)),(4,(6,6)),(4,(8,6))]
            # A damaged "City" prefix can remain wrong at one framing while
            # both 4x reads agree. Two further bounded framings still require
            # agreement at distinct scales; neither the city nor date comes
            # from state. Original 010/172 needs the wider 2x crop.
            if not row['text'].casefold().startswith('city of '):
                framings += [(2,(6,6)),(3,(3,3)),(2,(8,6))]
            for scale,padding in framings:
                suffix='_wide' if padding==(8,6) else ''
                first=_crop_text(image,row,f'city_caption_{scale}x{suffix}',executable,directory,evidence,padding=padding,scale=scale)
                second=_crop_text(image,row,f'city_caption_gray_{scale}x{suffix}',executable,directory,evidence,padding=padding,scale=scale,grayscale=True)
                if len(first)!=1 or len(second)!=1:continue
                a,b=first[0],second[0];ma,mb=caption(a['text']),caption(b['text'])
                identity=lambda m:(m[1].casefold(),number(m),era(m))
                if (not ma or not mb or identity(ma)!=identity(mb) or min(a['confidence'],b['confidence'])<.8
                        or not _same_location(row,a) or not _same_location(row,b)
                        or not same_caption(row['text'],a['text']) or not same_caption(row['text'],b['text'])):continue
                readings.append((identity(ma),a,b,scale))
                agrees=[v for v in readings if v[0]==identity(ma)]
                scales={v[3] for v in agrees}
                if len(scales)>=2:
                    # Two narrow crops can share a systematic date error.
                    # Before changing a native date, check two wider framings
                    # at distinct scales. A native date is preferred only if
                    # both independent pairs actually confirm it.
                    if number(ma)!=number(previous):
                        alternatives=[]
                        for check_scale,check_padding in ((3,(8,6)),(4,(12,6))):
                            aa=_crop_text(image,row,f'city_caption_datecheck_{check_scale}x',executable,directory,evidence,
                                          padding=check_padding,scale=check_scale)
                            bb=_crop_text(image,row,f'city_caption_datecheck_gray_{check_scale}x',executable,directory,evidence,
                                          padding=check_padding,scale=check_scale,grayscale=True)
                            if len(aa)!=1 or len(bb)!=1:continue
                            am,bm=caption(aa[0]['text']),caption(bb[0]['text'])
                            if (not am or not bm or identity(am)!=identity(bm) or min(aa[0]['confidence'],bb[0]['confidence'])<.8
                                    or not _same_location(row,aa[0]) or not _same_location(row,bb[0])
                                    or not same_caption(row['text'],aa[0]['text']) or not same_caption(row['text'],bb[0]['text'])):continue
                            alternatives.append((identity(am),aa[0],bb[0],check_scale))
                        readings+=alternatives
                        native_agrees=[v for v in alternatives if v[0]==identity(previous)]
                        if len({v[3] for v in native_agrees})==2:
                            agrees=native_agrees;ma=caption(agrees[0][1]['text'])
                            scales={v[3] for v in agrees}
                        elif any(v[0]!=identity(ma) for v in alternatives):
                            # Conflicting complete paired date reads cannot
                            # authorize a numeric replacement.
                            break
                    selected=agrees[0][1]
                    selected['provenance']=[p for _,aa,bb,_ in readings for r in (aa,bb) for p in r['provenance']]
                    if _replace_crop_row(rows,index,[selected],same_caption):
                        rows[index]['caption_identity_consensus']={'independent_scales':len(scales),'year_text':number(ma)}
                    break
    # OCR can split this centered native caption in two. Joining the two
    # observed fragments supplies a crop anchor, never canonical title text.
    # Exact source/GDI title verification remains the classifier's job.
    controls=[r for r in rows if r['text'].strip() in ('Auto','Help','OK')]
    if (len(controls)==3 and {r['text'].strip() for r in controls}=={'Auto','Help','OK'}
            and max(r['center'][1] for r in controls)-min(r['center'][1] for r in controls)<=8):
        suffixes=[r for r in rows if re.fullmatch(r'(?:we|me) [a-z]{3,7} in [A-Za-z ]{1,60}\?',r['text'])
                  and 70<=r['bounds'][1]<=200 and r['confidence']>=.8]
        if len(suffixes)==1:
            tail=suffixes[0];x,y,w,h=tail['bounds']
            prefixes=[r for r in rows if r is not tail and r['confidence']>=.8
                      and 100<=r['bounds'][0]<x and abs(r['center'][1]-tail['center'][1])<=3
                      and 0<=x-r['bounds'][0]-r['bounds'][2]<=40]
            if len(prefixes)==1:
                head=prefixes[0];left=head['bounds'][0];top=min(y,head['bounds'][1]);right=x+w
                bottom=max(y+h,head['bounds'][1]+head['bounds'][3])
                if (308<=(left+right)/2<=332 and right<=540 and bottom-top<=24
                        and min(r['center'][1] for r in controls)>bottom+30):
                    joined=dict(head,text=head['text']+' '+tail['text'],bounds=[left,top,right-left,bottom-top],
                        center=[round((left+right)/2),round((top+bottom)/2)],
                        x=left/image.width,y=top/image.height,width=(right-left)/image.width,height=(bottom-top)/image.height,
                        provenance=head['provenance']+tail['provenance'],production_caption_fragments=True)
                    rows[rows.index(head)]=joined;rows.remove(tail)
    # A damaged first word only permits re-reading the same title pixels. The
    # replacement must independently contain the actual original "What".
    # A missing OCR space before "in" may locate the list for pixel re-reads,
    # but never supplies a canonical title or authorizes its classification.
    titles=[r for r in rows if (_production_heading_read_locator(r['text'])
                              or r.get('production_crop_anchor')
                              or r.get('production_caption_fragments') is True)
            and r['confidence']>=.8 and 70<r['center'][1]<350]
    if len(titles)!=1:return
    title=titles[0];buttons=[r for r in rows if r['text'].strip().casefold() in ('auto','help','ok')
                           and r['center'][1]>title['center'][1] and r['confidence']>=.8]
    if len(buttons)!=3 or {r['text'].strip().casefold() for r in buttons}!={'auto','help','ok'}:
        return
    bottom=min(r['center'][1] for r in buttons)
    if max(r['center'][1] for r in buttons)-bottom>8:return
    # Original006/653's full-image "bodkd" is read as "bukd" by both a
    # separately cropped RGB and grayscale pass. Keep that actual reading;
    # do not replace the verb or city with a guessed canonical title.
    heading=lambda text:re.fullmatch(r'what shall\s*(?:we|me) ([a-z]{3,7}) in (.{1,60})',text.strip().rstrip('?'),re.I)
    old_heading=_production_heading_read_locator(title['text'])
    if old_heading and (not heading(title['text']) or not _near_text(old_heading[1].casefold(),'build',2)):
        city_readings=[]
        framings=[(3,(6,6)),(2,(6,6)),(2,(3,3))]
        if re.search(r'shall(?:we|me)|[a-z]in |^What chall ',title['text'],re.I):
            framings.insert(0,(3,(3,3)))
            framings.append((4,(4,3)))
        # Original011/1823 needs two extra source pixels on each side to
        # independently read the initial What. This only repairs that word;
        # the already measured bodd verb and city remain actual OCR text.
        damaged_what=title['text'].casefold().startswith('whait shall ')
        if damaged_what:framings.append((3,(8,6)))
        for scale,padding in framings:
            first=_crop_text(image,title,f'production_title_{scale}x',executable,directory,evidence,padding=padding,scale=scale)
            second=_crop_text(image,title,f'production_title_gray_{scale}x',executable,directory,evidence,padding=padding,grayscale=True,scale=scale)
            if len(first)==len(second)==1 and first[0]['text']==second[0]['text']:
                fresh=heading(first[0]['text'])
                if (fresh and _near_text(fresh[2].casefold(),old_heading[2].casefold(),1)
                        and (_near_text(fresh[1].casefold(),'build',2)
                             or (damaged_what and fresh[1].casefold()==old_heading[1].casefold()=='bodd'
                                 and fresh[2].casefold()==old_heading[2].casefold()))
                        and min(first[0]['confidence'],second[0]['confidence'])>=.8
                        and _same_location(title,first[0]) and _same_location(title,second[0])):
                    changed_city=fresh[2].casefold()!=old_heading[2].casefold()
                    if changed_city:
                        # Never replace a city suffix from one crop pair.
                        # Two distinct scales must agree on the same observed
                        # one-glyph correction; no state name is consulted.
                        city_readings.append((fresh[2].casefold(),scale,first[0],second[0]))
                        agrees=[v for v in city_readings if v[0]==fresh[2].casefold()]
                        if len({v[1] for v in agrees})<2:continue
                        first=[dict(agrees[0][2])]
                        first[0]['provenance']=[p for _,_,a,b in agrees for row in(a,b) for p in row['provenance']]
                    index=rows.index(title)
                    if _replace_crop_row(rows,index,first,lambda old,new:True):
                        if changed_city:
                            rows[index]['production_title_identity_consensus']={'city_text':fresh[2],'independent_scales':2}
                        else:rows[index]['provenance']+=second[0]['provenance']
                        title=rows[index];break
    vocabulary=_production_names()
    for index,row in enumerate(rows):
        if not (title['center'][1]+8<row['center'][1]<bottom-8
                and title['center'][0]-220<row['center'][0]<title['center'][0]+220):continue
        text=row['text'].strip()
        if row['center'][0]<title['center'][0] and re.fullmatch(r'[A-Za-z ]{5,80}',text):
            if not vocabulary or text.casefold() in vocabulary:continue
            # Only selected white glyphs survive this transform. Require an
            # independently read nearby spelling; the classifier still requires
            # an exact original rules-table option and full dialog corroboration.
            crop=image.convert('RGB').crop(tuple((row['bounds'][0],row['bounds'][1],
                row['bounds'][0]+row['bounds'][2],row['bounds'][1]+row['bounds'][3])))
            pixels=list(crop.getdata())
            if not pixels or sum(min(p)>=230 for p in pixels)/len(pixels)<.08:continue
            candidates=_crop_text(image,row,f'production_name_{index}_white_4x',executable,directory,evidence,white=True)
            accepted=_replace_crop_row(rows,index,candidates,lambda old,new:new.casefold() in vocabulary
                              and _near_text(old.casefold(),new.casefold(),2))
            if not accepted:
                first=_crop_text(image,row,f'production_name_{index}_2x',executable,directory,evidence,padding=(3,3),scale=2)
                second=_crop_text(image,row,f'production_name_{index}_gray_2x',executable,directory,evidence,padding=(3,3),grayscale=True,scale=2)
                if (len(first)==len(second)==1 and first[0]['text']==second[0]['text']
                        and second[0]['confidence']>=.8 and _same_location(row,second[0])
                        and _replace_crop_row(rows,index,first,lambda old,new:new.casefold() in vocabulary and _near_text(old.casefold(),new.casefold(),2))):
                    rows[index]['provenance']+=second[0]['provenance']
        elif row['center'][0]>title['center'][0] and re.match(r'^\(?\d',text):
            if _stat_reading(text)==text:continue
            for padding in ((3,3),(6,6)):
                try:
                    candidates=_crop_text(image,row,f'production_stat_{index}_{padding[0]}_3x',executable,directory,evidence,padding=padding)
                    peers=_crop_text(image,row,f'production_stat_{index}_{padding[0]}_gray_3x',executable,directory,evidence,padding=padding,grayscale=True)
                except ValueError:continue
                if len(candidates)!=1 or len(peers)!=1:continue
                candidate,peer=candidates[0],peers[0]
                canonical=_stat_reading(candidate['text'])
                if (canonical is None or canonical!=_stat_reading(peer['text']) or peer['confidence']<.8
                        or not _same_location(row,peer) or not _stat_numbers_compatible(text,canonical)):continue
                candidate['text']=canonical;candidate['provenance']+=peer['provenance']
                if _replace_crop_row(rows,index,candidates,lambda old,new:True):break


def _recover_production_option_rows(image,rows,executable,directory,evidence):
    """Read damaged list labels, including icon ink, from complete row crops."""
    if image.size!=(640,480):return
    titles=[r for r in rows if (_production_heading_read_locator(r['text']) or r.get('production_crop_anchor'))
            and r['confidence']>=.8 and 70<r['center'][1]<350]
    if len(titles)!=1:return
    title=titles[0]
    controls=[r for r in rows if r['text'] in ('Auto','Help','OK') and r['center'][1]>title['center'][1]]
    if (len(controls)!=3 or {r['text'] for r in controls}!={'Auto','Help','OK'}
            or max(r['center'][1] for r in controls)-min(r['center'][1] for r in controls)>8):return
    bottom=min(r['center'][1] for r in controls);names=_production_names()
    def paired_stat(row):
        return len([r for r in rows if r['center'][0]>title['center'][0] and _stat_reading(r['text'])
                    and abs(r['center'][1]-row['center'][1])<=5])==1
    known=[r for r in rows if title['center'][1]+8<r['center'][1]<bottom-8
           and r['center'][0]<title['center'][0] and r['text'].casefold() in names
           and r['confidence']>=.8 and paired_stat(r)]
    if len(known)<4:return
    left=sorted(r['bounds'][0] for r in known)[len(known)//2]
    for index,old in enumerate(rows):
        x,y,w,h=old['bounds'];text=old['text']
        if (text.casefold() in names or not title['center'][1]+8<old['center'][1]<bottom-8
                or not left-18<=x<=left+6 or x+w>=title['center'][0] or not 8<=h<=24
                or not paired_stat(old) or re.search(r'\b(?:no|not|cancel|yes|ok|help)\b',text,re.I)):continue
        def compatible(new):
            if new.casefold() not in names:return False
            if _near_text(text.casefold(),new.casefold(),2):return True
            # Original unit/improvement art can be merged into the label.
            # Only a short extra prefix extending left of the independently
            # observed label column permits a three-glyph difference.
            return (x<=left-8 and text.casefold().endswith(' '+new.casefold())
                    and len(text)-len(new)<=3 and _near_text(text.casefold(),new.casefold(),3))
        if not any(compatible(name) for name in names):continue
        for scale in (2,3,4):
            a=_crop_text(image,old,f'production_option_{index}_rgb{scale}',executable,directory,evidence,padding=(3,3),scale=scale)
            b=_crop_text(image,old,f'production_option_{index}_gray{scale}',executable,directory,evidence,padding=(3,3),scale=scale,grayscale=True)
            if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                    or min(a[0]['confidence'],b[0]['confidence'])<.8
                    or not compatible(a[0]['text']) or not _same_location(old,b[0])
                    or not _same_location(a[0],b[0])):continue
            if _replace_crop_row(rows,index,a,lambda before,after:True):
                rows[index]['provenance']+=b[0]['provenance'];break


def _recover_fortress_order_body(image,rows,executable,directory,evidence):
    """Read two damaged rows of the original informational Fortress notice."""
    if image.size!=(640,480):return
    titles=[r for r in rows if r['text']=='New Order: Fortress' and r['confidence']>=.8]
    oks=[r for r in rows if r['text'].strip().casefold()=='ok']
    if len(titles)!=1 or len(oks)!=1:return
    title,ok=titles[0],oks[0]
    if abs(title['center'][0]-ok['center'][0])>8:return
    endings=[r for r in rows if r['text']=='being lost in combat.' and title['center'][1]<r['center'][1]<ok['center'][1]]
    if len(endings)!=1:return
    for index,old in enumerate(rows):
        if not title['center'][1]<old['center'][1]<ok['center'][1] or abs(old['center'][0]-title['center'][0])>160:continue
        if old['text'].startswith('Our Settlers can now use the Fortress ('):
            expected='Our Settlers can now use the Fortress ("F")';scale=4
        elif old['text']=='and prevent more than one unit at a fime from':
            expected='and prevent more than one unit at a time from';scale=3
        else:continue
        a=_crop_text(image,old,'fortress_body_rgb'+str(scale),executable,directory,evidence,padding=(6,3),scale=scale)
        b=_crop_text(image,old,'fortress_body_gray'+str(scale),executable,directory,evidence,padding=(6,3),scale=scale,grayscale=True)
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=expected or b[0]['text']!=expected
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(a[0],b[0])):continue
        if _replace_crop_row(rows,index,a,lambda raw,fresh:fresh==expected):
            rows[index]['provenance']+=b[0]['provenance']


def _recover_masked_city_badge(image,rows,executable,directory,evidence):
    """Retain both components when two white masks read a label and real badge."""
    from .map_badges import proven_badge
    if image.size!=(640,480):return
    menu={r['text'].casefold() for r in rows if r['bounds'][1]<35 and r['confidence']>=.8}
    if not {'game','kingdom','view','orders'}<=menu:return
    blocked={'ok','cancel','yes','no','help','warning','continue','exit','save','load'}
    if any(r['text'].strip().casefold() in blocked and r['center'][1]>40 for r in rows):return
    for old in list(rows):
        x,y,w,h=old['bounds'];tokens=old['text'].split()
        if (not 8<=x<x+w<=456 or not 70<=y<y+h<=440 or not 24<h<=40 or not 60<=w<=160
                or old['confidence']<.3 or not 2<=len(tokens)<=3
                or not re.fullmatch(r'[^\W\d_]{3,25}',tokens[0]) or not 1<=sum(map(len,tokens[1:]))<=8
                or any(token.casefold() in blocked for token in tokens)):continue
        a=_crop_text(image,old,'masked_city_badge_white160',executable,directory,evidence,
                     padding=(3,3),white_threshold=160)
        b=_crop_text(image,old,'masked_city_badge_white230',executable,directory,evidence,
                     padding=(3,3),white_threshold=230)
        # Original010/2419's lower threshold omits the neighboring badge.
        # Matching name pixels only permit one additional complete-mask read;
        # no component may be assembled from inconsistent partial readings.
        if (len(a)==1 and len(b)==2 and a[0]['text']==b[0]['text']
                and min(a[0]['confidence'],b[0]['confidence'])>=.8 and _same_location(a[0],b[0])
                and re.fullmatch('[A-Za-z]{3,25}',b[0]['text']) and re.fullmatch('[1-9][0-9]?',b[1]['text'])):
            a=_crop_text(image,old,'masked_city_badge_white220',executable,directory,evidence,
                         padding=(3,3),white_threshold=220)
        if (len(a)!=2 or len(b)!=2 or [r['text'] for r in a]!=[r['text'] for r in b]
                or min(r['confidence'] for r in [*a,*b])<.8
                or not all(_same_location(p,q) for p,q in zip(a,b))):continue
        name,digit=a
        if (not re.fullmatch('[A-Za-z]{3,25}',name['text']) or name['text'].casefold() in blocked
                or abs(len(name['text'])-len(tokens[0]))>2
                or not re.fullmatch('[1-9][0-9]?',digit['text'])
                or name['bounds'][0]+name['bounds'][2]>=digit['bounds'][0]
                or digit['center'][1]<=name['center'][1]):continue
        if any(not(x-2<=r['bounds'][0] and r['bounds'][0]+r['bounds'][2]<=x+w+2
                   and y-2<=r['bounds'][1] and r['bounds'][1]+r['bounds'][3]<=y+h+2) for r in [*a,*b]):continue
        if any(other is not old and any(_overlap(other,r) for r in a) for other in rows):continue
        # This local token only binds the in-memory source pixels while
        # checking the complete badge pattern. recognize annotates the final
        # rows again with the original PNG hash before classification.
        pixel_digest=hashlib.sha256(image.tobytes()).hexdigest()
        annotate_badges(image,[digit],pixel_digest)
        if not proven_badge(digit,pixel_digest):continue
        digit.pop('map_badge_pixels',None)
        for r,peer in zip(a,b):
            r['provenance']=old['provenance']+r['provenance']+peer['provenance']
            r['merged_map_components']={'original_bounds':old['bounds'],'original_text':old['text'],
                                        'observed_components':[v['text'] for v in a]}
        index=rows.index(old);rows[index:index+1]=a


def _recover_merged_city_badge(image,rows,executable,directory,evidence):
    """Keep every re-read component of a merged city label and exact badge."""
    from .map_badges import occluded_badge_bounds
    if image.size!=(640,480):return
    menu={r['text'].casefold() for r in rows if r['bounds'][1]<35 and r['confidence']>=.8}
    if not {'game','kingdom','view','orders'}<=menu:return
    if any(r['text'].strip().casefold() in ('ok','cancel','yes','no','help') and r['center'][1]>40 for r in rows):return
    for old in list(rows):
        x,y,w,h=old['bounds'];tokens=old['text'].split()
        if (not 8<=x<x+w<=456 or not 70<=y<y+h<=440 or not 24<h<=40 or not 60<=w<=160
                or old['confidence']<.3 or len(tokens)!=2 or not re.fullmatch('[A-Za-z]{3,25}',tokens[0])
                or not 1<=len(tokens[1])<=8):continue
        selected=None
        for padding in ((3,3),(3,6)):
            a=_crop_text(image,old,f'merged_city_badge_rgb3_pad{padding[1]}',executable,directory,evidence,padding=padding)
            b=_crop_text(image,old,f'merged_city_badge_gray3_pad{padding[1]}',executable,directory,evidence,padding=padding,grayscale=True)
            names=[r for r in a if re.fullmatch('[A-Za-z]{3,25}',r['text'])]
            digits=[r for r in a if re.fullmatch('[1-9][0-9]?',r['text'])]
            if len(a)!=2 or len(b)!=1 or len(names)!=1 or len(digits)!=1:continue
            name,digit=names[0],digits[0]
            if (name['text']!=b[0]['text'] or min(r['confidence']for r in [*a,*b])<.8
                    or not _same_location(name,b[0]) or not _near_text(tokens[0].casefold(),name['text'].casefold(),2)
                    or name['text'].casefold() in {'cancel','help','warning','continue','yes','exit','save','load'}):continue
            if any(not(x-2<=r['bounds'][0] and r['bounds'][0]+r['bounds'][2]<=x+w+2
                       and y-2<=r['bounds'][1] and r['bounds'][1]+r['bounds'][3]<=y+h+2)for r in a):continue
            if (not name['bounds'][0]+name['bounds'][2]<digit['bounds'][0]
                    or digit['center'][1]<=name['center'][1] or occluded_badge_bounds(image,digit) is None
                    or any(other is not old and any(_overlap(other,r)for r in a)for other in rows)):continue
            selected=(a,b,name);break
        if selected is None:continue
        a,b,name=selected
        for r in a:
            r['provenance']=old['provenance']+r['provenance']+(b[0]['provenance'] if r is name else [])
            r['merged_map_components']={'original_bounds':old['bounds'],'original_text':old['text'],
                                        'observed_components':[v['text']for v in a]}
        index=rows.index(old);rows[index:index+1]=a


def _recover_compound_map_label(image,rows,executable,directory,evidence):
    """Separate a label from colored artwork only when two masks read it.

    A native low-confidence row can include a unit sprite above/left of its
    city label. The discarded pixels must themselves be predominantly colored;
    the resulting letters still require known-city binding in the classifier.
    """
    if image.size!=(640,480):return
    menu={r['text'].casefold() for r in rows if r['bounds'][1]<35 and r['confidence']>=.8}
    if not {'game','kingdom','view','orders'}<=menu:return
    if any(r['text'].strip().casefold() in ('ok','cancel','yes','no','help') and r['center'][1]>40 for r in rows):return
    for index,old in enumerate(rows):
        x,y,w,h=old['bounds'];raw=old['text'].casefold()
        if not (8<=x and x+w<=456 and 70<=y and y+h<=440 and 24<h<=40 and 32<=w<=160
                and .3<=old['confidence']<=.5 and re.fullmatch(r'[^\s]{4,28}',raw)):continue
        source=image.crop((x,y,x+w,y+h)).convert('RGB')
        if sum(max(p)-min(p)>=24 for p in source.getdata())<w*h*.5:continue
        reads=[_crop_text(image,old,f'compound_map_{index}_white{threshold}',executable,directory,evidence,
                         padding=(3,3),white_threshold=threshold) for threshold in (190,240)]
        if any(len(reading)!=1 for reading in reads):continue
        a,b=reads[0][0],reads[1][0];name=a['text'].casefold()
        if (a['text']!=b['text'] or min(a['confidence'],b['confidence'])<.8 or not _same_location(a,b)
                or not re.fullmatch('[a-z]{3,25}',name) or name in {'cancel','help','warning','continue','yes','exit','save','load'}
                or not raw.endswith(name) or not 1<=len(raw)-len(name)<=3):continue
        cx,cy,cw,ch=a['bounds']
        if not (x<=cx and cx+cw<=x+w+2 and y+10<=cy and cy+ch<=y+h+2 and 10<=ch<=24
                and 0<=w-cw<=40 and not any(other is not old and _overlap(other,a) for other in rows)):continue
        discarded=[image.getpixel((px,py))[:3] for py in range(y,y+h) for px in range(x,x+w)
                   if not (cx<=px<cx+cw and cy<=py<cy+ch)]
        if not discarded or sum(max(p)-min(p)>=24 for p in discarded)<len(discarded)*.5:continue
        a['provenance']=old['provenance']+a['provenance']+b['provenance']
        a['provenance'][-1]['compound_map_artwork']={'original_bounds':old['bounds'],
            'discarded_pixels':len(discarded),'chromatic_pixels':sum(max(p)-min(p)>=24 for p in discarded)}
        rows[index]=a


def _recover_map_labels(image,rows,executable,directory,evidence):
    """Agreeing reads of one pixel region; city identity stays in the classifier.

    White-letter masks suppress colored map art. A second threshold or wider
    crop must independently agree before that reading replaces native OCR.
    """
    if image.size!=(640,480):return
    menu={r['text'].casefold() for r in rows if r['bounds'][1]<35 and r['confidence']>=.8}
    if not {'game','kingdom','view','orders'}<=menu:return
    if any(r['text'].strip().casefold() in ('ok','cancel','yes','no','help') and r['center'][1]>40 for r in rows):return
    for index,row in enumerate(rows):
        x,y,w,h=row['bounds']
        # At most two trailing non-letter picture glyphs may share the native
        # box. They are not stripped or interpreted; new text needs pixel proof.
        # A mixed-script OCR letter may identify a crop, never a replacement:
        # replacements below must still be two agreeing actual ASCII readings.
        if not (8<=x and x+w<=456 and 70<=y and y+h<=440 and 10<=h<=24 and 16<=w<=160
                and row['confidence']>=.3 and re.fullmatch(r'[^\W\d_]{3,25}[^\w\s]{0,2}',row['text'])):continue
        # Original010/2419 reads Cyrillic Р/о in Pompeii. These two measured
        # lookalikes affect only the comparison gate, never replacement text.
        # The actual replacement still needs two independent ASCII pixel reads.
        compared=row['text'].translate(str.maketrans({'Р':'P','о':'o'})).casefold()
        def credible(candidate):
            return (candidate['confidence']>=.8 and _same_location(row,candidate)
                    and re.fullmatch(r'[A-Za-z]{3,25}',candidate['text'])
                    and _near_text(compared,candidate['text'].casefold(),2))
        def read(suffix,*,retain=True,**kwargs):
            name=f'map_label_{index}{suffix}_{kwargs.get("scale",3)}x'
            try:
                result=_crop_text(image,row,name,executable,directory,evidence,**kwargs)
            except (OSError,ValueError,TypeError,subprocess.SubprocessError) as error:
                evidence.setdefault('fallback_errors',[]).append(dict(pass_name=name,
                                                                      error=type(error).__name__))
                return None
            if retain:
                for candidate in result:
                    if credible(candidate):row['provenance']+=candidate['provenance']
            return result[0] if len(result)==1 and credible(result[0]) else None
        def agree(first,second):
            return first is not None and second is not None and first['text']==second['text']
        a=read('',padding=(3,3));b=read('_gray',padding=(3,3),grayscale=True)
        pair=(a,b) if agree(a,b) else None
        if pair is None and row['confidence']<.8:
            peer=read('_wide_gray',padding=(6,6),grayscale=True)
            if agree(a,peer):pair=(a,peer)
        # RGB/gray can agree on the same wrong map-font reading. Two bounded
        # white-glyph framings remain independent evidence even in that case.
        # Publish neither new reading unless both agree; no city state enters
        # this reader, and previous raw readings are never discarded.
        pixels=list(image.crop((x,y,x+w,y+h)).convert('RGB').getdata())
        white_count=sum(min(pixel)>=230 for pixel in pixels)
        if white_count>=20 and white_count>=len(pixels)*.04:
            first=read('_white190',retain=False,padding=(3,3),white_threshold=190,scale=2)
            second=read('_white230',retain=False,padding=(2,2),white_threshold=230,scale=4)
            if agree(first,second) and _same_location(first,second):
                row['provenance']+=first['provenance']+second['provenance']
                if pair is None:pair=(first,second)
        if pair is None and white_count>=20:
            # Original012/1936's city lettering touches neighboring artwork.
            # Two distinct framings/scales must independently retain the same
            # complete label; neither a city table nor partial text supplies it.
            first=read('_white230_wide',retain=False,padding=(6,3),white_threshold=230,scale=2)
            second=read('_white230_tight',retain=False,padding=(2,2),white_threshold=230,scale=3)
            if agree(first,second) and _same_location(first,second):
                row['provenance']+=first['provenance']+second['provenance']
                pair=(first,second)
        if pair is None:
            whites=[]
            for suffix,padding,threshold in (('_white',(3,3),190),('_white_low',(3,3),160),('_white_wide',(6,6),190)):
                candidate=read(suffix,padding=padding,white_threshold=threshold)
                if candidate is None:continue
                peers=[old for old in [a,b,*whites] if agree(old,candidate)]
                if peers:
                    pair=(peers[0],candidate);break
                whites.append(candidate)
        if pair is not None:
            first,second=pair
            if _replace_crop_row(rows,index,[first],lambda old,new:bool(re.fullmatch(r'[A-Za-z]{3,25}',new))
                                 and _near_text(compared,new.casefold(),2)):
                rows[index]['provenance']+=second['provenance']


def _recover_moving_status(image,rows,executable,directory,evidence):
    """Read the fixed unit-pane heading twice; never infer a move or actor."""
    if image.size!=(640,480):return
    candidates=[(i,r) for i,r in enumerate(rows) if r['bounds'][0]>=475 and 245<=r['center'][1]<=268
                and r['bounds'][2]<=160 and r['confidence']>=.8 and re.fullmatch(r'[^\W\d_]+ [^\W\d_]+',r['text'])
                and _near_text(r['text'].casefold(),'moving units',6)]
    if len(candidates)!=1:return
    index,row=candidates[0]
    if row['text'].casefold()=='moving units':return
    first=_crop_text(image,row,'moving_status_3x',executable,directory,evidence,padding=(3,3))
    second=_crop_text(image,row,'moving_status_gray_3x',executable,directory,evidence,padding=(3,3),grayscale=True)
    valid=lambda a,b:(len(a)==len(b)==1 and a[0]['text']==b[0]['text']=='Moving Units'
                      and b[0]['confidence']>=.8 and _same_location(row,b[0]))
    if not valid(first,second):
        first=_crop_text(image,row,'moving_status_white190_3x',executable,directory,evidence,padding=(3,3),white_threshold=190)
        second=_crop_text(image,row,'moving_status_white230_3x',executable,directory,evidence,padding=(3,3),white_threshold=230)
        if (not valid(first,second) and len(second)==1 and second[0]['text']=='Moving Units'
                and second[0]['confidence']>=.8 and _same_location(row,second[0])):
            first=second
            second=_crop_text(image,row,'moving_status_white240_3x',executable,directory,evidence,padding=(3,3),white_threshold=240)
    if valid(first,second) and _replace_crop_row(rows,index,first,lambda old,new:True):
        rows[index]['provenance']+=second[0]['provenance']


def _recover_completion_zoom(image,rows,executable,directory,evidence):
    """An original notice label must be read exactly by two real pixel passes."""
    if image.size!=(640,480):return
    headings=[r for r in rows if r['text'].casefold()=='domestic advisor' and r['confidence']>=.8]
    if len(headings)!=1:return
    title=headings[0]
    buttons=[r for r in rows if r['text'].strip().casefold()=='ok' and r['center'][1]>title['center'][1]]
    if len(buttons)!=1:return
    choices=[r for r in rows if re.fullmatch(r'(?:[O0•○●]\s+)?(?:Zoom to City|Continue)',r['text'])]
    if (len(choices)==2 and {re.sub(r'^[O0•○●]\s+','',r['text']) for r in choices}=={'Zoom to City','Continue'}
            and not any(r['text'].casefold() in ('cancel','yes','no','help') for r in rows)):
        for index,row in enumerate(rows):
            matches=[m for m in re.finditer(r'(?<= )([A-Za-z]{4,7})(?= )',row['text'])
                     if _near_text(m[1],'builds',1)]
            if (len(matches)!=1 or matches[0][1]=='builds' or not row['text'].endswith('.') or row['confidence']<.8
                    or not title['center'][1]<row['center'][1]<min(c['center'][1] for c in choices)):continue
            match=matches[0];expected=row['text'][:match.start()]+'builds'+row['text'][match.end():]
            a=_crop_text(image,row,'completion_body_rgb3',executable,directory,evidence,padding=(3,3))
            b=_crop_text(image,row,'completion_body_gray3',executable,directory,evidence,padding=(3,3),grayscale=True)
            if (len(a)==len(b)==1 and a[0]['text']==b[0]['text']==expected
                    and min(a[0]['confidence'],b[0]['confidence'])>=.8
                    and _same_location(row,b[0]) and _same_location(a[0],b[0])):
                if _replace_crop_row(rows,index,a,lambda old,new:True):rows[index]['provenance']+=b[0]['provenance']
    for index,row in enumerate(rows):
        if not (title['center'][1]<row['center'][1]<buttons[0]['center'][1] and row['confidence']>=.8
                and row['text'].casefold()!='zoom to city' and _near_text(row['text'].casefold(),'zoom to city',2)):continue
        first=_crop_text(image,row,'completion_zoom_3x',executable,directory,evidence,padding=(6,6))
        second=_crop_text(image,row,'completion_zoom_gray_3x',executable,directory,evidence,padding=(6,6),grayscale=True)
        if len(first)!=1 or len(second)!=1:continue
        a,b=first[0],second[0]
        if (a['text']!=b['text'] and 'Zoom to City' in (a['text'],b['text'])
                and min(a['confidence'],b['confidence'])>=.8
                and all(_near_text(r['text'],'Zoom to City',1) and _same_location(row,r) for r in (a,b))):
            first=_crop_text(image,row,'completion_zoom_tight_3x',executable,directory,evidence,padding=(3,3))
            second=_crop_text(image,row,'completion_zoom_tight_gray_3x',executable,directory,evidence,padding=(3,3),grayscale=True)
            if len(first)!=1 or len(second)!=1:continue
            a,b=first[0],second[0]
        if a['text']!='Zoom to City' or b['text']!='Zoom to City' or b['confidence']<.8 or not _same_location(row,b):continue
        if _replace_crop_row(rows,index,first,lambda old,new:True):rows[index]['provenance']+=second[0]['provenance']


def _map_patch_colors(image, rows, source_hash):
    """Retain original-pixel evidence for tiny city-art OCR, at any confidence.

    Color cannot identify a city or authorize an input. The classifier still
    requires a known city label, exact map layout, geometry and no controls.
    Native dialog text/background is grayscale; these map sprites are colored.
    """
    if image.size!=(640,480):return
    for row in rows:
        x,y,w,h=row['bounds']
        tiny=8<=x and x+w<=456 and 70<=y and y+h<=440 and 1<=w<=96 and 1<=h<=40
        vertical_icons=110<=x and x+w<=160 and 98<=y and y+h<=375 and 1<=w<=24 and 40<h<=136
        if not (tiny or vertical_icons):continue
        pixels=list(image.crop((x,y,x+w,y+h)).convert('RGB').getdata())
        row['map_patch_colors']={'source_sha256':source_hash,'bounds':list(row['bounds']),
                                 'rgb_spread_threshold':24,'pixel_count':len(pixels),
                                 'chromatic_pixels':sum(max(p)-min(p)>=24 for p in pixels)}


def recognize(path: str | Path) -> dict:
    path = Path(path).resolve()
    executable = ROOT / '.runtime' / 'ocr'
    if not executable.is_file():
        raise RuntimeError('Build scripts/ocr.swift into .runtime/ocr first')
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as image:
        width, height = image.size
        rows = _prepare_rows(_run_ocr(executable, path), width, height, 'native')
        evidence = dict(passes=['native'], conflicts=[], fallback_errors=[],source_image_sha256=original_hash)
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
            if annotate_footer(image,rows,original_hash):
                evidence['passes'].append('exact_original_gray_footer_rgb_sha256')
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
            for recover in (_recover_history_rows,_recover_missing_history_rank,_recover_history_title,_recover_research_rows,_recover_exchange_advance_row,_recover_split_production_title,_recover_joined_production_title,_recover_city_and_production_rows,_recover_production_option_rows,_recover_city_caption_year,recover_caption_date,_recover_founded_production_title,_recover_city_section_labels,_recover_revolt_notice_title,_recover_revolution_title,_recover_name_city_title,_recover_governance_labels,recover_disband_warning,_recover_council_title,_recover_tax_context,_recover_locator_names,_recover_domestic_title,
                            _recover_stolen_advance_notice,_recover_capture_notice_title,_recover_civil_war_notice,recover_promotion_title,_recover_foreign_completion_title,_recover_saved_caption,_recover_acquisition_line,_recover_discovery_punctuation,_recover_production_change_prose,_recover_upgrade_boundaries,_recover_production_upgrade_city,_recover_support_notice,_recover_travellers_title,_recover_changed_wonder_tail,_recover_population_decrease_option,_recover_population_notice,_recover_map_menu_label,_recover_map_heading,_recover_status_population,_recover_treasury_marker,_recover_status_year,_recover_diplomacy_intro,_recover_audience_title_fragments,_recover_audience_radio,_recover_audience_body,_recover_withdrawal_warning,_recover_treaty_warning,_recover_treaty_reminder,_recover_intruder_notice,_recover_tech_demand_title,_recover_herald_title,_recover_gape_title,_recover_exchange_title,_recover_herald_panel,recover_quoted_herald,_recover_herald_options,_recover_cease_proposal,_recover_treaty_missing_ok,_recover_treaty_closing_rows,_recover_greeting_body,_recover_golden_age_city_line,_recover_crusade_title,_recover_crusade_tail,_recover_howdy_spacing,_recover_diplomacy_gift_row,_recover_gape_boundary,_recover_exchange_body,_recover_exchange_requested_advance,_recover_cancel_treaty_body,_recover_tribute_tail,recover_herald_paragraph,_recover_government_offer,_recover_fortress_order_body,_recover_masked_city_badge,_recover_merged_city_badge,_recover_compound_map_label,_recover_map_labels,_recover_moving_status,_recover_expanded_status,_recover_completion_zoom):
                try:
                    recover(image,rows,executable,directory,evidence)
                except (OSError,ValueError,TypeError,subprocess.SubprocessError) as error:
                    evidence['fallback_errors'].append(dict(pass_name=recover.__name__,error=type(error).__name__))
        _map_patch_colors(image,rows,original_hash)
        annotate_badges(image,rows,original_hash)
        annotate_production_titles(image,rows,original_hash)
        annotate_tax_controls(image,rows,original_hash)
        annotate_notice_icons(image,rows,original_hash)
        annotate_founding_frame(image,rows,original_hash)
    return {'width': width, 'height': height, 'sha256': original_hash,
            'lines': rows, 'text': '\n'.join(row['text'] for row in rows), 'ocr': evidence}


def find_text(observation, text, *, exact=False):
    wanted = text.casefold()
    matches = [row for row in observation['lines']
               if (row['text'].casefold() == wanted if exact else wanted in row['text'].casefold())]
    if len(matches) != 1:
        raise ValueError(f'Game text must match one visible line ({len(matches)} matches)')
    return matches[0]['center']
