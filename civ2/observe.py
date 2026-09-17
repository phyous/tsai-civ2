"""Original-game image observations; OCR is evidence, not a game-state oracle."""
from __future__ import annotations
import hashlib
from functools import lru_cache
import math
from pathlib import Path
import re
import subprocess
import tempfile
from PIL import Image
from .ocr_worker import run_ocr
from .map_badges import annotate_badges
from .tax_controls import annotate_tax_controls
from .notice_icons import annotate_notice_icons

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


def _crop_text(image, row, name, executable, directory, evidence, *, white=False, padding=(6,3), grayscale=False, white_threshold=None, scale=None):
    """Read actual row pixels again; preserve source coordinates and provenance."""
    x,y,w,h=row['bounds']
    px,py=padding
    box=(max(0,x-px),max(0,y-py),min(image.width,x+w+px),min(image.height,y+h+py))
    crop=image.crop(box);scale=(4 if white else 3) if scale is None else scale
    if type(scale) is not int or scale not in (2,3,4):raise ValueError('Unsupported bounded OCR scale')
    if white:crop=crop.point(lambda v:0 if v>=230 else 255).convert('L')
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
            (f'all RGB channels>={white_threshold} to black; bicubic enlargement' if white_threshold is not None else
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
    cleaned=text.strip().rstrip('|').strip()
    if cleaned.endswith('))'):cleaned=cleaned[:-1]
    return cleaned if re.fullmatch(r'\(\d+\s+(?:Turns?|Tums?)(?:,\s*ADM:\s*\d+/\d+/\d+\s+HP:\s*\d+/\d+)?\)',cleaned,re.I) else None


def _stat_numbers_compatible(old,new):
    previous,fresh=re.findall(r'\d+',old),re.findall(r'\d+',new)
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
            or not body[-1]['text'].casefold().endswith('exchange knowledge with us?"')):return
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


def _recover_treasury_marker(image,rows,executable,directory,evidence):
    """Recover a status layout marker; native memory/save remains the amount source."""
    if image.size!=(640,480):return
    pattern=r'[0-9ile,]{1,16}\s+(?:gold|cold)(?:\s+[0-9.]+)?'
    for index,old in enumerate(rows):
        x,y,w,h=old['bounds']
        if (not x>=470 or not 220<=y<=242 or w>168 or h>24
                or not re.search(r'\b(?:gold|cold)\b',old['text'],re.I)
                or re.fullmatch(pattern,old['text'].casefold())):continue
        readings=[_crop_text(image,old,'treasury_marker_'+name,executable,directory,evidence,
                            padding=(3,3),grayscale=gray) for name,gray in (('rgb3',False),('gray3',True))]
        a,b=readings
        if (len(a)!=1 or len(b)!=1 or a[0]['text']!=b[0]['text']
                or min(a[0]['confidence'],b[0]['confidence'])<.8
                or not _same_location(a[0],b[0]) or not _same_location(old,b[0])
                or not re.fullmatch(pattern,a[0]['text'].casefold())):continue
        if _replace_crop_row(rows,index,a,lambda before,after:True):rows[index]['provenance']+=b[0]['provenance']


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
    x,y,w,h=old['bounds'];readings=[]
    for pad,right in ((3,14),(2,16)):
        box=(x-pad,y-pad,min(640,x+w+right),min(480,y+h+pad));crop=image.crop(box)
        name='diplomacy_intro_black_3x_pad'+str(pad);target=Path(directory)/(name+'.png')
        crop.convert('L').point(lambda value:255 if value>70 else 0).resize(
            (crop.width*3,crop.height*3),Image.Resampling.BICUBIC).save(target)
        evidence['passes'].append(name);raw=_run_ocr(executable,target)
        if len(raw)!=1 or raw[0]['text']!='You respond: "We..."' or raw[0]['confidence']<.8:return
        local=_prepare_rows(raw,crop.width,crop.height,name)[0]
        nx,ny,nw,nh=local['provenance'][0]['normalized_bounds']
        mapped=_prepare_rows([dict(text=local['text'],confidence=local['confidence'],
            x=(box[0]+nx*crop.width)/640,y=(box[1]+ny*crop.height)/480,
            width=nw*crop.width/640,height=nh*crop.height/480)],640,480,name)[0]
        mapped['provenance'][0].update(crop=list(box),scale=3,normalized_crop_bounds=[nx,ny,nw,nh],
            transform='L<=70 retained black, others white; bicubic enlargement')
        if not _same_location(old,mapped):return
        readings.append(mapped)
    if not _same_location(*readings):return
    first,second=readings;first['provenance']=old['provenance']+first['provenance']+second['provenance']
    rows[rows.index(old)]=first


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


