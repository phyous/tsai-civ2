"""State-independent caption pixels and pure source-bound title matching.

No image files or guest state are read by the classifier helper. The optional
local atlas is the only file read, hash-pinned exactly like the herald atlas.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import re
from PIL import Image,ImageChops
from .gdi_text import (load_atlas,REGULAR_ATLAS_ID,REGULAR_ATLAS_SHA256,REGULAR_METRICS_SHA256)
from .revision import prefixed_revision

TITLE_TEMPLATE={'tag':'PRODUCTION','title':'What shall we build in %STRING0?',
                'width':440,'body':'','options':[],'buttons':['Auto','Help'],'listbox':True}
TEMPLATE_SHA256='c3680a28f44d263138a6c7bbcd2245796304e2392522fa5bd9714c247af97533'
PALETTE={0,65,134,182,190,199,207,215,223}
PROOF_KIND='original-production-caption-pixels-v1'


def _sha(value):return hashlib.sha256(value).hexdigest()
def _canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def _year(text):return re.sub('[^a-z0-9]','',text.casefold())


def _controls(rows):
    found=[r for r in rows if r['text'] in ('Auto','Help','OK')]
    if len(found)!=3 or {r['text'] for r in found}!={'Auto','Help','OK'}:return None
    if any(r.get('confidence',0)<.8 for r in found) or max(r['center'][1] for r in found)-min(r['center'][1] for r in found)>8:return None
    expected={'Auto':(140,185),'Help':(300,340),'OK':(450,490)}
    if any(not expected[r['text']][0]<=r['center'][0]<=expected[r['text']][1] or not 200<=r['center'][1]<=425 for r in found):return None
    return found


def _caption_row(row,controls):
    x,y,w,h=row['bounds']
    return (row.get('confidence',0)>=.8 and 100<=x and x+w<=540 and 100<=w<=420 and 8<=h<=24
            and 65<=y and y+h<=210 and 308<=row['center'][0]<=332
            and row['center'][1]+30<min(r['center'][1] for r in controls))


def _bitrows(image,value):
    pixels=image.load();width,height=image.size
    return [format(sum(1<<x for x in range(width) if pixels[x,y]==value),'0110x') for y in range(height)]


def annotate_production_titles(image,rows,source_hash):
    """Capture bounded original masks only; no state/name candidates or OCR edits."""
    if image.size!=(640,480) or not re.fullmatch('[0-9a-f]{64}',str(source_hash)):return
    controls=_controls(rows)
    if controls is None:return
    image=image.convert('RGB')
    for row in rows:
        if not _caption_row(row,controls):continue
        _,y,_,h=row['bounds'];crop=[100,y-4,440,h+8];region=image.crop((100,y-4,540,y+h+4))
        colors=region.getcolors(region.width*region.height)
        if not colors or any(not r==g==b or r not in PALETTE for count,(r,g,b) in colors):continue
        gray=region.getchannel('R')
        row['gdi_title_pixels']={'kind':PROOF_KIND,'source_sha256':source_hash,'row_bounds':list(row['bounds']),
            'crop':crop,'palette':sorted(c[0] for _,c in colors),'region_rgb_sha256':_sha(region.tobytes()),
            'black':_bitrows(gray,0),'gray134':_bitrows(gray,134)}


def _proof(raw,row,source_hash):
    p=raw.get('gdi_title_pixels')
    if (not isinstance(p,dict) or set(p)!={'kind','source_sha256','row_bounds','crop','palette','region_rgb_sha256','black','gray134'}
            or p['kind']!=PROOF_KIND or p['source_sha256']!=source_hash or p['row_bounds']!=row['bounds']
            or not re.fullmatch('[0-9a-f]{64}',str(p['region_rgb_sha256']))):return None
    _,y,_,h=row['bounds']
    if p['crop']!=[100,y-4,440,h+8]:return None
    palette=p['palette']
    if (not isinstance(palette,list) or any(type(v) is not int for v in palette) or palette!=sorted(set(palette))
            or not set(palette)<=PALETTE or not {0,134}<=set(palette)):return None
    masks=[]
    for name in ('black','gray134'):
        values=p[name]
        if not isinstance(values,list) or len(values)!=h+8 or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{110}',v) for v in values):return None
        masks.append([int(v,16) for v in values])
    if any(a&b for a,b in zip(*masks)):return None
    return p,*masks


def _names(state,rows):
    if not isinstance(state,dict):return []
    candidates={};ambiguous=set()
    try:source_revision=prefixed_revision(state)
    except (ValueError,TypeError):source_revision=None
    player=state.get('player',{}).get('id');cities=state.get('cities',[])
    if source_revision and type(player) is int and isinstance(cities,list) and len(cities)<=256:
        for city in cities:
            if (not isinstance(city,dict) or city.get('owner')!=player
                    or any(type(city.get(k)) is not int for k in ('id','owner','x','y'))
                    or not isinstance(city.get('name'),str) or not 3<=len(city['name'])<=60):continue
            name=city['name']
            if name in candidates:ambiguous.add(name)
            candidates[name]={'kind':'owned_native_city',**source_revision,
                              'city':{k:city[k] for k in ('id','owner','name','x','y')}}
    headers=[re.match(r'city of .+?,\s*(\d{1,5}\s+(?:b\.?\s*c\.?|a\.?\s*d\.?))',r['text'],re.I)
             for r in rows if r.get('confidence',0)>=.8 and 32<=r['bounds'][1]<=56]
    years={_year(m[1]) for m in headers if m};notices=state.get('recent_founding_notices',[])
    if len(years)==1 and isinstance(notices,list) and len(notices)<=4:
        for notice in notices:
            if (not isinstance(notice,dict) or notice.get('source_tag')!='FOUNDED'
                    or not re.fullmatch('[0-9a-f]{64}',str(notice.get('image_sha256','')))
                    or not isinstance(notice.get('year_text'),str) or _year(notice['year_text']) not in years
                    or not isinstance(notice.get('name'),str) or not 3<=len(notice['name'])<=60):continue
            candidates.setdefault(notice['name'],{'kind':'same_year_founding_notice','name':notice['name'],
                'image_sha256':notice['image_sha256'],'year_text':notice['year_text'],'source_tag':'FOUNDED'})
    return [(name,evidence) for name,evidence in candidates.items() if name not in ambiguous]


def _maskrows(mask):
    pixels=mask.load();return [sum(1<<x for x in range(mask.width) if pixels[x,y]) for y in range(mask.height)]


@lru_cache(maxsize=256)
def _render(text):
    atlas=load_atlas(style='regular')
    # Exceptions are not cached: a missing/half-installed optional atlas must
    # not leave a stale miss after local generation completes.
    if atlas is None:raise ValueError('Optional original regular atlas is unavailable')
    original=atlas.render(text);base=Image.new('L',(original.width+4,44));base.paste(original,(2,2))
    gray=Image.new('L',base.size)
    for dx,dy in ((-1,-1),(-2,-1)):
        layer=Image.new('L',base.size);layer.paste(original,(2+dx,2+dy));gray=ImageChops.lighter(gray,layer)
    black=ImageChops.subtract(base,gray);bounds=ImageChops.lighter(base,gray).getbbox()
    black=black.crop(bounds);gray=gray.crop(bounds)
    return black.width,black.height,_maskrows(black),_maskrows(gray)


def exact_production_title(observation,rows,state,resources):
    """Return one pixel-proven prepared title row and evidence, or None.

    Owned native identities or same-year founded-name observations provide a
    bounded candidate set. Neither edit distance nor OCR suffixes choose a name.
    """
    if ((observation.get('width'),observation.get('height'))!=(640,480)
            or observation.get('ocr',{}).get('conflicts') or not isinstance(resources,list)
            or [r for r in resources if r.get('tag')=='PRODUCTION']!=[TITLE_TEMPLATE]):return None
    controls=_controls(rows)
    if controls is None:return None
    names=_names(state,rows)
    if not names:return None
    if load_atlas(style='regular') is None:return None
    matches=[]
    for row in rows:
        if not _caption_row(row,controls):continue
        index=row.get('source_line')
        if type(index) is not int or not 0<=index<len(observation.get('lines',[])):continue
        proof=_proof(observation['lines'][index],row,observation.get('sha256'))
        if proof is None:continue
        p,actual_black,actual_gray=proof;left,top,width,height=p['crop']
        for name,name_proof in names:
            text=TITLE_TEMPLATE['title'].replace('%STRING0',name)
            try:rendered=_render(text)
            except ValueError:continue
            if rendered is None:continue
            w,h,black,gray=rendered
            if not 1<=w<=420 or h>height:continue
            for x in range(round(320-w/2)-3,round(320-w/2)+4):
                shift=x-left
                if shift<0 or shift+w>width:continue
                shifted_black=[v<<shift for v in black];shifted_gray=[v<<shift for v in gray]
                for y in range(height-h+1):
                    expected=[0]*y+shifted_black+[0]*(height-h-y)
                    if expected!=actual_black:continue
                    if any((v&actual_gray[y+i])!=v for i,v in enumerate(shifted_gray)):continue
                    bounds=[x,top+y,w,h]
                    if abs(x+w/2-row['center'][0])>8 or abs(top+y+h/2-row['center'][1])>5:continue
                    new=deepcopy(row);new.update(text=text,normal=text.casefold().strip(' .:!?'),bounds=bounds,
                                                center=[round(x+w/2),round(top+y+h/2)],confidence=1)
                    evidence={'source':'Original GAME.TXT PRODUCTION title and exact original GDI caption pixels',
                        'source_image_sha256':observation['sha256'],'source_line':index,'raw_ocr_text':row['text'],
                        'text':text,'observed_city_name':name,'name_source':name_proof,'template_sha256':TEMPLATE_SHA256,
                        'atlas_id':REGULAR_ATLAS_ID,'atlas_sha256':REGULAR_ATLAS_SHA256,'metrics_sha256':REGULAR_METRICS_SHA256,
                        'bounds':bounds,'pixel_proof_sha256':_sha(_canonical(p)),
                        'black_extra':0,'black_missing':0,'predicted_gray_missing':0,
                        'gray134_overpaint_offsets':[[-1,-1],[-2,-1]],
                        'scope':'Caption text only; complete original options and city guards remain mandatory'}
                    matches.append((row,new,name,evidence))
    return matches[0] if len(matches)==1 else None
