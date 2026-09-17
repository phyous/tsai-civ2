"""Exact original-GDI option readings; no inputs, guessed words or font assets.

The optional locally generated atlas stays under ignored engine/game/. Missing
or changed bytes disable this fallback. Existing full-dialog checks still apply.
"""
from __future__ import annotations
from copy import deepcopy
import csv
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import re
from zipfile import ZipFile, BadZipFile
from PIL import Image, ImageChops

ROOT=Path(__file__).resolve().parents[1]
ATLAS_ID='original-win31-times-new-roman-bold-16-v1'
ATLAS_SHA256='ae5c588fd813391b31109ab0e0b4e23925df12a0e86243667beac84a54994cad'
METRICS_SHA256='ff4431e8b04cebd3c0de1f5f7f61a655b3dc8d73067221d82fd51739f4db4c84'
SOURCE_PINS={
 'EXCHANGE0':'8fbbf07b8214d9afe08754c3eab0b05744430da1130230e8176b51931c977887',
 'EXCHANGE1':'3662cf980a23d2480897856c6483bdf78525ef439b771dc7cc1fa1abac583dc2',
 'PROPOSEPEACE':'7d6d029be3a15a19a420ac38f8fcaaf561431aeb0ea15f69981821089b7f15cd'}
COUNTEROFFER='"Will you accept %STRING4 instead?"'
# All three calibrated herald option interiors share exactly this grayscale
# palette. This is a foreground-mask match, not equality of texture pixels.
ROW_PALETTE={(v,v,v) for v in (0,97,105,113,121,130,134,142,150,158,166,174,182,190,195,199,207,215,223)}
WHITE_RING=([(x,y) for x in range(-2,3) for y in (-8,8)]
            +[(x,y) for y in range(-2,3) for x in (-8,8)])
BLACK_RING=[(x,-7) for x in range(-2,3)]+[(-7,y) for y in range(-2,3)]


def _sha(data):return hashlib.sha256(data).hexdigest()
def _canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def _words(text):return re.findall(r'[A-Za-z0-9]+',text)


class Atlas:
    """95 original ASCII masks, exact advances; TextOut origin is (4,4)."""
    def __init__(self,bitmap,metrics):
        if _sha(bitmap)!=ATLAS_SHA256 or _sha(metrics)!=METRICS_SHA256:
            raise ValueError('Original GDI atlas bytes differ')
        image=Image.open(io.BytesIO(bitmap));image.load()
        if image.size!=(512,240):raise ValueError('Original GDI atlas dimensions differ')
        mask=image.convert('L').point(lambda v:255 if v==0 else 0)
        self.glyphs={}
        for row in csv.DictReader(io.StringIO(metrics.decode('ascii')),delimiter='\t'):
            r={k:int(v) for k,v in row.items()};code=r['code'];x=r['cell_x'];y=r['cell_y']
            self.glyphs[chr(code)]=(mask.crop((x,y,x+32,y+40)),r['advance'])
        if set(self.glyphs)!={chr(n) for n in range(32,127)}:raise ValueError('Incomplete original GDI atlas')

    def render(self,text):
        if not isinstance(text,str) or not 1<=len(text)<=120 or any(c not in self.glyphs for c in text):
            raise ValueError('Text outside calibrated ASCII atlas')
        width=sum(self.glyphs[c][1] for c in text)+8
        if width>640:raise ValueError('Text wider than the original screen')
        result=Image.new('L',(width,40));x=0
        for c in text:
            glyph,advance=self.glyphs[c]
            layer=Image.new('L',result.size);layer.paste(glyph,(x,0))
            result=ImageChops.lighter(result,layer);x+=advance
        return result


def load_atlas(directory=None):
    directory=Path(directory) if directory is not None else ROOT/'engine/game/gdi-fonts'
    try:
        bitmap=(directory/'times-bold-16.bmp').read_bytes();metrics=(directory/'times-bold-16.tsv').read_bytes()
        if len(bitmap)!=15422 or len(metrics)!=2298:return None
        return _cached_atlas(bitmap,metrics)
    except (OSError,ValueError,UnicodeError):return None


@lru_cache(maxsize=2)
def _cached_atlas(bitmap,metrics):return Atlas(bitmap,metrics)


@lru_cache(maxsize=1)
def _sources():
    with ZipFile(ROOT/'engine/game/civ2-win31.zip') as archive:
        return tuple(archive.read('civ2/'+name).decode('cp1252') for name in ('GAME.TXT','LABELS.TXT'))