def _recover_city_and_production_rows(image, rows, executable, directory, evidence):
    """Narrow native city/list layouts; no rules names or dates are invented."""
    if image.size!=(640,480):return
    caption=r'^Ci(?:ty|sy|cy) of (.+?),\s*(\d{1,5})\s*(B\.?\s*C\.?|A\.?\s*D\.?)'
    for index,row in enumerate(rows):
        previous=re.match(caption,row['text'],re.I)
        if previous and 32<=row['bounds'][1]<=56 and row['confidence']>=.8:
            def same_caption(old,new):
                fresh=re.match(caption,new,re.I)
                same_name=bool(fresh and previous[1].casefold()==fresh[1].casefold())
                # The original N can be read as HT. A different name must be
                # read at two distinct scales and keep the observed date exact.
                name_ok=bool(fresh and (same_name or (_near_text(previous[1].casefold(),fresh[1].casefold(),2)
                                                     and previous[2]==fresh[2])))
                return bool(fresh and new.casefold().startswith('city of ') and name_ok
                    and _near_text(previous[2],fresh[2],1)
                    and re.sub(r'[^a-z]','',previous[3].casefold())==re.sub(r'[^a-z]','',fresh[3].casefold()))
            readings=[]
            for scale,padding in ((2,(3,3)),(3,(6,6)),(4,(6,6)),(4,(8,6))):
                suffix='_wide' if padding==(8,6) else ''
                first=_crop_text(image,row,f'city_caption_{scale}x{suffix}',executable,directory,evidence,padding=padding,scale=scale)
                second=_crop_text(image,row,f'city_caption_gray_{scale}x{suffix}',executable,directory,evidence,padding=padding,scale=scale,grayscale=True)
                if len(first)!=1 or len(second)!=1:continue
                a,b=first[0],second[0];ma,mb=re.match(caption,a['text'],re.I),re.match(caption,b['text'],re.I)
                identity=lambda m:(m[1].casefold(),m[2],re.sub('[^a-z]','',m[3].casefold()))
                if (not ma or not mb or identity(ma)!=identity(mb) or min(a['confidence'],b['confidence'])<.8
                        or not _same_location(row,a) or not _same_location(row,b)
                        or not same_caption(row['text'],a['text']) or not same_caption(row['text'],b['text'])):continue
                readings.append((identity(ma),a,b,scale))
                agrees=[v for v in readings if v[0]==identity(ma)]
                scales={v[3] for v in agrees}
                if len(scales)>=2:
                    selected=agrees[0][1]
                    selected['provenance']=[p for _,aa,bb,_ in readings for r in (aa,bb) for p in r['provenance']]
                    if _replace_crop_row(rows,index,[selected],same_caption):
                        rows[index]['caption_identity_consensus']={'independent_scales':len(scales),'year_text':ma[2]}
                    break
    # A damaged first word only permits re-reading the same title pixels. The
    # replacement must independently contain the actual original "What".
    titles=[r for r in rows if re.match(r'^wh(?:at|ait) shall (?:we|me) [a-z]{3,7} in .+',r['text'],re.I)
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
    heading=lambda text:re.fullmatch(r'what shall (?:we|me) ([a-z]{3,7}) in (.{1,60})',text.strip().rstrip('?'),re.I)
    old_heading=re.fullmatch(r'wh(?:at|ait) shall (?:we|me) ([a-z]{3,7}) in (.{1,60})',title['text'].strip().rstrip('?'),re.I)
    if old_heading and (not heading(title['text']) or not _near_text(old_heading[1].casefold(),'build',2)):
        for scale,padding in ((3,(6,6)),(2,(6,6)),(2,(3,3))):
            first=_crop_text(image,title,f'production_title_{scale}x',executable,directory,evidence,padding=padding,scale=scale)
            second=_crop_text(image,title,f'production_title_gray_{scale}x',executable,directory,evidence,padding=padding,grayscale=True,scale=scale)
            if len(first)==len(second)==1 and first[0]['text']==second[0]['text']:
                fresh=heading(first[0]['text'])
                if (fresh and fresh[2].casefold()==old_heading[2].casefold()
                        and _near_text(fresh[1].casefold(),'build',2)
                        and second[0]['confidence']>=.8 and _same_location(title,second[0])):
                    index=rows.index(title)
                    if _replace_crop_row(rows,index,first,lambda old,new:True):
                        rows[index]['provenance']+=second[0]['provenance'];title=rows[index];break
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
                and row['confidence']>=.5 and re.fullmatch(r'[^\W\d_]{3,25}[^\w\s]{0,2}',row['text'])):continue
        def credible(candidate):
            return (candidate['confidence']>=.8 and _same_location(row,candidate)
                    and re.fullmatch(r'[A-Za-z]{3,25}',candidate['text'])
                    and _near_text(row['text'].casefold(),candidate['text'].casefold(),2))
        def read(suffix,**kwargs):
            try:
                result=_crop_text(image,row,f'map_label_{index}{suffix}_3x',executable,directory,evidence,**kwargs)
            except (OSError,ValueError,TypeError,subprocess.SubprocessError) as error:
                evidence.setdefault('fallback_errors',[]).append(dict(pass_name=f'map_label_{index}{suffix}_3x',
                                                                      error=type(error).__name__))
                return None
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
                                 and _near_text(old.casefold(),new.casefold(),2)):
                rows[index]['provenance']+=second['provenance']


