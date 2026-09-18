"""Conservative OCR classification for original Civ II native UI.

Only observed strings and their supplied centers become targets. No image-to-
coordinate guesses, model calls, mouse input, or invisible choices occur here.
OCR does not prove whether a control is enabled or which list row is selected.

Keyboard fallback must be a separate observed transaction: MENU.TXT specifies
V=Move/View Pieces, C=Center View, Shift+C=Find City, F1=City Status,
F6=Science Advisor and Ctrl+S=Save. In an identified native list, Home/arrow keys
can establish a selection, but re-observe before Enter. Do not infer list indices
from OCR order, particularly in multi-column production dialogs. Enter is only
mechanical for a recognized single-OK information screen or a verified nonempty
new-city default name. Unknown dialogs never authorize Enter or Escape.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from .native_events import EVENT_TITLES, classify_information
from .dates import DATE_PATTERN,city_date_match,date_key,date_parts
from .map_badges import proven_badge
from .tax_controls import proven_tax_arrows
from .exchange_picker import classify_exchange_picker
from .acquisition_notice import classify_acquisition_notice
from .production_change import classify_production_change
from .production_upgrade import classify_production_upgrade
from .history_notice import classify_history_notice
from .native_choices import classify_native_choice
from .foreign_report import classify_foreign_report
from .caravan import classify_caravan
from .native_map import evidence_for as native_map_evidence
from .gdi_titles import exact_production_title

CDROM_TEMPLATE_SHA256='28a50ae19b7eaf7abf51d1c97ab591c3f03abff2e7a19fc18dcb623914666fd7'


class DialogObservationError(ValueError):
    pass


def _normal(text):
    return ' '.join(unicodedata.normalize('NFKC',text).translate(str.maketrans({'“':'"','”':'"','’':"'",'‘':"'"})).casefold().split()).strip(' .:!?')


def _pattern(template):
    """A GAME.TXT placeholder matches observed text, never generates a choice."""
    text=_normal(template.replace('^',' '))
    pieces=re.split(r'(%string\d+|%number\d+)',text)
    return ''.join(r'.{1,180}?' if p.startswith('%string') else r'[0-9,+.\-]+' if p.startswith('%number') else re.escape(p) for p in pieces)


def _choice_pattern(template):
    pattern=_pattern(template)
    # A quoted option's variable may not swallow the closing quote and the
    # next, independently rendered quoted alternative.
    return pattern.replace(r'.{1,180}?',r'[^\"]{1,180}?') if _normal(template).startswith('"') else pattern


def dialog_resources(game_text):
    """Parse supplied original GAME.TXT into templates; no game assets bundled."""
    if not isinstance(game_text,str):raise TypeError('GAME.TXT must be text')
    sections={};current=None
    for raw in game_text.splitlines():
        line=raw.strip()
        if re.fullmatch(r'@[A-Z][A-Z0-9_]*',line):
            current=line[1:];sections[current]=[]
        elif current and not line.startswith(';') and not line.startswith('@@'):
            sections[current].append(line)
    result=[]
    for tag,lines in sections.items():
        title=next((s[7:] for s in lines if s.startswith('@title=')),None)
        if not title:continue
        width=next((int(s[7:]) for s in lines if re.fullmatch(r'@width=\d+',s)),None)
        content=[s for s in lines if not s.startswith('@')]
        while content and not content[0]:content.pop(0)
        while content and not content[-1]:content.pop()
        split=next((i for i,s in enumerate(content) if not s),len(content))
        body=' '.join(content[:split])
        options=[s for s in content[split+1:] if s]
        if tag=='DIPLOMACY':options=[s for s in sections.get('DIPLOMACYMENU',[]) if s and not s.startswith('@')]
        if tag=='TREATYMENU':options=[s for s in sections.get('TREATYOPTIONS',[]) if s and not s.startswith('@')]
        result.append(dict(tag=tag,title=title,width=width,body=body,options=options,
                           buttons=[s[8:] for s in lines if s.startswith('@button=')],
                           listbox=any(s.startswith('@listbox') for s in lines)))
    return result


def _rows(observation):
    if not isinstance(observation,dict):raise DialogObservationError('OCR observation must be an object')
    width,height=observation.get('width'),observation.get('height')
    if type(width) is not int or type(height) is not int or not 1<=width<=4096 or not 1<=height<=4096:
        raise DialogObservationError('Invalid image dimensions')
    if not isinstance(observation.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',observation['sha256']):
        raise DialogObservationError('An exact source-image hash is required')
    if not isinstance(observation.get('lines'),list) or len(observation['lines'])>1000:
        raise DialogObservationError('Invalid OCR lines')
    rows=[]
    for index,row in enumerate(observation['lines']):
        if not isinstance(row,dict) or not isinstance(row.get('text'),str):raise DialogObservationError('Invalid OCR row')
        text=row['text'].strip()
        if not text:continue
        center,bounds=row.get('center'),row.get('bounds')
        if not isinstance(center,(list,tuple)) or len(center)!=2 or any(type(v) is not int for v in center):
            raise DialogObservationError('An observed integer center is required')
        if not isinstance(bounds,(list,tuple)) or len(bounds)!=4 or any(type(v) is not int for v in bounds):
            raise DialogObservationError('Observed pixel bounds are required')
        x,y,w,h=bounds
        if w<=0 or h<=0 or x<0 or y<0 or x+w>width+1 or y+h>height+1 or not (0<=center[0]<width and 0<=center[1]<height):
            raise DialogObservationError('OCR geometry outside source image')
        if not x-1<=center[0]<=x+w+1 or not y-1<=center[1]<=y+h+1:
            raise DialogObservationError('OCR center does not belong to its text bounds')
        confidence=row.get('confidence',1.)
        if type(confidence) not in (int,float) or not math.isfinite(confidence) or not 0<=confidence<=1:
            raise DialogObservationError('Invalid OCR confidence')
        prepared=dict(text=text,normal=_normal(text),center=list(center),bounds=list(bounds),
                      source_line=index,confidence=confidence)
        production_proof=row.get('production_title_identity_consensus')
        if isinstance(production_proof,dict) and production_proof.get('requires_founding_notice') is True:
            prepared['production_founding_year']=production_proof.get('observed_year')
        if proven_badge(row,observation['sha256']):
            prepared['original_city_badge']=True
            prepared['original_city_badge_bounds']=list(row['map_badge_pixels']['bounds'])
        if (arrows:=proven_tax_arrows(row,observation['sha256'])):
            prepared['native_tax_arrows']=arrows
        colors=row.get('map_patch_colors')
        if (isinstance(colors,dict) and colors.get('source_sha256')==observation['sha256']
                and colors.get('bounds')==list(bounds) and colors.get('rgb_spread_threshold')==24
                and type(colors.get('pixel_count')) is int and colors['pixel_count']==w*h
                and type(colors.get('chromatic_pixels')) is int
                and 0<=colors['chromatic_pixels']<=w*h):
            prepared['chromatic_fraction']=colors['chromatic_pixels']/(w*h)
        provenance=row.get('provenance',[])
        if isinstance(provenance,list) and any(isinstance(p,dict) and str(p.get('preprocessing','')).startswith('map_label_') for p in provenance):
            readings=[]
            for p in provenance:
                if not isinstance(p,dict):continue
                mode=p.get('preprocessing','');coords=p.get('normalized_bounds')
                if (mode!='native' and not re.fullmatch(r'map_label_\d+(?:(?:_gray|_white|_wide_gray|_white_low|_white_wide)?_3x|_white190_2x|_white230_4x)',str(mode))):continue
                if (not isinstance(p.get('text'),str) or not re.fullmatch(r'[A-Za-z]{3,25}',p['text'])
                        or type(p.get('confidence')) not in (int,float) or not .8<=p['confidence']<=1
                        or not isinstance(coords,list) or len(coords)!=4
                        or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in coords)):continue
                px,py,pw,ph=coords;cx=(px+pw/2)*width;cy=(py+ph/2)*height
                # Vision's normalized boxes can place an exact integer edge a
                # few 1e-8 pixels beyond it after scaling back to the source.
                if abs(cx-center[0])<=6+1e-6 and abs(cy-center[1])<=4+1e-6 and pw*width<=w+12+1e-6 and ph*height<=h+8+1e-6:
                    readings.append(_normal(p['text']))
            if readings:prepared['same_pixel_map_readings']=readings
        rows.append(prepared)
    return sorted(rows,key=lambda r:(r['bounds'][1],r['bounds'][0]))


def _option(row,control):
    return dict(text=row['text'],center=list(row['center']),control=control,
                source_line=row['source_line'],confidence=row['confidence'],enabled=None)


def _unique(rows):
    return len({_normal(r['text']) for r in rows})==len(rows) and len({tuple(r['center']) for r in rows})==len(rows)


def _edit_distance(a,b):
    previous=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        current=[i]
        for j,cb in enumerate(b,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(ca!=cb)))
        previous=current
    return previous[-1]


def _saved_city_name(raw_name,state):
    """Resolve only a unique exact/one-edit owned SAV identity, never a new city."""
    if not isinstance(state,dict) or not isinstance(raw_name,str) or len(_normal(raw_name))<3:
        return None
    from .revision import observation_digest
    try: digest=observation_digest(state)
    except ValueError:return None
    player=state.get('player',{}).get('id')
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest) or type(player) is not int:
        return None
    owned=[c for c in state.get('cities',[]) if isinstance(c,dict) and c.get('owner')==player
           and all(type(c.get(k)) is int for k in ('id','owner','x','y'))
           and isinstance(c.get('name'),str)]
    exact=[c for c in owned if _normal(c['name'])==_normal(raw_name)]
    if exact:return exact[0] if len(exact)==1 else None
    near=[c for c in owned if _edit_distance(_normal(c['name']),_normal(raw_name))==1]
    return near[0] if len(near)==1 else None


def _recent_founded_name(raw_name,year_text,state):
    """A same-year native founding notice binds a label, never a SAV actor."""
    if not isinstance(state,dict) or not isinstance(raw_name,str) or len(_normal(raw_name))<3:return None
    if date_parts(year_text) is None:return None
    notices=state.get('recent_founding_notices',[])
    if not isinstance(notices,list) or len(notices)>4:return None
    year=date_key(year_text);matches=[]
    for notice in notices:
        if (not isinstance(notice,dict) or notice.get('source_tag')!='FOUNDED'
                or not re.fullmatch('[a-f0-9]{64}',str(notice.get('image_sha256','')))
                or not isinstance(notice.get('name'),str) or not 3<=len(notice['name'])<=60
                or not isinstance(notice.get('year_text'),str)
                or date_key(notice['year_text'])!=year):continue
        if _edit_distance(_normal(raw_name),_normal(notice['name']))<=1:matches.append(notice)
    return matches[0] if len(matches)==1 else None


def _clipped_city_label(row,state):
    """A viewport-edge fragment is layout only, never a reconstructed actor.

    Original005/1189 clips Antium to 'ium' against the map's left border.
    Require a unique strict suffix/prefix of an already observed city name.
    """
    from .revision import observation_digest
    try: observation_digest(state)
    except (ValueError,TypeError):return False
    text=row['normal'];x,y,w,h=row['bounds']
    if (row['confidence']<.8 or not re.fullmatch('[a-z]{3,25}',text)
            or text in {'yes','exit','help','buy','next','back','auto','done','save','load','menu','quit','warning'}
            or not 70<=y<=440 or not 1<=h<=24 or not 1<=w<=160):return False
    left=0<=x<=8;right=452<=x+w<=460
    if left==right:return False
    names={_normal(c['name']) for key in ('cities','known_cities') for c in state.get(key,[])
           if isinstance(c,dict) and isinstance(c.get('name'),str)
           and all(type(c.get(k)) is int for k in ('x','y'))}
    matches={name for name in names if len(name)>len(text)
             and (name.endswith(text) if left else name.startswith(text))}
    return len(matches)==1


def _production_stat(text):
    return bool(re.fullmatch(r'\(\d+\s+(?:turns?|tums?)(?:,\s*adm:\s*\d+/\d+/\d+\s+hp:\s*\d+/\d+)?\)',text))


def _production_icon_rows(body, names):
    """Colored original artwork left of a fully read production label/stat pair.

    The color fraction was validated against this observation's image hash in
    _rows. It cannot identify an option or supply missing text.
    """
    labels=[r for r in body if r['normal'] in names and r['confidence']>=.8]
    stats=[r for r in body if _production_stat(r['normal']) and r['confidence']>=.8]
    icons=[]
    for row in body:
        x,y,w,h=row['bounds']
        if (row in labels or row in stats or row['confidence']>=.5
                or row.get('chromatic_fraction',0)<.5 or not 1<=w<=68 or not 1<=h<=20
                or not re.fullmatch(r'[A-Za-z0-9]{1,12}',row['text'])
                or row['normal'] in {'ok','no','yes','help','cancel','buy','exit','auto','done'}):continue
        paired=[r for r in labels if 2<=r['bounds'][0]-(x+w)<=48
                and abs(r['center'][1]-row['center'][1])<=8
                and any(s['bounds'][0]>r['bounds'][0]+r['bounds'][2]
                        and abs(s['center'][1]-r['center'][1])<=8 for s in stats)]
        if len(paired)==1:icons.append(row)
    return icons


def _city_sprite_text(row, labels):
    """Recognize bounded fragments on a known city's colored sprite.

    The Rome icons at006/34 and005/295 were read as 'ОБ П' and 'Wu Fom 1'
    (confidence.30), directly above the independently read Rome label. This is artwork evidence,
    not a city statistic, unit, menu option or reconstructed text.
    """
    glyphs=''.join(row['text'].split())
    translated=row['text'].translate(str.maketrans({'О':'O','К':'K'}))
    words=_normal(''.join(c if c.isalnum() or c.isspace() else ' ' for c in translated)).split()
    controls={'ok','no','yes','exit','help','next','back','buy','auto','cancel','done','name','save','load','menu','quit','warning'}
    if ((row['confidence']>=.5 and row.get('chromatic_fraction',0)<.5) or not 1<=len(glyphs)<=8
            or not any(c.isalnum() for c in glyphs)
            or (any(not c.isalnum() and c not in '()[]|/' for c in glyphs)
                and row.get('chromatic_fraction',0)<.5)
            or any(word in controls for word in words) or ''.join(words) in controls):
        return False
    x,y,w,h=row['bounds']
    if not 1<=w<=96 or not 1<=h<=40:return False
    return any(abs(row['center'][0]-label['center'][0])<=32
               and 12<=label['center'][1]-row['center'][1]<=36
               and -8<=label['bounds'][1]-(y+h)<=12 for label in labels)


def _owned_city_size_sprite(row, labels, state):
    """Corroborate a tiny icon+badge OCR fragment against a saved owned city.

    Original006/440 reads the Rome sprite and its size2 badge as high-confidence
    'Bi 2'. The prefix and badge have no decoded semantic value. Growth or
    Settler completion can change the badge since the last save; only the next
    native save establishes current size. Ordinary text stays unrecognized.
    """
    match=re.fullmatch(r'([A-Za-z]{1,2})\s+(\d{1,2})',row['text'])
    if (not match or match[1].casefold() in {'ok','no','go'} or row['confidence']<.8
            or not 1<=row['bounds'][2]<=48 or not 1<=row['bounds'][3]<=20):
        return False
    player=state.get('player',{}).get('id')
    from .revision import observation_digest
    try: digest=observation_digest(state)
    except ValueError:return False
    if (type(player) is not int or not isinstance(digest,str)
            or not re.fullmatch('[0-9a-f]{64}',digest)):
        return False
    size=int(match[2])
    names={_normal(city['name']) for city in state.get('cities',[])
           if isinstance(city,dict) and city.get('owner')==player
           and isinstance(city.get('name'),str) and type(city.get('size')) is int
           and 1<=size<=99}
    x,y,w,h=row['bounds']
    return any(label['normal'] in names
               and 0<=row['center'][0]-label['center'][0]<=24
               and 12<=label['center'][1]-row['center'][1]<=28
               and -2<=label['bounds'][1]-(y+h)<=10 for label in labels)


def _city_badge_text(row,labels):
    if (not row.get('original_city_badge') or row['confidence']<.8
            or not re.fullmatch(r'[1-9][0-9]?',row['text'])):return False
    # OCR may include nearby artwork in a numeric row's box. Its unique
    # hash-bound13px badge raster, rather than the oversized OCR box, locates
    # the layout element; no population value is inferred from it.
    x,y,w,h=row['original_city_badge_bounds']
    return any(abs(x+w/2-label['center'][0])<=32
               and 14<=label['center'][1]-(y+h/2)<=30
               and -2<=label['bounds'][1]-(y+h)<=12 for label in labels)


def _native_map_kind(rows, observation, state, native_map_context=None):
    """Recognize the observed 640x480 Roman map layout, never a generic backdrop.

    The map does not display the government. Fixed pane geometry plus independent
    native status markers replace that invalid assumption. The few OCR aliases
    below are measured in unchanged original screenshots (Map→Hap, World→Workd,
    Units→Uhits), not general fuzzy matching. Unexpected text over the left map
    rejects even a dialog whose title or OK button OCR is corrupted.
    """
    if (observation['width'],observation['height']) != (640,480) or not isinstance(state,dict):
        return None, 'Native map layout requires the original 640x480 image and known player state'
    player=state.get('player',{})
    roman=(player.get('tribe_id')==0 or _normal(player.get('tribe') or '') in ('roman','romans','rome'))
    if not roman:
        return None, 'Native map title is not bound to the known Roman player'
    menu=' '.join(r['normal'] for r in rows if 18<=r['center'][1]<=38)
    if not all(re.search(r'\b'+word+r'\b',menu) for word in ('game','kingdom','view','orders','advisors','civilopedia')):
        return None, 'Native map menu row is incomplete'
    map_titles=[r for r in rows if 140<=r['center'][0]<=320 and 40<=r['center'][1]<=64
                and r['normal'] in ('roman map','roman hap')]
    worlds=[r for r in rows if 500<=r['center'][0]<=610 and 40<=r['center'][1]<=64
            and r['normal'] in ('world','workd','workl','work')]
    if len(map_titles)!=1 or len(worlds)!=1:
        return None, 'Native map and world pane titles are incomplete'
    status=[r for r in rows if r['bounds'][0]>=466 and 175<=r['center'][1]<=246]
    people=[r for r in status if re.fullmatch(r'[0-9,]+\s+people',r['normal'])]
    years=[r for r in status if date_parts(r['normal']) is not None]
    # Original narrow status-font 1 is observed as I/l and 5 as E. This is only a pane
    # layout marker, never an OCR-derived treasury value; economy comes from SAV.
    gold=[r for r in status if re.fullmatch(r'[0-9ile,]{1,16}\s+(?:gold|cold)(?:\s+[0-9.]+)?',r['normal'])]
    if len(people)!=1 or len(years)!=1 or len(gold)!=1:
        return None, 'Native population, year and treasury status markers are incomplete'
    if any(r['confidence']<.8 for r in map_titles+worlds+people+years+gold):
        return None, 'Native map pane or status text has low OCR confidence'
    # City labels legitimately appear over the playfield. Only names already in
    # the supplied owned/remembered observation qualify; no unseen city is inferred.
    city_names={_normal((_saved_city_name(c['name'],state) or _recent_founded_name(c['name'],years[0]['text'],state) or c)['name'])
                for key in ('cities','known_cities') for c in state.get(key,[])
                if isinstance(c,dict) and isinstance(c.get('name'),str)}
    def city_label(row):
        if _clipped_city_label(row,state):return True
        readings={row['normal'],*row.get('same_pixel_map_readings',[])}
        readings.update(_normal(c['name']) for text in list(readings)
                        if text not in {'ok','cancel','help','exit','buy','yes','no','next','back','auto','done','save','load','menu','quit','warning'}
                        and (c:=_saved_city_name(text,state)) is not None)
        readings.update(_normal(n['name']) for text in list(readings)
                        if (n:=_recent_founded_name(text,years[0]['text'],state)) is not None)
        matches={name for name in city_names if any(re.fullmatch(re.escape(name)+r'(?:\s+\(?\d+\)?)?',reading) for reading in readings)}
        return len(matches)==1
    labels=[r for r in rows if r['bounds'][1]>=65 and r['bounds'][0]<462
            and r['confidence']>=.8 and city_label(r)]
    map_proof = native_map_evidence(native_map_context, observation)
    if map_proof and any(r['bounds'][1]>=65 and r['bounds'][0]<462 and r['normal'] in
                        {'ok','cancel','yes','no','help','close','continue','back','next','done','exit',
                         'save','load','buy','change','auto'} for r in rows):
        return None, 'Possible unrecognized modal or open menu'
    for r in rows:
        if r['bounds'][1]>=65 and r['bounds'][0]<462:
            if (not map_proof and r not in labels and not _city_sprite_text(r,labels)
                    and not _owned_city_size_sprite(r,labels,state) and not _city_badge_text(r,labels)):
                return None, 'Unexpected text over the native map playfield; possible unrecognized modal'
    full=' '.join(r['normal'] for r in rows)

    if re.search(r'\b(?:select|choose|emissary|confirmation|warning|please|options|really|are you sure)\b',full):
        return None, 'Possible unrecognized modal or open menu'
    end=[r for r in rows if r['normal']=='end of turn' and r['bounds'][0]>=466 and 175<=r['center'][1]<=465]
    moving=[r for r in rows if r['bounds'][0]>=466 and 245<=r['center'][1]<=282
            and re.fullmatch(r'(?:moving|moring) (?:units|uhits)',r['normal'])]
    if len(end)==1 and end[0]['confidence']>=.8:
        return 'end_turn', 'Original end-of-turn indicator in the verified native map layout; no automatic input'
    if len(moving)==1 and moving[0]['confidence']>=.8 and not end:
        return 'normal_map', 'Original Roman map pane layout and status markers; actor still requires a fresh save'
    return None, 'Native moving-unit or end-of-turn status is not uniquely observed'


def _civilopedia_reference(rows, observation, rules):
    """Recognize the measured native advance-reference layout, never a modal.

    Body text remains evidence only. In particular, an OCR parenthetical such
    as ``(with Masonty)`` is not corrected or used as a technology requirement.
    Only the observed EXIT control is authorized by this classification.
    """
    if not any(r['normal']=='advances menu' for r in rows):
        return None
    failure={'reason':'Civilopedia reference title, panels or controls are incomplete or ambiguous'}
    if (observation['width'],observation['height'])!=(640,480) or not isinstance(rules,dict):
        return failure
    top=[r for r in rows if r['bounds'][1]<50]
    if len(top)!=1 or not 230<=top[0]['center'][0]<=410 or not 10<=top[0]['center'][1]<=40:
        return failure
    title=top[0]
    matches=[advance for advance in rules.get('advances',[])
             if isinstance(advance,dict) and isinstance(advance.get('name'),str)
             and type(advance.get('id')) is int and _normal(advance['name'])==title['normal']]
    if len(matches)!=1:
        return failure
    controls={}
    zones={'advances menu':(85,290),'description':(305,420),'exit':(440,555)}
    for name,(left,right) in zones.items():
        found=[r for r in rows if r['normal']==name]
        if (len(found)!=1 or not left<=found[0]['bounds'][0]
                or found[0]['bounds'][0]+found[0]['bounds'][2]>right
                or not 445<=found[0]['center'][1]<=468):
            return failure
        controls[name]=found[0]
    if len([r for r in rows if r['bounds'][1]>=432])!=3:
        return failure
    allows=[r for r in rows if r['normal']=='allows' and 328<=r['bounds'][0]<430
            and 55<=r['center'][1]<=85]
    repeated=[r for r in rows if r['normal']==title['normal'] and 250<=r['center'][1]<=390
              and 210<=r['center'][0]<=430]
    if len(allows)!=1 or len(repeated)!=1:
        return failure
    used={r['source_line'] for r in [title,allows[0],*controls.values()]}
    reference_names={_normal(item['name']) for table in ('advances','units','improvements')
                     for item in rules.get(table,[]) if isinstance(item,dict) and isinstance(item.get('name'),str)}
    for r in rows:
        x,y,w,h=r['bounds']
        if r['confidence']<.8 or x<64 or x+w>576:
            return failure
        if r['source_line'] in used:
            continue
        # Upper-left illustration letters are pixels from the original art,
        # not controls. All other body labels must occupy their original panels.
        artwork=(68<=x and x+w<=314 and 52<=y and y+h<=240
                 and 1<=len(r['text'])<=12 and r['text'].isalpha() and r['text'].isupper()
                 and r['normal'] not in ('ok','yes','no','cancel','help','close'))
        entry=re.fullmatch(r'(.+?)(?:\s+\(with [a-z ]{1,60}\))?',r['normal'])
        allowed=(328<=x and x+w<=572 and 85<=y and y+h<=238
                 and entry is not None and entry[1] in reference_names)
        chart=(68<=x and x+w<=572 and 248<=y and y+h<=390 and r['normal'] in reference_names)
        category=(435<=x and x+w<=565 and 394<=y and y+h<=428
                  and bool(re.fullmatch(r'[a-z]{3,20}',r['normal'])))
        if not (artwork or allowed or chart or category):
            return failure
    return {'title':title,'advance':matches[0],'controls':list(controls.values()),
            'exit':controls['exit'],'body':[r['text'] for r in rows if r['source_line'] not in used],
            'anchor_lines':[r['source_line'] for r in [title,allows[0],repeated[0],*controls.values()]]}


def _city_layout_without_unit_captions(rows, observation, missing):
    """Identify the original city pane when unit collections omit their captions.

    This supplies layout evidence only. It does not infer the absent caption,
    city statistics, a control's enabled state, or the absence of arbitrary
    windows. The caller retains all existing foreground-modal guards.
    """
    if (observation['width'], observation['height']) != (640, 480):
        return None
    if any(r['normal'].startswith(('units sup','units pres'))
           and r['normal'] not in ('units supported','units present') for r in rows):
        return None  # A clipped caption can be an occluded background window.
    titles=[r for r in rows if 32<=r['bounds'][1]<=56 and r['confidence']>=.8
            and city_date_match(r['text'])]
    if len(titles)!=1:
        return None
    # Native 640x480 pane regions, corroborated by the actual original labels.
    regions={
        'food storage':(440,58,639,90), 'citizens':(5,92,202,130),
        'city resources':(202,92,438,130), 'resource map':(5,235,202,268),
        'city improvements':(5,342,194,375),
        'buy':(444,235,514,267), 'change':(560,235,639,267),
        'info':(463,420,518,446), 'map':(520,420,577,446),
        'rename':(579,420,639,446), 'happy':(463,447,518,479),
        'view':(520,447,577,479), 'exit':(579,447,639,479),
    }
    # The native collection layout can use the caption space for additional
    # unit rows. An absent caption is not an absent or empty unit collection.
    optional={'unitssupported':('units supported',(5,266,202,303)),
              'unitspresent':('units present',(202,266,438,303))}
    for key,(label,region) in optional.items():
        if key not in missing:regions[label]=region
    anchors={}
    for label,(left,top,right,bottom) in regions.items():
        matches=[r for r in rows if r['normal'].replace(' ','')==label.replace(' ','') and r['confidence']>=.8
                 and left<=r['center'][0]<=right and top<=r['center'][1]<=bottom]
        if len(matches)!=1:
            return None
        anchors[label]={key:matches[0][key] for key in ('text','center','bounds','source_line')}
    absent=[label.title() for key,(label,_) in optional.items() if key in missing]
    return {'source':'Complete original city pane: exact title, stable section labels and eight city controls in their native regions',
            'source_sha256':observation['sha256'], 'missing_captions':absent,
            **({'missing_caption':absent[0]} if len(absent)==1 else {}),
            'title_source_line':titles[0]['source_line'], 'observed_anchors':anchors}


def classify_dialog(observation, *, rules=None, game_text=None, labels_text=None, state=None, native_map_context=None):
    """Return supported/unknown classification with exact visible option targets.

    ``options`` contains decision choices; ``buttons`` contains observed native
    auxiliary controls. Do not dispatch from a result with supported=False.
    Terminal text is a cue for human verification, not an automatic victory.
    """
    rows=_rows(observation);width,height=observation['width'],observation['height']
    result=dict(id='unknown',kind='unknown',supported=False,title='',width=width,height=height,
                sha256=observation['sha256'],options=[],buttons=[],requires_model=False,
                visible_text='\n'.join(r['text'] for r in rows),
                mechanical_action=None,outcome=None,reason='No unambiguous supported original screen',
                evidence=dict(source='original screenshot OCR',enabled_state='not established by OCR',
                              option_scope='visible labels only; not a complete scrollable menu'))
    def finish(kind,title,choices=(),buttons=(),*,model=False,mechanical=None,outcome=None,reason=None):
        if not _unique(list(choices)) or not _unique(list(buttons)):
            return unknown('Duplicate option text or centers are ambiguous',kind,title)
        result.update(id=kind,kind=kind,supported=True,title=title,options=list(choices),buttons=list(buttons),
                      requires_model=model,mechanical_action=mechanical,outcome=outcome,reason=reason)
        return result
    def unknown(reason,kind='unknown',title=''):
        result.update(kind=kind,title=title,supported=False,options=[],buttons=[],reason=reason)
        return result
    def single_title(pattern):
        return [r for r in rows if re.fullmatch(pattern,r['normal'])]
    def body_rows(title,button_names,dialog_width=440):
        # Only observed geometry: rows below the title and above the lowest
        # native button row. Column order is not interpreted as keyboard order.
        half=max(dialog_width/2,title['bounds'][2]/2+12)
        below=[r for r in rows if r['bounds'][1]>title['bounds'][1]+title['bounds'][3]-2
               and abs(r['center'][0]-title['center'][0])<=half]
        buttons=[r for r in below if r['normal'] in button_names]
        if not buttons:return [],[],None
        bottom=max(r['center'][1] for r in buttons)
        bottom_buttons=[r for r in buttons if abs(r['center'][1]-bottom)<=18]
        limit=min(r['bounds'][1] for r in bottom_buttons)
        return [r for r in below if r['bounds'][1]+r['bounds'][3]<=limit+2],bottom_buttons,limit
    full=' '.join(r['normal'] for r in rows)
    # Original optional-media notice can reappear when a movie is requested.
    # Its default OK continues this session without media; Repeat Search is
    # auxiliary. Pin the complete original resource, not a generic Please Note.
    if game_text and (width,height)==(640,480):
        media=[t for t in dialog_resources(game_text) if t['tag']=='CDROMNOTFOUND'
               and hashlib.sha256(json.dumps(t,sort_keys=True).encode()).hexdigest()==CDROM_TEMPLATE_SHA256]
        headings=[r for r in rows if r['normal'] in ('please note','please lfote') and r['confidence']>=.8]
        if len(media)==len(headings)==1:
            title=headings[0];body,controls,_=body_rows(title,{'ok','repeat search','cancel','yes','no'},320)
            global_controls=[r for r in rows if r['normal'] in ('ok','repeat search','cancel','yes','no')]
            def media_text(text):
                text=_normal(text)
                # Measured009/589 product-title glyphs and quote punctuation;
                # all other words in the full original paragraph stay exact.
                text=re.sub(r'\b(?:civilization (?:iit|i)|ciyilization ii)\b','civilization ii',text)
                return text.replace('"\'repeat search"','"repeat search"')
            if (len(controls)==2 and {r['normal'] for r in controls}=={'repeat search','ok'}
                    and controls==global_controls and all(r['confidence']>=.8 for r in body+controls)
                    and abs(controls[0]['center'][1]-controls[1]['center'][1])<=4
                    and abs(sum(r['center'][0] for r in controls)/2-title['center'][0])<=8
                    and media_text(' '.join(r['text'] for r in body))==media_text(media[0]['body'])):
                buttons=[_option(r,'button') for r in controls];ok=[r for r in buttons if _normal(r['text'])=='ok']
                result['resource_tag']='CDROMNOTFOUND'
                result['evidence']['cdrom_notice']={'source':'Complete original GAME.TXT CDROMNOTFOUND optional-media notice',
                    'template_sha256':CDROM_TEMPLATE_SHA256,'title_source_line':title['source_line'],
                    'body_source_lines':[r['source_line'] for r in body],
                    'observed_body':'\n'.join(r['text'] for r in body)}
                return finish('information',title['text'],ok,buttons,mechanical='acknowledge_information',
                              reason='Continue without optional CD multimedia using the original default OK')
    # Original tax scrollbars expose six observed arrow buttons, not a guessed
    # percentage-to-pixel mapping. One model click is followed by a fresh read.
    tax_labels={'How Shall We Distribute The Wealth','Government','Maximum Rate','Taxes','Science','Luxuries','Lock'}
    if isinstance(labels_text,str) and tax_labels<=set(labels_text.splitlines()) and (width,height)==(640,480):
        titles=[r for r in rows if 90<=r['center'][1]<=125 and 280<=r['center'][0]<=350
                and r['confidence']>=.8 and _edit_distance(r['normal'],'how shall we distribute the wealth')<=4]
        contexts=[(r,m) for r in rows if (m:=re.fullmatch(r'government: (anarchy|despotism|monarchy|communism|fundamentalism|republic|democracy) maximum rate: (\d{1,3})%',r['normal']))
                  and r['confidence']>=.8 and 120<=r['center'][1]<=160]
        rates=[(r,m) for r in rows if (m:=re.fullmatch(r'(taxes|science|luxuries):\s*(\d{1,3})%',r['normal']))
               and r['confidence']>=.8 and 'native_tax_arrows' in r]
        buttons=[r for r in rows if r['normal'] in {'ok','cancel','yes','no','help','done','exit'}]
        if (len(titles)==len(contexts)==1 and len(rates)==3 and {m[1] for _,m in rates}=={'taxes','science','luxuries'}
                and len(buttons)==1 and buttons[0]['normal']=='ok'
                and 300<=buttons[0]['center'][0]<=340 and 350<=buttons[0]['center'][1]<=385):
            limit=int(contexts[0][1][2]);values={m[1]:int(m[2]) for _,m in rates}
            panel=[r for r in rows if 118<=r['bounds'][0] and r['bounds'][0]+r['bounds'][2]<=520
                   and 125<=r['center'][1]<=350]
            markers=[r for r in panel if r not in [contexts[0][0],*[r for r,_ in rates]]]
            def marker_ok(row):
                if re.fullmatch(r'(?:0|100)%|l?lock|total income: \d+(?: total cost: \d+)?|total cost: \d+|discoveries: \d+ turns?',row['normal']):return True
                # A '+' OCR read on the right-arrow glyph remains pixel-proven
                # artwork. It does not create an eighth control.
                x,y,w,h=row['bounds']
                return row['text'] in ('+','<','>','←','→') and any(
                    bx<=x and by<=y and x+w<=bx+bw and y+h<=by+bh
                    for rate,_ in rates for arrow in rate['native_tax_arrows']
                    for bx,by,bw,bh in [arrow['bounds']])
            if (limit in range(0,101,10) and sum(values.values())==100
                    and all(v in range(0,limit+1,10) for v in values.values())
                    and all(marker_ok(r) and r['confidence']>=.8 for r in markers)
                    and len([r for r in markers if r['normal']=='0%'])==3
                    and len([r for r in markers if r['normal']=='100%'])==3):
                options=[]
                for row,match in rates:
                    for arrow in row['native_tax_arrows']:
                        direction=arrow['direction'];verb='decrease' if direction=='left' else 'increase'
                        options.append(dict(text=f"{row['text']} — {direction} arrow (attempt {verb})",
                            center=arrow['center'],control='button',source_line=row['source_line'],
                            confidence=row['confidence'],enabled=None,
                            observed_glyph={'direction':direction,'bounds':arrow['bounds']}))
                ok=_option(buttons[0],'button');options.append(ok)
                result['tax_allocation']={'government':contexts[0][1][1],'maximum_rate':limit,'rates':values,
                    'semantics':'Each arrow attempts one native adjustment; the game enforces limits and redistributes other rows. Reobserve after every click; OK confirms.'}
                result['evidence']['tax_controls']={'source':'Original LABELS.TXT and six exact 17x17 scrollbar-arrow pixel patterns',
                    'labels_sha256':hashlib.sha256(labels_text.encode('utf-8')).hexdigest(),
                    'source_image_sha256':observation['sha256']}
                return finish('tax_allocation',titles[0]['text'],options,[ok],model=True)
    # Original untitled @THRONE notice. Only dismiss its complete narrative;
    # this does not choose a decoration on the following interactive screen.
    throne = re.search(r'(?ms)^@THRONE\s*\n(.*?)(?=^@|\Z)', game_text or '')
    prompt = [r for r in rows if r['normal']=='(click mouse to continue...)']
    if throne and len(prompt)==1 and (width,height)==(640,480):
        notice = [r for r in rows if r is not prompt[0]]
        expected = _normal(' '.join(line.strip() for line in throne[1].splitlines() if line.strip()))
        if (len(expected)>80 and notice
                and _normal(' '.join(r['text'] for r in notice))==expected
                and all(r['confidence']>=.8 and 60<=r['bounds'][0]
                        and r['bounds'][0]+r['bounds'][2]<=580
                        and 90<=r['center'][1]<=310 for r in notice)
                and prompt[0]['confidence']>=.8
                and 280<=prompt[0]['center'][0]<=360 and 450<=prompt[0]['center'][1]<=476
                and not observation.get('ocr',{}).get('conflicts')):
            button=_option(prompt[0],'button')
            result['resource_tag']='THRONE'
            result['acknowledgement_point']=list(notice[0]['center'])
            result['presentation_scope']='Dismiss the original notice only; no decoration or gameplay choice'
            result['evidence']['template_sha256']=hashlib.sha256(expected.encode()).hexdigest()
            return finish('presentation_notice','Throne room notice',[button],[button],
                          mechanical='acknowledge_presentation')
    production_change=classify_production_change(observation,rows,dialog_resources(game_text or ''),rules)
    if production_change:
        result['resource_tag']='PRODCHANGE'
        result['production_change']=production_change['production_change']
        result['evidence'].update(production_change['evidence'])
        return finish('production_change_choice',production_change['title'],production_change['options'],
                      production_change['buttons'],model=True)
    production_upgrade=classify_production_upgrade(observation,rows,dialog_resources(game_text or ''),rules,state,labels_text)
    if production_upgrade:
        result['resource_tag']=production_upgrade['resource_tag']
        result['evidence'].update(production_upgrade['evidence'])
        return finish(production_upgrade['kind'],production_upgrade['title'],production_upgrade['options'],
                      production_upgrade['buttons'],model=True)
    foreign_report=classify_foreign_report(observation,rows,dialog_resources(game_text or ''),rules,labels_text)
    if foreign_report:
        result['resource_tag']=foreign_report['resource_tag']
        result['evidence'].update(foreign_report['evidence'])
        return finish(foreign_report['kind'],foreign_report['title'],foreign_report['options'],
                      foreign_report['buttons'],model=True)
    caravan=classify_caravan(observation,rows,dialog_resources(game_text or ''),rules,labels_text)
    if caravan:
        result['resource_tag']=caravan['resource_tag']
        result['evidence'].update(caravan['evidence'])
        return finish(caravan['kind'],caravan['title'],caravan['options'],caravan['buttons'],model=True)
    native_choice=classify_native_choice(observation,rows,dialog_resources(game_text or ''),rules)
    if native_choice:
        result['resource_tag']=native_choice['resource_tag']
        result['evidence'].update(native_choice['evidence'])
        return finish(native_choice['kind'],native_choice['title'],native_choice['options'],native_choice['buttons'],
                      model=native_choice['requires_model'],mechanical=native_choice['mechanical_action'])
    history=classify_history_notice(observation,rows,game_text,dialog_resources(game_text or ''))
    if history:
        result['resource_tag']='HISTORY'
        result['evidence']['history_report']=history['evidence']
        return finish('information',history['title'],[history['button']],[history['button']],
                      mechanical='acknowledge_information')
    acquisition=classify_acquisition_notice(observation,rows,labels_text,rules,state)
    if acquisition:
        result['resource_tag']=acquisition['resource_tag']
        result['evidence']['acquisition_notice']=acquisition['evidence']
        return finish('information',acquisition['title'],[acquisition['button']],[acquisition['button']],
                      mechanical='acknowledge_information')
    exchange=classify_exchange_picker(observation,rows,dialog_resources(game_text or ''),rules,state)
    if exchange:
        result.update(resource_tag=exchange['resource_tag'],advance=exchange['advance'],prior_trade=exchange['prior_trade'])
        result['evidence']['exchange_picker']=exchange['evidence']
        return finish('exchange_picker',exchange['title'],exchange['options'],exchange['buttons'],
                      model=exchange['requires_model'],mechanical=exchange['mechanical_action'])
    reference=_civilopedia_reference(rows,observation,rules)
    if reference is not None:
        if 'reason' in reference:
            return unknown(reference['reason'],'civilopedia_reference')
        buttons=[_option(row,'button') for row in reference['controls']]
        exit_button=_option(reference['exit'],'button')
        result['reference']={'advance_id':reference['advance']['id'],
            'advance_name':reference['advance']['name'],'observed_body':reference['body'],
            'knowledge':'Reference-page text only; does not establish acquired knowledge or authorize research.'}
        result['evidence']['reference_layout']={'source':'Original 640x480 Civilopedia advance page and RULES advance title',
                                                'source_lines':reference['anchor_lines']}
        return finish('civilopedia_reference',reference['title']['text'],[exit_button],buttons,
                      mechanical='close_reference',reason='Close only the observed EXIT on the complete original advance-reference layout')
    # Do not confuse a generic final score, a rival arrival or the lost-space-race
    # narrative with the player's victory.
    conquest=single_title(r'your civilization has conquered the entire planet')
    space_success='your people have fulfilled the dream of countless generations' in full
    over=single_title(r'game over')
    if conquest or space_success or over:
        if len(conquest)>1 or len(over)>1:return unknown('Ambiguous repeated terminal headings')
        title=(conquest or over or [dict(text=' '.join(r['text'] for r in rows))])[0]['text']
        outcome='victory_candidate_conquest' if conquest else 'victory_candidate_space' if space_success else 'terminal_unspecified'
        choices=[_option(r,'option') for r in rows if r['normal'] in ("no, i'm done",'yes, keep playing')]
        if choices and len(choices)!=2:return unknown('Incomplete keep-playing choices','game_over',title)
        return finish('victory' if conquest or space_success else 'game_over',title,choices,
                      model=bool(choices),outcome=outcome,reason='Original terminal text needs screenshot review; not automated outcome proof')
    if re.search(r'\bspaceship arrives on alpha centauri\b',full):
        return unknown('Arrival does not establish that the human player won','space_arrival')
    buy_titles=single_title(r'buy .+')
    if buy_titles:
        if len(buy_titles)!=1 or buy_titles[0]['confidence']<.8 or not isinstance(rules,dict) or not game_text:
            return unknown('Buy quote requires one original title, original rules and GAME.TXT','buy_quote')
        title=buy_titles[0]
        items=[item for table in ('units','improvements') for item in rules.get(table,[])
               if isinstance(item,dict) and isinstance(item.get('name'),str)
               and 'buy '+_normal(item['name'])==title['normal']]
        if len(items)!=1:
            return unknown('Buy title is not one unambiguous original production item','buy_quote',title['text'])
        body,controls,_=body_rows(title,{'ok','cancel','yes','no','help'},320)
        global_controls=[r for r in rows if r['normal'] in ('ok','cancel','yes','no','help')]
        if (len(controls)!=1 or controls[0]['normal']!='ok' or controls!=global_controls
                or abs(title['center'][0]-controls[0]['center'][0])>8
                or any(r['confidence']<.8 for r in body+controls)):
            return unknown('Buy quote requires one aligned OK and no competing dialog controls','buy_quote',title['text'])
        choices=[r for r in body if r['normal'] in ('complete it','never mind')]
        if choices and ([r['normal'] for r in choices]!=['complete it','never mind'] or len(choices)!=2):
            return unknown('Buy quote does not show both original purchase alternatives','buy_quote',title['text'])
        if [r for r in rows if r['normal'] in ('complete it','never mind')]!=choices:
            return unknown('Buy alternatives occur outside the recognized quote','buy_quote',title['text'])
        content=[r for r in body if r not in choices]
        if (not content or (choices and max(r['bounds'][1]+r['bounds'][3] for r in content)>choices[0]['bounds'][1]+2)
                or any(r['bounds'][1]<title['bounds'][1]+title['bounds'][3]-2 for r in body)):
            return unknown('Buy quote body and choice geometry are ambiguous','buy_quote',title['text'])
        text=_normal(' '.join(r['text'] for r in content))
        amount=r'(?:[0-9]{1,9}|[0-9]{1,3}(?:,[0-9]{3}){1,2})'
        match=re.fullmatch(r'cost to complete '+re.escape(_normal(items[0]['name']))+r': ('+amount+r') gold\. treasury: ('+amount+r') gold',text)
        if not match:
            return unknown('Buy quote lacks the complete exact item, cost and treasury body','buy_quote',title['text'])
        cost,treasury=(int(value.replace(',','')) for value in match.groups())
        tag='COMPLETE1' if choices else 'COMPLETE0'
        if (choices and cost>treasury) or (not choices and cost<=treasury):
            return unknown('Buy controls conflict with the observed affordability','buy_quote',title['text'])
        templates=[t for t in dialog_resources(game_text) if t['tag']==tag]
        expected_body='Cost to complete %STRING0: %NUMBER0 gold. Treasury: %NUMBER1 gold.'
        if (len(templates)!=1 or _normal(templates[0]['title'])!='buy %string0'
                or _normal(templates[0]['body'].replace('^',' '))!=_normal(expected_body)
                or templates[0]['options']!=(['Complete it.','Never mind.'] if choices else [])
                or templates[0]['buttons'] or templates[0]['listbox']):
            return unknown('Buy resource does not match the calibrated original quote','buy_quote',title['text'])
        # An OCR conflict inside this modal makes even a matching text unsafe.
        conflicts=observation.get('ocr',{}).get('conflicts',[])
        if any(isinstance(c,dict) and isinstance(c.get('bounds'),list) and len(c['bounds'])==4
               and all(type(v) is int for v in c['bounds'])
               and c['bounds'][0]<title['center'][0]+160 and c['bounds'][0]+c['bounds'][2]>title['center'][0]-160
               and c['bounds'][1]<controls[0]['bounds'][1]+controls[0]['bounds'][3]
               and c['bounds'][1]+c['bounds'][3]>title['bounds'][1] for c in conflicts):
            return unknown('Conflicting OCR overlaps the native Buy quote','buy_quote',title['text'])
        result['resource_tag']=tag
        result['quote']={'item':items[0]['name'],'cost':cost,'treasury':treasury,
            'source':'Original GAME.TXT '+tag+' and complete visible quote','purchase_executed':False,
            'knowledge':'Quote only. Opening Buy has not purchased anything; any completion requires its own observed choice.'}
        result['evidence']['quote']={'source_tag':tag,'title_source_line':title['source_line'],
            'body_source_lines':[r['source_line'] for r in content],
            'choice_source_lines':[r['source_line'] for r in choices],
            'button_source_line':controls[0]['source_line'],
            'observed_body':'\n'.join(r['text'] for r in content),
            'template_sha256':hashlib.sha256(json.dumps(templates[0],sort_keys=True).encode()).hexdigest()}
        ok=_option(controls[0],'button')
        return finish('buy_quote',title['text'],[_option(r,'option') for r in choices] if choices else [ok],
                      [ok],model=bool(choices),mechanical=None if choices else 'acknowledge_information',
                      reason='Original purchase quote; only its observed alternatives authorize a separate choice' if choices
                      else 'Original unaffordable quote has only an observed OK acknowledgement')
    science_report=single_title(r'science advisor report')
    if science_report:
        if len(science_report)!=1 or science_report[0]['confidence']<.8:
            return unknown('Science report title is ambiguous','science_advisor')
        title=science_report[0]
        templates=[t for t in dialog_resources(game_text) if t['tag']=='REPORTSCIENCE'] if game_text else []
        if len(templates)!=1 or _normal(templates[0]['title'])!='science advisor report' or not isinstance(rules,dict):
            return unknown('Original REPORTSCIENCE resource and advance names are required','science_advisor',title['text'])
        template=templates[0]
        if set(template['buttons'])!={'Info','Goal'} or not template['listbox']:
            return unknown('Science report resource does not match its original controls','science_advisor',title['text'])
        body,button_rows,_=body_rows(title,{'ok','info','goal','cancel'},template['width'] or 540)
        if len(button_rows)!=3 or {r['normal'] for r in button_rows}!={'ok','info','goal'} or any(r['confidence']<.8 for r in button_rows):
            return unknown('Science report requires unambiguous observed OK, Info and Goal controls','science_advisor',title['text'])
        advances={_normal(r['name']):r for r in rules.get('advances',[]) if isinstance(r.get('name'),str)}
        researching=[];discoveries=[];headings=[];achieved=[];unexpected=[]
        for r in body:
            research=re.fullmatch(r'researching:\s*(.+?)\s*\((\d+)\s+of\s+(\d+)\)',r['normal'])
            interval=re.fullmatch(r'discoveries every\s+(\d+)\s+turns?',r['normal'])
            if research and research[1] in advances:
                researching.append((r,research))
            elif interval:
                discoveries.append((r,interval))
            elif r['normal']=='civilization advances achieved':
                headings.append(r)
            elif r['normal'] in advances:
                achieved.append(r)
            else:
                unexpected.append(r)
        if unexpected or len(researching)!=1 or len(discoveries)!=1 or len(headings)!=1 or any(r['confidence']<.8 for r in body):
            return unknown('Science report body is incomplete or contains unrecognized text','science_advisor',title['text'])
        heading=headings[0]
        if (not researching[0][0]['center'][1]<discoveries[0][0]['center'][1]<heading['center'][1]
            or any(r['bounds'][1]<heading['bounds'][1]+heading['bounds'][3]-2 for r in achieved)
            or not _unique(achieved)):
            return unknown('Science report header and achieved-advance list geometry are ambiguous','science_advisor',title['text'])
        buttons=[_option(r,'button') for r in button_rows];ok=next(r for r in buttons if _normal(r['text'])=='ok')
        research=researching[0][1];interval=discoveries[0][1]
        result['resource_tag']='REPORTSCIENCE'
        result['report']={'observed_body':[r['text'] for r in body],
            'researching':advances[research[1]]['name'],'research_progress':int(research[2]),
            'research_required':int(research[3]),'discoveries_every_turns':int(interval[1]),
            'visible_achieved_advances':[advances[r['normal']]['name'] for r in achieved],
            'knowledge':'Actual visible report labels only; the scrollable advance list may be incomplete. This report does not change research.'}
        return finish('science_advisor',title['text'],[ok],buttons,mechanical='acknowledge_information',
                      reason='Acknowledge only observed OK on the complete original Science Advisor Report; Info and Goal are not dispatched')
    # GAME.TXT @CITYMODAL1 is a navigation warning, not a strategic choice.
    # Acknowledge only its observed OK, preserving the city window for the next
    # classification. The alternative "Close City Window" is not dispatched.
    city_warning=single_title(r'city window')
    if city_warning:
        if len(city_warning)!=1 or city_warning[0]['confidence']<.8:
            return unknown('City-window warning title is ambiguous','city_window_warning')
        title=city_warning[0]
        body,button_rows,_=body_rows(title,{'ok','close city window'},400)
        body_text=' '.join(r['normal'] for r in body)
        if body_text!='you must close the city window before the game can proceed':
            return unknown('City-window warning body does not match the original notice','city_window_warning',title['text'])
        if {_normal(r['text']) for r in button_rows}!={'ok','close city window'} or any(r['confidence']<.8 for r in body+button_rows):
            return unknown('City-window warning controls are incomplete','city_window_warning',title['text'])
        buttons=[_option(r,'button') for r in button_rows]
        ok=[r for r in buttons if _normal(r['text'])=='ok']
        if len(ok)!=1:return unknown('City-window OK is ambiguous','city_window_warning',title['text'])
        result['resource_tag']='CITYMODAL1'
        return finish('information',title['text'],ok,buttons,mechanical='acknowledge_information',
                      reason='Dismiss only the exact original City Window warning with its observed default OK')
    # Measured original OCR reads Found as Foond in the illustrated notice.
    # Do not accept that variant without its native founded-city body and OK.
    founded=single_title(r'f(?:ou|oo)nd new ci(?:t|c)y')
    if founded:
        if len(founded)!=1 or founded[0]['confidence']<.8:
            return unknown('Founding notice title is ambiguous','founding_notice')
        title=founded[0]
        body,button_rows,_=body_rows(title,{'ok','cancel','yes','no'},600)
        # The illustrated notice can expose unrelated map labels outside its
        # horizontal body band. Only the single actual founding line establishes
        # the notice; other text inside that band would be an unknown modal.
        matching=[(r,re.fullmatch(rf'(.+?)\s+founded\s*:\s*({DATE_PATTERN})',r['normal'],re.I)) for r in body]
        matching=[(r,m) for r,m in matching if m and date_parts(m[2]) is not None]
        if len(matching)!=1 or len(body)!=1 or matching[0][0]['confidence']<.8:
            return unknown('Founding notice lacks one complete original founded-city line','founding_notice',title['text'])
        if len(button_rows)!=1 or button_rows[0]['normal']!='ok' or button_rows[0]['confidence']<.8:
            return unknown('Founding notice requires one observed OK button','founding_notice',title['text'])
        result['resource_tag']='FOUNDED'
        result['founded_city']={'name':re.split(r'\s+founded\s*:',matching[0][0]['text'],maxsplit=1,flags=re.I)[0].strip(),
                                'year_text':re.split(r'\s+founded\s*:',matching[0][0]['text'],maxsplit=1,flags=re.I)[1].strip(),'source':'Original founding notice text'}
        result['observed_city_name']=result['founded_city']['name']
        ok=_option(button_rows[0],'button')
        return finish('information',title['text'],[ok],[ok],mechanical='acknowledge_information',
                      reason='Original founding notice acknowledged after observed title, body and OK')
    # Optional council consultation is a real two-option native choice. A
    # damaged heading needs the complete original body and both alternatives;
    # its displayed date remains observed text, independent of the save year.
    if game_text:
        council=[t for t in dialog_resources(game_text) if t['tag']=='COUNCILTIME'
                 and t['title']=='The High Council: %STRING2' and t['width']==320
                 and t['options']==['Consult High Council.','No thanks, too busy.']
                 and not t['buttons'] and not t['listbox']]
        titles=[r for r in rows if (m:=re.fullmatch(rf'(.+?):\s*({DATE_PATTERN})',r['normal'],re.I))
                and date_parts(m[2]) is not None and _edit_distance(m[1],'the high council')<=4 and r['confidence']>=.8]
        if len(council)==len(titles)==1:
            title=titles[0];body,controls,_=body_rows(title,{'ok','cancel','yes','no','help'},320)
            expected={_normal(t) for t in council[0]['options']}
            options=[r for r in body if re.sub(r'^(?:o|[○●•])\s+','',r['normal']) in expected]
            prose=[r for r in body if r not in options]
            if (len(options)==2 and {re.sub(r'^(?:o|[○●•])\s+','',r['normal']) for r in options}==expected
                    and len(controls)==1 and controls[0]['normal']=='ok' and prose
                    and all(r['confidence']>=.8 for r in [*body,*controls])
                    and max(r['center'][1] for r in prose)<min(r['center'][1] for r in options)
                    and re.fullmatch(_pattern(council[0]['body']),
                        re.sub(r'\s*,\s*', ', ', _normal(' '.join(r['text'] for r in prose))))):
                result['resource_tag']='COUNCILTIME'
                return finish('high_council',title['text'],[_option(r,'option') for r in options],
                              [_option(r,'button') for r in controls],model=True)
    # Recover only this local prepared caption from source-bound exact pixels.
    # The observation's raw OCR stays intact; the regular production branch
    # below must still prove every offered item, statistic and native control.
    if isinstance(state,dict) and isinstance(rules,dict) and game_text:
        caption=exact_production_title(observation,rows,state,dialog_resources(game_text))
        if caption:
            previous,recovered,name,proof=caption
            rows[rows.index(previous)]=recovered
            result['observed_city_name']=name
            result['evidence']['exact_production_title']=proof
    patterns={
        'new_city_name':r'what shall we name "?this city',
        'research_choice':r'what discovery shall our .+ pursue',
        'production_choice':r'what shall we build in .+',
        'government_choice':r'select type of government',
        'diplomacy':r'.+ emissary',
        'tax_rate':r'select new tax rate',
        'luxury_rate':r'select new luxury rate',
        'revolution_choice':r'revolution',
        'revolution_offer':r'(?:civ rules: governments|cir roles: gopernments)',
        'city_locator':r'where in the (?:heck is|beck is|heckis)',
    }
    matches=[(kind,r) for kind,p in patterns.items() for r in single_title(p)]
    if not matches and game_text:
        offers=[t for t in dialog_resources(game_text) if t['tag']=='AUTOREV'
                and _normal(t['title'])=='civ rules: governments' and len(t['options'])==2]
        recovered=[]
        for heading in rows:
            if heading['confidence']<.8 or _edit_distance(heading['normal'],'civ rules: governments')>4:continue
            for template in offers:
                body,controls,_=body_rows(heading,{'ok','cancel','help'},template['width'] or 440)
                radio=lambda r:re.sub(r'^[•○●o)]*\s*','',r['normal'])
                choices=[r for r in body if any(re.fullmatch(_pattern(t),radio(r)) for t in template['options'])]
                prose=[r for r in body if r not in choices]
                if (len(choices)==2 and len(controls)==1 and controls[0]['normal']=='ok'
                        and all(r['confidence']>=.8 for r in body+controls)
                        and re.fullmatch(_pattern(template['body']),_normal(' '.join(r['text'] for r in prose)))):
                    recovered.append(heading)
        if len(recovered)==1:
            matches=[('revolution_offer',recovered[0])]
            result['title_recovery']={'source':'Complete original AUTOREV body and both actual choices; bounded title glyph difference',
                                      'ocr_text':recovered[0]['text']}
    if not matches and game_text:
        templates=[t for t in dialog_resources(game_text) if t['tag']=='REVOLUTION'
                   and _normal(t['title'])=='revolution' and t['options']==['Yes','No']]
        recovered=[]
        if len(templates)==1:
            for heading in rows:
                if heading['confidence']<.8 or _edit_distance(heading['normal'],'revolution')>2:continue
                body,controls,_=body_rows(heading,{'ok','cancel','help'},240)
                radio=lambda r:re.sub(r'^[o0•○●]\s+','',r['normal'])
                choices=[r for r in body if radio(r) in ('yes','no')]
                prose=' '.join(r['normal'] for r in body if r not in choices)
                if (len(choices)==2 and {radio(r) for r in choices}=={'yes','no'}
                        and len(controls)==1 and controls[0]['normal']=='ok'
                        and all(r['confidence']>=.8 for r in body+controls)
                        and re.fullmatch(_pattern(templates[0]['body']),prose)):
                    recovered.append(heading)
        if len(recovered)==1:
            matches=[('revolution_choice',recovered[0])]
            result['resource_tag']='REVOLUTION'
            result['title_recovery']={'source':'Original REVOLUTION body, both observed alternatives and sole OK; bounded title glyph difference',
                                      'ocr_text':recovered[0]['text'],'source_line':recovered[0]['source_line']}
        elif len(recovered)>1:return unknown('Ambiguous original revolution headings')
    # The original selected-font research screenshot reads the @RESEARCH
    # heading as "Whait ... porsue?". These two measured glyph variants do not
    # authorize a list by themselves: exact advance peers and all three native
    # controls must independently corroborate the research dialog. Keep the raw
    # observed heading and let the ordinary option validation run below.
    if not matches and isinstance(rules,dict):
        advance_names={_normal(r['name']) for r in rules.get('advances',[])
                       if isinstance(r,dict) and isinstance(r.get('name'),str)}
        approximate=[]
        for title in rows:
            if title['confidence']<.8 or not re.fullmatch(r'wha(?:t|it) discovery shall our [a-z ]{2,40} p[uo]rsue',title['normal']):
                continue
            body,controls,_=body_rows(title,{'ok','help','goal','cancel'},300)
            corroborated=(len(controls)==3 and {r['normal'] for r in controls}=={'help','goal','ok'}
                          and all(r['confidence']>=.8 for r in controls)
                          and sum(r['normal'] in advance_names and r['confidence']>=.8 for r in body)>=2)
            if corroborated:approximate.append(title)
        if len(approximate)==1:
            title=approximate[0]
            matches=[('research_choice',title)]
            result['title_recovery']={'source':'Original RESEARCH title with measured Whait/porsue glyph variants, native controls and exact peer advances',
                                      'ocr_text':title['text'],'source_line':title['source_line']}
        elif len(approximate)>1:
            return unknown('Multiple corroborated research headings are ambiguous','research_choice')
    # Match only the original production-title template, and only against city
    # names already observed by the caller. Corrupted title spelling alone is
    # insufficient: exact rule names, paired stat rows and native Auto/Help/OK
    # controls must independently establish this specific original dialog.
    if not matches and isinstance(state,dict) and isinstance(rules,dict):
        city_names={c['name'] for c in state.get('cities',[]) if isinstance(c,dict) and isinstance(c.get('name'),str)}
        city_names.update(n for n in state.get('observed_city_names',[]) if isinstance(n,str))
        # A provisional OCR name can coexist with its later native-save name.
        # Fold only uniquely corroborated aliases instead of making that single
        # city appear to be two competing identities.
        headers=[city_date_match(r['text'])
                 for r in rows if r['confidence']>=.8 and 32<=r['bounds'][1]<=56]
        header_years={m[2] for m in headers if m};header_year=next(iter(header_years)) if len(header_years)==1 else None
        city_names={(_saved_city_name(name,state) or _recent_founded_name(name,header_year,state) or {}).get('name',name) for name in city_names}
        rule_names={_normal(r['name']) for table in ('units','improvements') for r in rules.get(table,[]) if r.get('name') and r['name']!='Nothing'}
        approximate=[]
        for title in rows:
            m=re.fullmatch(r'what shall (?:we|me) ([a-z]{3,7}) in (.{1,60})',title['normal'])
            if not m or title['confidence']<.8 or (_edit_distance(m[1],'build')>2 and m[1]!='bodd'):
                continue
            names=[name for name in city_names if _edit_distance(m[2],_normal(name))<=1]
            if len(names)!=1:
                continue
            if 'production_founding_year' in title:
                founded=_recent_founded_name(m[2],title['production_founding_year'],state)
                if founded is None or _normal(founded['name'])!=_normal(names[0]):continue
            body,buttons,_=body_rows(title,{'ok','auto','help'},440)
            icons=_production_icon_rows(body,rule_names)
            body=[r for r in body if r not in icons]
            options=[r for r in body if r['normal'] in rule_names and r['confidence']>=.8]
            stats=[r for r in body if _production_stat(r['normal'])]
            corroborated=({r['normal'] for r in buttons}=={'auto','help','ok'} and len(buttons)==3
                and all(r['confidence']>=.8 for r in buttons)
                and len(options)>=2 and len(options)==len(stats) and len(body)==len(options)+len(stats)
                and all(any(abs(r['center'][1]-s['center'][1])<=8 and s['bounds'][0]>r['center'][0] for s in stats) for r in options))
            if corroborated:
                approximate.append((title,names[0]))
        if len(approximate)==1:
            title,city_name=approximate[0]
            matches=[('production_choice',title)]
            result['observed_city_name']=city_name
            result['title_match']={'source':'Original production template plus known city, exact options, paired stats and Auto/Help/OK',
                                   'observed_text':title['text'],'template':'What shall we build in '+city_name+'?'}
        elif len(approximate)>1:
            return unknown('Multiple corroborated production headings are ambiguous','production_choice')
    if len(matches)>1:return unknown('Multiple recognized native dialog titles')
    if matches:
        kind,title=matches[0]
        if title['confidence']<.8:return unknown('Low-confidence title',kind,title['text'])
        if kind=='production_choice' and 'production_founding_year' in title:
            suffix=re.fullmatch(r'what shall (?:we|me) [a-z]{3,7} in (.{1,60})',title['normal'])
            founded=_recent_founded_name(suffix[1],title['production_founding_year'],state) if suffix else None
            if founded is None:return unknown('Production title needs one same-year original founding notice',kind,title['text'])
        source_width={'research_choice':300,'production_choice':440,'government_choice':240,
                      'new_city_name':460,'diplomacy':440,'tax_rate':260,'luxury_rate':260,
                      'revolution_choice':240,'revolution_offer':440,'city_locator':360}[kind]
        body,button_rows,_=body_rows(title,{'ok','cancel','help','goal','auto','zoom to city'},source_width)
        if kind=='production_choice' and isinstance(rules,dict):
            names={_normal(r['name']) for table in ('units','improvements') for r in rules.get(table,[])
                   if r.get('name') and r['name']!='Nothing'}
            icons=_production_icon_rows(body,names)
            if icons:
                result['evidence']['production_artwork']=[dict(text=r['text'],bounds=r['bounds'],source_line=r['source_line']) for r in icons]
                body=[r for r in body if r not in icons]
        buttons=[_option(r,'button') for r in button_rows]
        if not _unique(buttons):return unknown('Ambiguous duplicate dialog buttons',kind,title['text'])
        if kind in ('tax_rate','luxury_rate'):
            government=[r for r in body if re.fullmatch(r'government type\s*:\s*(anarchy|despotism|monarchy|communism|fundamentalism|republic|democracy)',r['normal'])]
            maximum=[r for r in body if re.fullmatch(r'maximum rate\s*:\s*\d+\s*%',r['normal'])]
            if len(government)!=1 or len(maximum)!=1 or not any(r['normal']=='ok' for r in button_rows):
                return unknown('Rate dialog context or confirmation is incomplete',kind,title['text'])
            limit=int(re.search(r'\d+',maximum[0]['normal']).group())
            choices=[]
            for r in body:
                if r in government or r in maximum:continue
                if not re.fullmatch(r'\d+\s*%',r['normal']):
                    return unknown('Only complete observed percentage options are supported',kind,title['text'])
                value=int(re.search(r'\d+',r['normal']).group())
                if value%10 or not 0<=value<=min(100,limit) or r['confidence']<.8:
                    return unknown('Unverified or inconsistent rate option',kind,title['text'])
                choices.append(_option(r,'option'))
            if len(choices)<2:return unknown('No unambiguous observed rate-choice list',kind,title['text'])
            result['maximum_rate']=limit
            return finish(kind,title['text'],choices,buttons,model=True)
        if kind=='revolution_choice':
            body_text=' '.join(r['normal'] for r in body)
            if 'citizens demand new government' in body_text:
                ok=[_option(r,'button') for r in button_rows if r['normal']=='ok']
                if len(ok)==1 and len(button_rows)==1:
                    return finish('information',title['text'],ok,buttons,mechanical='acknowledge_information')
                return unknown('Post-revolution acknowledgement is ambiguous',kind,title['text'])
            radio=lambda r:re.sub(r'^[o0•○●]\s+','',r['normal'])
            choice_rows=[r for r in body if radio(r) in ('yes','no')]
            prose=' '.join(r['normal'] for r in body if r not in choice_rows)
            if (len(choice_rows)!=2 or {radio(r) for r in choice_rows}!={'yes','no'}
                    or not re.fullmatch(r'do we want a revolution to overthrow the [a-z ]+',prose)
                    or any(r['confidence']<.8 for r in body+button_rows)
                    or len(button_rows)!=1 or button_rows[0]['normal']!='ok'):
                return unknown('Revolution question or both actual alternatives missing',kind,title['text'])
            choices=[_option(r,'option') for r in choice_rows]
            return finish(kind,title['text'],choices,buttons,model=True)
        if kind=='revolution_offer':
            templates=[t for t in dialog_resources(game_text or '') if t['tag'] in ('AUTOMONARCHY','AUTOREV')
                       and _normal(t['title'])=='civ rules: governments' and len(t['options'])==2]
            matches=[]
            radio=lambda text:re.sub(r'^(?:[o0]\s+|[•○●]\s*)','',text)
            for template in templates:
                body,button_rows,_=body_rows(title,{'ok','cancel','help'},template['width'] or 440)
                choices=[];prose=[]
                for line in body:
                    text=radio(line['normal'])
                    if any(re.fullmatch(_pattern(option),text) for option in template['options']):choices.append(line)
                    else:prose.append(line)
                actual=_normal(' '.join(r['text'] for r in prose))
                # Measured ui328 glyph readings only, within the complete
                # original government explanation. No strategic text omitted.
                actual=re.sub(r'\blo switch governments\b','to switch governments',actual)
                actual=re.sub(r'\bbriel period\b','brief period',actual)
                if (len(choices)==2 and all(r['confidence']>=.8 for r in [*body,*button_rows])
                        and len(button_rows)==1 and button_rows[0]['normal']=='ok'
                        and re.fullmatch(_pattern(template['body']),actual)
                        and all(sum(bool(re.fullmatch(_pattern(option),radio(r['normal'])))
                                    for r in choices)==1 for option in template['options'])
                        and prose and min(r['center'][1] for r in choices)>max(r['center'][1] for r in prose)):
                    matches.append((template,choices))
            if len(matches)!=1:return unknown('Government offer requires its complete original body and both observed choices',kind,title['text'])
            template,choices=matches[0];result['resource_tag']=template['tag']
            return finish(kind,title['text'],[_option(r,'option') for r in choices],buttons,model=True)
        if kind=='city_locator':
            if not isinstance(state,dict):return unknown('Owned city observation required for navigation',kind,title['text'])
            names={_normal(c['name']) for c in state.get('cities',[]) if isinstance(c.get('name'),str)}
            if not names or not button_rows:return unknown('City navigation context incomplete',kind,title['text'])
            if not body or any(r['normal'] not in names for r in body):
                return unknown('City locator labels are not unambiguous owned-city names',kind,title['text'])
            choices=[_option(r,'list_item') for r in body]
            return finish(kind,title['text'],choices,buttons,reason='Navigation only; caller must bind its requested owned city, never accept a guessed default')
        if kind=='new_city_name':
            labels=[r for r in body if re.match(r'city name\s*:',r['text'],re.I)]
            if (len(labels)!=1 or {r['normal'] for r in button_rows}!={'ok','cancel'}
                    or len(button_rows)!=2 or any(r['confidence']<.8 for r in body+button_rows)):
                return unknown('Name prompt or complete OK/Cancel controls are missing',kind,title['text'])
            label=labels[0];suffix=label['text'].partition(':')[2].strip()
            values=[r for r in body if r is not label
                    and abs(r['center'][1]-label['center'][1])<=12
                    and r['bounds'][0]>=label['bounds'][0]+label['bounds'][2]]
            if len(body)!=1+len(values) or (suffix and values):
                return unknown('Name-entry body contains ambiguous or extra text',kind,title['text'])
            if suffix:
                result['default_name']=suffix
            elif len(values)==1:
                result['default_name']=values[0]['text']
            elif not values:
                # A selected native edit value can be absent from OCR. The
                # source-bound NAMECITY form may still accept its untouched
                # default: no name is typed, inferred, or added to known cities.
                templates=[t for t in dialog_resources(game_text) if t['tag']=='NAMECITY'] if game_text else []
                ok_row=next(r for r in button_rows if r['normal']=='ok')
                cancel_row=next(r for r in button_rows if r['normal']=='cancel')
                source_ok=(len(templates)==1 and _normal(templates[0]['title'])=='what shall we name this city'
                    and _normal(templates[0]['body'])=='city name' and not templates[0]['options']
                    and not templates[0]['listbox'] and not templates[0]['buttons'])
                geometry_ok=(label['normal']=='city name'
                    and title['bounds'][1]+title['bounds'][3] < label['bounds'][1]
                    and 16 <= ok_row['center'][1]-label['center'][1] <= 100
                    and abs(ok_row['center'][1]-cancel_row['center'][1])<=12
                    and ok_row['center'][0] < title['center'][0] < cancel_row['center'][0]
                    and abs((ok_row['center'][0]+cancel_row['center'][0])/2-title['center'][0])<=24
                    and title['center'][0]-230 <= label['bounds'][0]
                    and label['bounds'][0]+label['bounds'][2] < title['center'][0])
                extra_controls=[r for r in rows if r['normal'] in {'ok','cancel','yes','no','help','goal','auto'}
                                and r not in button_rows]
                if not source_ok or not geometry_ok or extra_controls:
                    return unknown('Unreadable default lacks the complete original name-entry form',kind,title['text'])
                result['default_name']=None
                result['resource_tag']='NAMECITY'
                result['evidence']['name_entry']={'source_tag':'NAMECITY',
                    'field_label':label['text'],'field_label_source_line':label['source_line'],
                    'field_label_bounds':label['bounds'],'value_observed':False,
                    'operation':'Accept the unchanged native default without typing or inferring its value'}
            else:return unknown('Default city name is ambiguous',kind,title['text'])
            ok=[_option(r,'button') for r in button_rows if r['normal']=='ok']
            return finish(kind,title['text'],ok,buttons,mechanical='accept_observed_default_name')
        if kind in ('research_choice','production_choice','government_choice'):
            if not button_rows or not any(r['normal']=='ok' for r in button_rows):
                return unknown('Observed list confirmation button missing',kind,title['text'])
            if kind=='government_choice':
                names={'despotism','monarchy','communism','fundamentalism','republic','democracy'}
            else:
                if not isinstance(rules,dict):return unknown('Original rules names are required',kind,title['text'])
                tables=['advances'] if kind=='research_choice' else ['units','improvements']
                names={_normal(r['name']) for table in tables for r in rules.get(table,[]) if r.get('name') and r.get('name')!='Nothing'}
            recover_research=(kind=='research_choice'
                and len(button_rows)==3 and {r['normal'] for r in button_rows}=={'help','goal','ok'}
                and all(r['confidence']>=.8 for r in button_rows)
                and sum(r['normal'] in names and r['confidence']>=.8 for r in body)>=2)
            choices=[];unknown_rows=[]
            for row in body:
                # Production suffixes must be native parenthesized stat/turn
                # annotations; no prefix stripping of unknown OCR glyphs.
                base=re.sub(r'\s+\([^()]*\)\s*$','',row['normal'])
                government_label=re.sub(r'^(?:o|[○●•])\s+','',row['normal']) if kind=='government_choice' else None
                if row['normal'] in names or (kind=='production_choice' and base in names) or government_label in names:
                    if row['confidence']<.8:return unknown('Low-confidence option text',kind,title['text'])
                    choices.append(_option(row,'list_item'))
                elif (recover_research and len(row['normal'])>=5 and row['confidence']>=.8
                      and re.fullmatch(r'[a-z ]+',row['normal'])
                      and row['normal'] not in ('civilization advances','city improvements','military units','wonders of the world')):
                    recovered=[r for r in rules.get('advances',[]) if isinstance(r.get('name'),str)
                               and len(_normal(r['name']))>=5 and _edit_distance(row['normal'],_normal(r['name']))==1]
                    if len(recovered)==1:
                        option=_option(row,'list_item');option['ocr_text']=row['text']
                        option['text']=recovered[0]['name']
                        option['name_recovery']={'source':'Unique one-edit match to original advance table, corroborated by research title, controls and exact peer options',
                                                 'original_advance_id':recovered[0].get('id'),'edit_distance':1}
                        choices.append(option)
                    else:unknown_rows.append(row)
                elif re.fullmatch(r'[0-9]+\s+turns?',row['normal']) or _production_stat(row['normal']):
                    # Independently recognized display-only timing column.
                    continue
                elif row['normal'] not in ('civilization advances','city improvements','military units','wonders of the world'):
                    unknown_rows.append(row)
            if unknown_rows:return unknown('Unrecognized text inside native list; options may be incomplete',kind,title['text'])
            if not choices:return unknown('No complete authentic option labels recognized',kind,title['text'])
            return finish(kind,title['text'],choices,buttons,model=True)
        # Diplomacy may have no standard button labels in OCR: option radio rows
        # still need a complete resource-matched body and actual option labels.
        if not game_text:return unknown('Original diplomacy templates required',kind,title['text'])
        templates=[t for t in dialog_resources(game_text) if re.fullmatch(_pattern(t['title']),title['normal'])]
        found=[]
        for template in templates:
            if not template['body']:continue
            # EXCHANGE0 may append one counteroffer from the original LABELS
            # catalog. Its presence and text must be observed, never invented.
            optional=[]
            if template['tag']=='EXCHANGE0' and isinstance(labels_text,str):
                label='"Will you accept %STRING4 instead?"'
                if labels_text.splitlines().count(label)==1:optional=[label]
            # Original emissary notices are narrower than the dialogue menu.
            # Scope every source template to its own observed frame, excluding
            # the game status pane visible beside it and text below its OK.
            below,template_buttons,_=body_rows(title,{'ok','cancel','help','goal','auto'},template['width'] or source_width)
            if template_buttons!=button_rows or not below:continue
            half=max((template['width'] or source_width)/2,title['bounds'][2]/2+12)
            if any(r not in below and r not in template_buttons
                   and r['bounds'][1]>title['bounds'][1]+title['bounds'][3]-2
                   and r['center'][1]<min(b['center'][1] for b in template_buttons)
                   and abs(r['center'][0]-title['center'][0])<=half for r in rows):continue
            # Normalize the complete wrapped text once. Normalizing each row
            # would erase an internal colon/period at a line break.
            actual=_normal(' '.join(r['text'] for r in below))
            # GREETINGS02 renders its _._._. spacing markup as an ellipsis.
            # Source text remains immutable; match its observed rendered form.
            rendered_body=template['body'].replace('_._._.','...')
            match=(re.match if template['options'] else re.fullmatch)(_pattern(rendered_body),actual)
            if not match:continue
            # Match choices after the complete body, not phrases quoted by the
            # emissary within the body. Handle OCR-wrapped options in 1..3 rows.
            after=[]
            for index,row in enumerate(below):
                start=len(_normal(' '.join(r['text'] for r in below[:index])))+1 if index else 0
                if start>=match.end():after.append(row)
            pronoun_recovery=None
            if template['tag']=='EMISSARY':
                # LABELS.TXT supplies the two literal pronouns him/her. The
                # terminal variable must consume the complete visible body,
                # not a prefix that leaves extra text on its last OCR row.
                body_text=_normal(' '.join(r['text'] for r in below[:len(below)-len(after)]))
                exact_body=any(re.fullmatch(_pattern(rendered_body.replace('%STRING4',pronoun)),body_text)
                               for pronoun in ('him','her'))
                if not exact_body:
                    # Retained original006/910 prints "her?", read as hert.
                    # Admit only that complete suffix with an independently
                    # observed source alternative that also says her.
                    peer=any(re.sub(r'^(?:o|[○●•])\s+(?=["\'])','',r['normal'])=='"no. send her away."' for r in after)
                    if not peer or not re.fullmatch(_pattern(rendered_body.replace('%STRING4','hert')),body_text):continue
                    pronoun_recovery={'observed_suffix':'hert','source_pronoun':'her',
                        'source':'Original LABELS.TXT her; measured question-mark glyph and exact matching refusal alternative'}
            detached=[];radio_valid=True
            # Original EMISSARY can OCR a radio circle as its own row, even
            # after the label in vertical sort order. Bind only a small marker
            # immediately left of one complete source alternative, retaining
            # both source rows and the actual label's click point.
            if template['tag']=='EMISSARY':
                markers=[r for r in after if r['normal'] in ('o','○','●','•')]
                for marker in markers:
                    peers=[r for r in after if r not in markers
                           and r['confidence']>=.8
                           and abs(r['center'][1]-marker['center'][1])<=3
                           and 6<=r['bounds'][0]-marker['center'][0]<=28
                           and marker['bounds'][0]+marker['bounds'][2]<=r['bounds'][0]-2
                           and any(re.fullmatch(_choice_pattern(t),r['normal']) for t in template['options'])]
                    if (marker['confidence']<.8 or not all(6<=v<=20 for v in marker['bounds'][2:])
                            or len(peers)!=1 or any(d['label_source_line']==peers[0]['source_line'] for d in detached)):
                        radio_valid=False;break
                    detached.append({'marker_source_line':marker['source_line'],
                        'label_source_line':peers[0]['source_line'],'marker_bounds':marker['bounds'],
                        'label_center':peers[0]['center'],'observed_marker':marker['text']})
                after=[r for r in after if r not in markers]
            if not radio_valid:continue
            options=[];i=0;valid=True
            while i<len(after):
                matches_option=[]
                for count in range(1,min(3,len(after)-i)+1):
                    segment=after[i:i+count]
                    if count>1 and any(segment[j+1]['bounds'][1]-segment[j]['bounds'][1]>28 for j in range(count-1)):continue
                    joined=_normal(' '.join(r['text'] for r in segment))
                    # A visible radio-circle prefix is artwork, not part of the
                    # source alternative. Preserve it in the actual option text.
                    joined=re.sub(r'^(?:o|[○●•])\s+(?=["\'])','',joined)
                    if any(re.fullmatch(_choice_pattern(t),joined) for t in template['options']+optional):
                        matches_option.append((count,segment))
                if len(matches_option)!=1:valid=False;break
                count,segment=matches_option[0]
                option=_option(segment[0],'option')
                option['text']=' '.join(r['text'] for r in segment)
                option['source_lines']=[r['source_line'] for r in segment]
                options.append(option);i+=count
            if not valid:continue
            if template['options'] and not options:continue
            # Non-menu choice dialogs require all source alternatives; menu
            # templates may have a native filtered subset, all still observed.
            if optional:
                if len(options) not in (len(template['options']),len(template['options'])+1):continue
                expected=template['options']+(optional if len(options)>len(template['options']) else [])
                if any(not re.fullmatch(_choice_pattern(source),re.sub(r'^(?:o|[○●•])\s+(?=["\'])','',_normal(option['text'])))
                       for source,option in zip(expected,options)):continue
            elif template['tag'] not in ('DIPLOMACY','TREATYMENU') and len(options)!=len(template['options']):continue
            found.append((template,options,detached,pronoun_recovery))
        if len(found)!=1:return unknown('Diplomatic text/options do not match one complete original template',kind,title['text'])
        template,choices,detached,pronoun_recovery=found[0];result['resource_tag']=template['tag']
        if detached:result['evidence']['detached_radio_markers']=detached
        if pronoun_recovery:result['evidence']['audience_pronoun_reading']=pronoun_recovery
        if template['tag']=='EXCHANGE0' and len(choices)>len(template['options']):
            result['evidence']['optional_label_source']={'resource':'LABELS.TXT',
                'sha256':hashlib.sha256(labels_text.encode('utf-8')).hexdigest(),
                'template':'"Will you accept %STRING4 instead?"'}
        if not choices:
            choices=[_option(r,'button') for r in button_rows if r['normal']=='ok']
            if len(choices)!=1:return unknown('No visible acknowledgement button',kind,title['text'])
            if template['tag']=='INTRUDER':
                # The complete source-matched withdrawal warning is public
                # information. Retain it for later model decisions; this
                # acknowledgement does not choose or execute a unit retreat.
                result['evidence'].update(source='original GAME.TXT event template',
                    source_tag=template['tag'],
                    template_sha256=hashlib.sha256(json.dumps(template,sort_keys=True).encode()).hexdigest())
                return finish('information',title['text'],choices,buttons,mechanical='acknowledge_information')
            return finish(kind,title['text'],choices,buttons,mechanical='acknowledge_information')
        return finish(kind,title['text'],choices,buttons,model=True)
    # @GHOSTTOWN is a strategic choice: completing a worker can remove its
    # size-one city. Never send its OK through the informational path.
    if game_text and isinstance(state,dict) and isinstance(rules,dict):
        ghost=[t for t in dialog_resources(game_text) if t['tag']=='GHOSTTOWN'
               and _normal(t['title'])=='domestic advisor' and t['width']==320
               and _normal(t['body'])=='%string0 is about to build %string1, but it is only a size 1 city. continue anyway'
               and t['options']==['Delay Settler production.','Build Settlers anyway (disbands city).']
               and not t['buttons'] and not t['listbox']]
        headings=single_title(r'(?:domestic advisor|domestic admsor)')
        if len(ghost)==len(headings)==1:
            title=headings[0];body,controls,_=body_rows(title,{'ok','cancel','yes','no','help'},320)
            def ghost_option(row):
                text=re.sub(r'^(?:o|[○●•])\s+','',row['normal'])
                # Original006/768 visibly prints "disbands". Keep the raw
                # reading in the model option; only source comparison tolerates
                # the measured b→h error inside this complete literal choice.
                return text.replace('(dishands city)','(disbands city)')
            expected=[_normal(t) for t in ghost[0]['options']]
            choices=[r for r in body if ghost_option(r) in expected]
            prose=[r for r in body if r not in choices]
            sentence=_normal(' '.join(r['text'] for r in prose))
            match=re.fullmatch(r'(.{3,60}) is about to build (.{3,40}), but it is only a size 1 city\. continue anyway',sentence)
            city=_saved_city_name(match[1],state) if match else None
            workers=[u for u in rules.get('units',[]) if isinstance(u,dict) and u.get('role')==5
                     and isinstance(u.get('name'),str) and match and _normal(u['name'])==match[2]]
            if (city is not None and len(workers)==1 and len(choices)==2
                    and [ghost_option(r) for r in choices]==expected
                    and len(controls)==1 and controls[0]['normal']=='ok'
                    and all(r['confidence']>=.8 for r in [title,*body,*controls])
                    and abs(title['center'][0]-controls[0]['center'][0])<=8
                    and prose and min(r['center'][1] for r in choices)>max(r['center'][1] for r in prose)+8):
                result['resource_tag']='GHOSTTOWN'
                result['evidence']['worker_disband_warning']={
                    'source':'Original GAME.TXT GHOSTTOWN, owned native city and worker-role RULES unit',
                    'city_name':city['name'],'item_name':workers[0]['name'],
                    'observed_body':'\n'.join(r['text'] for r in prose),
                    'observed_options':[r['text'] for r in choices],
                    'body_source_lines':[r['source_line'] for r in prose],
                    'choice_source_lines':[r['source_line'] for r in choices],
                    'template_sha256':hashlib.sha256(json.dumps(ghost[0],sort_keys=True).encode()).hexdigest()}
                return finish('worker_disband_choice',title['text'],[_option(r,'option') for r in choices],
                              [_option(r,'button') for r in controls],model=True,
                              reason='Original size-one worker completion warning; both observed alternatives require a model choice')
    # The original BUILT notice can add the LABELS.TXT radio choices to its
    # template body. Both are real choices, so never acknowledge its OK using
    # the information-only path. Bind names to observed own cities/public rules.
    if game_text and isinstance(state,dict) and isinstance(rules,dict):
        notice_templates={'BUILT':('domestic advisor','%string0 %string3 %string1'),
                          'SUPPORT':('military advisor',"%string0 can't support %string1. unit disbanded")}
        built=[t for t in dialog_resources(game_text) if t['tag'] in notice_templates
               and (_normal(t['title']),_normal(t['body']))==notice_templates[t['tag']]
               and t['options']==[] and not t['listbox']]
        headings=single_title('domestic advisor')+single_title('military advisor')
        if len(headings)==1:
            built=[t for t in built if _normal(t['title'])==headings[0]['normal']]
        if len(built)==1 and len(headings)==1:
            title=headings[0]
            body,button_rows,_=body_rows(title,{'ok','cancel','yes','no','help'},600)
            def radio_label(row):
                # Original unselected circle can be read as O. Preserve raw
                # option text and its observed center; only compare the label.
                return re.sub(r'^(?:o|[○●•])\s+','',row['normal'])
            radios=[r for r in body if radio_label(r) in ('zoom to city','continue')]
            # A native radio circle can be a separate OCR row. Treat it only
            # as artwork beside an already complete observed choice label.
            radio_marks=[];marked_choices=[]
            if len(radios)==2:
                for row in body:
                    if row in radios or row['normal'] not in ('o','○','●','•'):continue
                    x,y,w,h=row['bounds']
                    matched=[r for r in radios if 6<=w<=20 and 6<=h<=20
                             and abs(row['center'][1]-r['center'][1])<=3
                             and 16<=r['bounds'][0]-row['center'][0]<=28
                             and 6<=r['bounds'][0]-(x+w)<=20]
                    if len(matched)==1 and matched[0] not in marked_choices:
                        radio_marks.append(row);marked_choices.append(matched[0])
            text_rows=[r for r in body if r not in radios and r not in radio_marks]
            cities={_normal(c['name']) for c in state.get('cities',[]) if isinstance(c,dict) and isinstance(c.get('name'),str)}
            names={_normal(r['name']) for table in ('units','improvements') for r in rules.get(table,[])
                   if isinstance(r,dict) and isinstance(r.get('name'),str)}
            sentence=text_rows[0]['normal'] if len(text_rows)==1 else None
            combinations=[(city,verb,item) for city in cities for verb in ('builds','completes') for item in names
                          if sentence==city+' '+verb+' '+item]
            if built[0]['tag']=='SUPPORT':
                units={_normal(u['name']) for u in rules.get('units',[]) if isinstance(u,dict) and isinstance(u.get('name'),str)}
                combinations=[(city,'cannot support',item) for city in cities for item in units
                              if sentence==city+" can't support "+item+'. unit disbanded']
            if (len(combinations)==1 and len(radios)==2 and {radio_label(r) for r in radios}=={'zoom to city','continue'}
                    and len(button_rows)==1 and button_rows[0]['normal']=='ok'
                    and all(r['confidence']>=.8 for r in [title,*body,*button_rows])
                    and abs(title['center'][0]-button_rows[0]['center'][0])<=8
                    and all(r['center'][1]>text_rows[0]['center'][1]+8 for r in radios)):
                tag=built[0]['tag']
                result['resource_tag']=tag
                result['evidence']['completion_notice' if tag=='BUILT' else 'support_loss_notice']={'source':f'Original GAME.TXT {tag} and LABELS.TXT Zoom to City/Continue',
                    'observed_body':text_rows[0]['text'],'body_source_line':text_rows[0]['source_line'],
                    'city_name':combinations[0][0],'item_name':combinations[0][2],
                    'separate_radio_artwork':[{'text':r['text'],'bounds':r['bounds'],
                                               'source_line':r['source_line']} for r in radio_marks]}
                return finish('production_notice' if tag=='BUILT' else 'support_loss_notice',title['text'],[_option(r,'option') for r in radios],
                              [_option(r,'button') for r in button_rows],model=True)
    if game_text:
        # Original LABELS.TXT supplies these finite completion verbs. Without
        # them BUILT's all-placeholder body could match arbitrary advisor text.
        event=classify_information(observation,dialog_resources(game_text),
            placeholder_values={tag:{'STRING3':['completes','builds']} for tag in ('BUILT','BUILT3')})
        if event['supported']:
            result['resource_tag']=event['resource_tag']
            result['evidence']={**result['evidence'],**event['evidence']}
            if 'native_rejection' in event:
                result['native_rejection']=event['native_rejection']
            return finish(event['kind'],event['title'],event['options'],event['buttons'],
                          mechanical='acknowledge_information',reason=event['reason'])
        if any(r['normal'] in set(EVENT_TITLES.values()) for r in rows):
            return unknown(event['reason'],'information')
    info_titles=[r for r in rows if (r['normal'] in ('game saved','in the beginning','civilization advance')
                 or r['normal'].startswith('civ tutorial:') or r['normal'].startswith('civ rules:'))]
    if len(info_titles)>1:return unknown('Multiple informational headings')
    if info_titles:
        title=info_titles[0]
        if title['normal'].startswith('civ rules:'):
            sources=[t for t in dialog_resources(game_text) if re.fullmatch(_pattern(t['title']),title['normal'])] if game_text else []
            if len(sources)!=1 or sources[0]['options']:
                return unknown('Rule notice is not a verified information-only resource','information',title['text'])
        _,button_rows,_=body_rows(title,{'ok','cancel','yes','no','help'})
        if len(button_rows)!=1 or button_rows[0]['normal']!='ok':
            return unknown('Information screen is not an unambiguous single-OK acknowledgement','information',title['text'])
        # Fixed informational titles are safe only with no other visible choice
        # or confirmation cues. Civ Rules can include destructive confirmations.
        if re.search(r'\b(really|do you want|are you sure|shall we)\b',full):
            return unknown('Confirmation wording requires explicit choice','information',title['text'])
        choice=_option(button_rows[0],'button')
        return finish('information',title['text'],[choice],[choice],mechanical='acknowledge_information')
    # Unrecognized modal controls must block classification of the background map
    # or city screen. OCR alone cannot prove a foreground box is absent.
    if any(r['normal'] in ('ok','cancel','yes','no','repeat search') and r['center'][1]>40 for r in rows):
        return unknown('Unrecognized foreground dialog controls')
    labels={r['normal'].replace(' ','') for r in rows}
    # Narrow observed OCR alias from the complete original city screen. A
    # truncated label under a foreground popup ("Units Sup") does not qualify.
    if any(r['normal']=='units supporied' and 0<=r['bounds'][0]<200 and 260<=r['center'][1]<=310
           and r['confidence']>=.8 for r in rows):
        labels.add('unitssupported')
    city_markers={'foodstorage','cityresources','unitssupported','unitspresent','resourcemap'}
    city_layout=None
    missing_city_markers=city_markers-labels
    if missing_city_markers and missing_city_markers<={'unitssupported','unitspresent'}:
        city_layout=_city_layout_without_unit_captions(rows,observation,missing_city_markers)
    if city_markers<=labels or city_layout is not None:
        if re.search(r'\b(?:select|choose|emissary|confirmation|warning|please|really|are you sure)\b',full):
            return unknown('Possible unrecognized foreground modal over the city screen','city_screen')
        buttons=[_option(r,'button') for r in rows if r['normal'] in ('buy','change','info','map','happy','view','rename','exit')
                 and r['center'][0]>width*.65 and r['center'][1]>height*.45]
        if not {'buy','change','exit'}<={_normal(b['text']) for b in buttons}:
            return unknown('City controls incomplete','city_screen')
        if city_layout is not None:
            result['evidence']['city_layout']=city_layout
        anchors={key:[r for r in rows if r['normal']==label and r['confidence']>=.8]
                 for key,label in (('resource_map','resource map'),('citizens','citizens'))}
        if all(len(matches)==1 for matches in anchors.values()):
            result['evidence']['city_resource_map']={key:{field:matches[0][field]
                for field in ('center','bounds','source_line')} for key,matches in anchors.items()}
        titles=[r for r in rows if 32<=r['bounds'][1]<=56 and r['confidence']>=.8
                and city_date_match(r['text'])]
        title=titles[0]['text'] if len(titles)==1 else 'Original city screen'
        if len(titles)==1:
            match=city_date_match(titles[0]['text'])
            if match:
                raw_name=match[1].strip()
                result['observed_city_name']=raw_name
                city=_saved_city_name(raw_name,state) if titles[0]['confidence']>=.8 else None
                if city is not None:
                    result['observed_city_name']=city['name']
                    if _normal(city['name'])!=_normal(raw_name):
                        from .revision import prefixed_revision
                        source='live memory observation' if state['evidence'].get('kind')=='live_memory' else 'original save'
                        result['city_name_recovery']={'source':'Unique one-edit match to owned city in '+source,
                            'ocr_text':raw_name,'canonical_name':city['name'],'city_id':city['id'],
                            **prefixed_revision(state),'source_line':titles[0]['source_line']}
                elif titles[0]['confidence']>=.8:
                    notice=_recent_founded_name(raw_name,match[2],state)
                    if notice is not None:
                        result['observed_city_name']=notice['name']
                        result['city_name_recovery']={'source':'Unique same-year original founding notice label; no native actor binding',
                            'ocr_text':raw_name,'canonical_name':notice['name'],'year_text':notice['year_text'],
                            'notice_image_sha256':notice['image_sha256'],'source_line':titles[0]['source_line']}
        return finish('city_screen',title,buttons,buttons,model=True)
    map_kind,map_reason=_native_map_kind(rows,observation,state,native_map_context)
    if map_kind:
        map_proof=native_map_evidence(native_map_context,observation)
        if map_proof:result['evidence']['native_map']=map_proof
        return finish(map_kind,'End of Turn' if map_kind=='end_turn' else 'Original map',reason=map_reason)
    result['reason']=map_reason
    return result


# Short alias for callers that do not need to distinguish OCR and save parsers.
classify = classify_dialog