def _radio_centers(image,heading,okay):
    pixels=image.load();found=[]
    # Actual original right-side herald layouts: native circle white/black
    # ring, independent of its selected center; no inferred option count.
    for y in range(max(260,heading['center'][1]+24),min(443,okay['center'][1]-15)):
        for x in range(280,336):
            if (all(pixels[x+dx,y+dy]==(255,255,255) for dx,dy in WHITE_RING)
                    and all(pixels[x+dx,y+dy]==(0,0,0) for dx,dy in BLACK_RING)):
                found.append((x,y))
    if (len(found) not in (2,3) or len({x for x,y in found})!=1
            or any(b[1]-a[1]!=25 for a,b in zip(found,found[1:]))
            or found[-1][1]!=427):return []
    return found


def _focus_boundary(image,centers):
    pixels=image.load();matches=[]
    for cx,cy in centers:
        top,bottom=cy-9,cy+10
        a={x for x in range(cx+14,635) if pixels[x,top]==(0,0,0)}
        b={x for x in range(cx+14,635) if pixels[x,bottom]==(0,0,0)}
        if not a or not b:continue
        left,right=min(a|b),max(a|b)
        if left!=cx+16 or not 620<=right<=633 or a&b or a|b!=set(range(left,right+1)):continue
        parity=(min(a)+top)%2
        perimeter=([(x,y) for x in range(left,right+1) for y in (top,bottom)]
                   +[(x,y) for y in range(top+1,bottom) for x in (left,right)])
        if all((pixels[x,y]==(0,0,0))==((x+y)%2==parity) for x,y in perimeter):
            matches.append({'center':[cx,cy],'bounds':[left,top,right+1,bottom+1],'black_parity':parity})
    return matches[0] if len(matches)==1 else None


def _candidate(template,raw):
    # Source literals and every alphanumeric token must remain identical.
    # Variables are observed tokens, then themselves verified by exact pixels.
    if '"' not in raw:return None
    observed=' '.join(_words(raw[raw.index('"'):]))
    parts=re.split(r'(%STRING\d+)',template);pattern=[]
    for part in parts:
        if re.fullmatch(r'%STRING\d+',part):pattern.append('(?P<'+part[1:]+'>[A-Za-z0-9]+(?: [A-Za-z0-9]+){0,8})')
        else:pattern.extend(re.escape(w) for w in _words(part))
    match=re.fullmatch(' '.join(pattern),observed)
    if not match:return None
    result=template
    for key,value in match.groupdict().items():result=result.replace('%'+key,value)
    return result if _words(result)==_words(raw[raw.index('"'):]) else None


def _exact_row(image,atlas,text,center,focus):
    cx,cy=center;region=(cx+17,cy-8,637,cy+10)
    crop=image.crop(region)
    if any(color not in ROW_PALETTE for count,color in crop.getcolors(crop.width*crop.height) or []):return None
    channels=crop.split()
    black=ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2]).point(lambda v:255 if v==0 else 0)
    # Exclude only the independently proven dotted focus perimeter. The left,
    # top and bottom are outside this interior region; its right edge remains.
    if focus['center']==[cx,cy]:
        right=focus['bounds'][2]-1
        for y in range(region[1],region[3]):black.putpixel((right-region[0],y-region[1]),0)
    rendered=atlas.render(text);bbox=rendered.getbbox()
    if bbox is None:return None
    offset=(cx+17-region[0],cy-13-region[1])
    if (bbox[0]+offset[0]<0 or bbox[1]+offset[1]<0 or bbox[2]+offset[0]>black.width
            or bbox[3]+offset[1]>black.height or bbox[2]+cx+17>focus['bounds'][2]-1):return None
    expected=Image.new('L',black.size);expected.paste(rendered,offset)
    if ImageChops.difference(expected,black).getbbox() is not None:return None
    box=[bbox[0]+cx+17,bbox[1]+cy-13,bbox[2]-bbox[0],bbox[3]-bbox[1]]
    return box,{'region':list(region),'region_rgb_sha256':_sha(crop.tobytes()),
                'comparison':'exact black foreground mask; calibrated grayscale background palette',
                'foreground_rgb':[0,0,0],'extra_pixels':0,'missing_pixels':0,
                'textout_origin':[cx+21,cy-9]}