def _recover_moving_status(image,rows,executable,directory,evidence):
    """Read the fixed unit-pane heading twice; never infer a move or actor."""
    if image.size!=(640,480):return
    candidates=[(i,r) for i,r in enumerate(rows) if r['bounds'][0]>=475 and 245<=r['center'][1]<=268
                and r['bounds'][2]<=160 and r['confidence']>=.8 and re.fullmatch(r'[A-Za-z]+ [A-Za-z]+',r['text'])
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
    for index,row in enumerate(rows):
        if not (title['center'][1]<row['center'][1]<buttons[0]['center'][1] and row['confidence']>=.8
                and row['text'].casefold()!='zoom to city' and _near_text(row['text'].casefold(),'zoom to city',2)):continue
        first=_crop_text(image,row,'completion_zoom_3x',executable,directory,evidence,padding=(6,6))
        second=_crop_text(image,row,'completion_zoom_gray_3x',executable,directory,evidence,padding=(6,6),grayscale=True)
        if len(first)!=1 or len(second)!=1:continue
        a,b=first[0],second[0]
        if a['text']!='Zoom to City' or b['text']!='Zoom to City' or b['confidence']<.8 or not _same_location(row,b):continue
        if _replace_crop_row(rows,index,first,lambda old,new:True):rows[index]['provenance']+=b['provenance']


def _map_patch_colors(image, rows, source_hash):
    """Retain original-pixel evidence for tiny city-art OCR, at any confidence.

    Color cannot identify a city or authorize an input. The classifier still
    requires a known city label, exact map layout, geometry and no controls.
    Native dialog text/background is grayscale; these map sprites are colored.
    """
    if image.size!=(640,480):return
    for row in rows:
        x,y,w,h=row['bounds']
        if not (8<=x and x+w<=456 and 70<=y and y+h<=440
                and 1<=w<=96 and 1<=h<=40):continue
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
            for recover in (_recover_history_rows,_recover_city_and_production_rows,_recover_city_section_labels,_recover_revolution_title,_recover_governance_labels,_recover_tax_context,_recover_locator_names,_recover_domestic_title,
                            _recover_saved_caption,_recover_acquisition_line,_recover_treasury_marker,_recover_diplomacy_intro,_recover_herald_panel,_recover_exchange_body,_recover_government_offer,_recover_map_labels,_recover_moving_status,_recover_expanded_status,_recover_completion_zoom):
                try:
                    recover(image,rows,executable,directory,evidence)
                except (OSError,ValueError,TypeError,subprocess.SubprocessError) as error:
                    evidence['fallback_errors'].append(dict(pass_name=recover.__name__,error=type(error).__name__))
        _map_patch_colors(image,rows,original_hash)
        annotate_badges(image,rows,original_hash)
        annotate_tax_controls(image,rows,original_hash)
        annotate_notice_icons(image,rows,original_hash)
    return {'width': width, 'height': height, 'sha256': original_hash,
            'lines': rows, 'text': '\n'.join(row['text'] for row in rows), 'ocr': evidence}


def find_text(observation, text, *, exact=False):
    wanted = text.casefold()
    matches = [row for row in observation['lines']
               if (row['text'].casefold() == wanted if exact else wanted in row['text'].casefold())]
    if len(matches) != 1:
        raise ValueError(f'Game text must match one visible line ({len(matches)} matches)')
    return matches[0]['center']