def recover_quoted_herald(image,rows,executable=None,directory=None,evidence=None,*,atlas=None,game_text=None,labels_text=None):
    """Optional observe.py recovery signature; atomic and input-free.

    Every observed radio must match one complete source option. The existing
    classifier must then accept the entire source body and all alternatives.
    """
    if image.size!=(640,480) or not isinstance(rows,list):return False
    if evidence is not None and evidence.get('conflicts'):return False
    headings=[r for r in rows if r['text'].endswith(' Emissary') and r.get('confidence',0)>=.8
              and 200<=r['bounds'][1]<=420 and 420<=r['center'][0]<=485]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK':return False
    heading,okay=headings[0],controls[0]
    if abs(heading['center'][0]-okay['center'][0])>8 or not 450<=okay['center'][1]<=467:return False
    atlas=atlas or load_atlas()
    if atlas is None:return False
    if game_text is None:
        try:game_text,labels_text=_sources()
        except (OSError,KeyError,ValueError,BadZipFile):return False
    from .dialogs import dialog_resources,classify_dialog
    templates=[t for t in dialog_resources(game_text) if t['tag'] in SOURCE_PINS
               and _sha(_canonical(t))==SOURCE_PINS[t['tag']]]
    image=image.convert('RGB');centers=_radio_centers(image,heading,okay)
    if not centers:return False
    pixels=image.load()
    if any(pixels[637,y]!=(65,65,65) or pixels[638,y]!=(65,65,65) or pixels[639,y]!=(0,0,0)
           for y in range(centers[0][1]-11,centers[-1][1]+12)):return False
    focus=_focus_boundary(image,centers)
    if focus is None:return False
    originals=[]
    for cx,cy in centers:
        matches=[r for r in rows if abs(r['center'][1]-cy)<=6 and r['bounds'][0]>=cx-12
                 and r['bounds'][0]<=cx+28 and r['bounds'][3]<=24 and r.get('confidence',0)>=.8
                 and r['bounds'][2]>=100 and '"' in r['text']]
        if len(matches)!=1 or matches[0] in originals:return False
        originals.append(matches[0])
    # An additional observed row in the option area is never silently omitted.
    if any(r not in originals and centers[0][1]-10<=r['center'][1]<=centers[-1][1]+10
           and r['bounds'][0]>=centers[0][0]-12 for r in rows):return False
    proposals={}
    for template in templates:
        source_options=template['options'][:]
        if len(originals)==3 and template['tag']=='EXCHANGE0' and isinstance(labels_text,str) and labels_text.splitlines().count(COUNTEROFFER)==1:
            source_options.append(COUNTEROFFER)
        if len(source_options)!=len(originals):continue
        strings=tuple(_candidate(t,r['text']) for t,r in zip(source_options,originals))
        if any(s is None for s in strings):continue
        replacements=[]
        for raw,text,center in zip(originals,strings,centers):
            try:match=_exact_row(image,atlas,text,center,focus)
            except ValueError:match=None
            if match is None:break
            bounds,proof=match;row=deepcopy(raw);x,y,w,h=bounds
            row.update(text=text,bounds=bounds,center=[round(x+w/2),round(y+h/2)],confidence=1,
                       x=x/640,y=y/480,width=w/640,height=h/480)
            row['provenance']=deepcopy(raw.get('provenance',[]))+[dict(
                preprocessing='original_gdi_exact',text=text,confidence=1,normalized_bounds=[x/640,y/480,w/640,h/480],
                atlas_id=ATLAS_ID,atlas_sha256=ATLAS_SHA256,metrics_sha256=METRICS_SHA256,
                source_template=template['tag'],source_sha256=SOURCE_PINS[template['tag']],
                radio_center=list(center),focus_boundary=focus,**proof)]
            replacements.append(row)
        if len(replacements)!=len(originals):continue
        proposed=deepcopy(rows)
        for old,new in zip(originals,replacements):proposed[rows.index(old)]=new
        # Internal preflight uses an explicitly RGB-derived digest only as an
        # identity placeholder. Its result is discarded; recognize preserves
        # the original PNG hash and the normal later classifier binds that PNG.
        checked=classify_dialog({'width':640,'height':480,'sha256':_sha(image.tobytes()),'lines':proposed},
                                game_text=game_text,labels_text=labels_text)
        if (not checked.get('supported') or not checked.get('requires_model') or checked.get('mechanical_action') is not None
                or checked.get('resource_tag')!=template['tag']
                or tuple(o['text'] for o in checked['options'])!=strings):continue
        proposals[strings]=(proposed,template['tag'])
    if len(proposals)!=1:return False
    proposed,tag=next(iter(proposals.values()));rows[:]=proposed
    if evidence is not None:
        evidence.setdefault('passes',[]).append('original_gdi_exact')
        evidence.setdefault('gdi_exact',[]).append({'atlas_id':ATLAS_ID,'atlas_sha256':ATLAS_SHA256,
            'image_rgb_sha256':_sha(image.tobytes()),'resource_tag':tag,'source_sha256':SOURCE_PINS[tag],
            'radio_centers':[list(p) for p in centers],'complete_options':len(originals),'focus_boundary':focus})
    return True
