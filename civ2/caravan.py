"""Source-bound caravan choices, with no automatic cargo or delivery decision.

These layouts have source and synthetic pixel tests, not a live caravan capture.
Only a complete native frame and one original radio per observed choice pass.
The game adjudicates availability, cost and effects after the actual click.
"""
from copy import deepcopy
from functools import lru_cache
from io import BytesIO
import hashlib
from pathlib import Path
import re
from zipfile import BadZipFile
from PIL import Image
from .evidence import canonical
from .gdi_text import WHITE_RING, BLACK_RING


SOURCES={
    'CARAVANMENU':dict(tag='CARAVANMENU',title='%STRING0 Caravan Options',width=320,
        body='',options=[],buttons=[],listbox=False),
    'CARAVANBUILT':dict(tag='CARAVANBUILT',title='Caravan',width=420,
        body='%STRING0 builds %STRING1.  What trade goods shall it carry?',
        options=[],buttons=['Supply And Demand'],listbox=False),
    'CARACONFIRM':dict(tag='CARACONFIRM',title='Caravan',width=320,
        body='Confirm %STRING0 caravan?',options=['Confirmed.','Reconsider.'],
        buttons=['Confirm and Zoom'],listbox=False),
}
SOURCE_HASHES={
    'CARAVANMENU':'c6d7735aba04366496a33004e1c645bb625c37d98125d3ca60bd55d0508a4402',
    'CARAVANBUILT':'f140bda36b813acd35e0a787c5c42b86a58ae05cc23b83ae78c24b915e25f86c',
    'CARACONFIRM':'affa1aa6a78f48bc7a9627478074b5882c3171fdfca3bb3b85b1d256d961281a',
}
COMMODITY_SHA256='467a6d970af9d56a268896a704ae6093002bef9287eea9dbf5a90febfb976d88'
ARRIVAL_OPTIONS=['Keep moving.','Establish trade route.','Help build WONDER.']
NAME=r"[A-Za-z0-9][A-Za-z0-9 .'-]{0,59}"


def _commodities(text):
    if not isinstance(text,str):return None
    lines=text.splitlines()
    if lines.count('@CARAVAN')!=1:return None
    start=lines.index('@CARAVAN')+1
    end=next((i for i in range(start,len(lines)) if lines[i].startswith('@')),len(lines))
    entries=[line.split(';',1)[0].strip() for line in lines[start:end]]
    entries=[line for line in entries if line]
    if any(not re.fullmatch(r'[A-Za-z]+,',line) for line in entries):return None
    names=[line[:-1] for line in entries]
    return names if hashlib.sha256(canonical(names)).hexdigest()==COMMODITY_SHA256 else None


@lru_cache(maxsize=1)
def _original_commodities():
    try:
        from .boot import original_rules
        return _commodities(original_rules())
    except (OSError,ValueError,KeyError,BadZipFile):return None


def _normal(text):return ' '.join(text.split())


def _pixel_layout(observation,title,buttons,choices,width):
    """The entire option band must have exactly the observed native radios."""
    path=observation.get('path')
    if not isinstance(path,(str,Path)):return None
    try:
        data=Path(path).read_bytes()
        if hashlib.sha256(data).hexdigest()!=observation['sha256']:return None
        with Image.open(BytesIO(data)) as source:
            if source.format!='PNG' or source.size!=(640,480):return None
            image=source.convert('RGB')
    except (OSError,ValueError):return None
    pixels=image.load();frames=[];frame_width=width+22
    center=title['center'][0];title_y=title['bounds'][1]
    last=max(r['bounds'][1]+r['bounds'][3] for r in buttons)
    for left in range(center-frame_width//2-3,center-frame_width//2+4):
        right=left+frame_width-1
        if left<0 or right>=640:continue
        for top in range(max(0,title_y-13),max(0,title_y-3)):
            if any(pixels[x,top]!=(0,0,0) for x in range(left,right+1)):continue
            for bottom in range(last+3,min(480,last+19)):
                if (all(pixels[x,bottom]==(0,0,0) for x in range(left,right+1))
                        and all(pixels[x,y]==(0,0,0) for x in (left,right) for y in range(top,bottom+1))
                        and all(pixels[x,top+1]==(223,223,223) for x in range(left+1,right-1))
                        and all(pixels[right-1,y]==(65,65,65) for y in range(top+2,bottom))):
                    frames.append((left,top,right+1,bottom+1))
    if len(frames)!=1:return None
    left,top,right,bottom=frames[0];radios=[]
    # Scan the full native foreground above its buttons, including rows whose
    # text OCR may have omitted. This count cannot come from the text list.
    for y in range(title['bounds'][1]+title['bounds'][3]+9,min(r['bounds'][1] for r in buttons)-9):
        for x in range(left+9,right-9):
            if (all(pixels[x+dx,y+dy]==(255,255,255) for dx,dy in WHITE_RING)
                    and all(pixels[x+dx,y+dy]==(0,0,0) for dx,dy in BLACK_RING)):
                radios.append((x,y))
    if len(radios)!=len(choices) or len({x for x,y in radios})!=1:return None
    if any(not 24<=b[1]-a[1]<=26 for a,b in zip(radios,radios[1:])):return None
    for row,(x,y) in zip(choices,radios):
        if abs(row['center'][1]-y)>5 or not 10<=row['bounds'][0]-x<=32:return None
    return dict(frame_bounds=list(frames[0]),radio_centers=[list(p) for p in radios],
        complete_observed_radio_count=len(radios),image_sha256=observation['sha256'],
        frame_rgb_sha256=hashlib.sha256(image.crop(frames[0]).tobytes()).hexdigest(),
        calibration='Original generic 640x480 frame/radio primitives; caravan layout not live calibrated')


def classify_caravan(observation,rows,resources,rules,labels_text,*,caravan_rules_text=None):
    if (not isinstance(observation,dict) or (observation.get('width'),observation.get('height'))!=(640,480)
            or not re.fullmatch('[a-f0-9]{64}',str(observation.get('sha256','')))
            or observation.get('ocr',{}).get('conflicts') or not isinstance(rows,list)
            or not isinstance(resources,list) or not isinstance(rules,dict) or not isinstance(labels_text,str)):
        return None
    labels=labels_text.splitlines()
    if labels[177:180]!=ARRIVAL_OPTIONS or len(labels)<=80 or labels[80]!='Food':return None
    headings=[r for r in rows if r['text']=='Caravan' or re.fullmatch(NAME+r' Caravan Options',r['text'])]
    if len(headings)!=1:return None
    title=headings[0];cx,cy=title['center']
    if not 280<=cx<=360 or not 40<=cy<=330 or title['confidence']<.8:return None
    available=[tag for tag,source in SOURCES.items()
               if [r for r in resources if isinstance(r,dict) and r.get('tag')==tag]==[source]]
    matches=[]
    for tag in available:
        source=SOURCES[tag];arrival=tag=='CARAVANMENU'
        if arrival != title['text'].endswith(' Caravan Options'):continue
        half=source['width']/2+11
        buttons=[r for r in rows if r['text'] in ['OK',*source['buttons']]
                 and abs(r['center'][0]-cx)<=half and cy+35<r['center'][1]<470]
        if sorted(r['text'] for r in buttons)!=sorted(['OK',*source['buttons']]):continue
        buttons.sort(key=lambda r:r['center'][0]);by=min(r['center'][1] for r in buttons)
        if max(r['center'][1] for r in buttons)-by>5:continue
        panel=[r for r in rows if r is not title and r not in buttons
               and cy<r['center'][1]<by and abs(r['center'][0]-cx)<=half]
        panel.sort(key=lambda r:(r['center'][1],r['center'][0]))
        if (not panel or any(r['confidence']<.8 or r['bounds'][0]<cx-half+3
                or r['bounds'][0]+r['bounds'][2]>cx+half-3 for r in [*panel,*buttons])):continue
        choices=[];body=[];detail={}
        if arrival:
            choices=panel
            names=[r['text'] for r in choices]
            if (not 2<=len(names)<=3 or names[0]!=ARRIVAL_OPTIONS[0]
                    or names!=[name for name in ARRIVAL_OPTIONS if name in names]):continue
            detail={'observed_subject':title['text'][:-len(' Caravan Options')]}
        else:
            commodities=_original_commodities() if caravan_rules_text is None else _commodities(caravan_rules_text)
            if commodities is None:continue
            commodities=[*commodities,'Food']
            if tag=='CARACONFIRM':
                if len(panel)<3:continue
                body,choices=panel[:-2],panel[-2:]
                if [r['text'] for r in choices]!=source['options']:continue
                text=_normal(' '.join(r['text'] for r in body))
                found=[name for name in commodities if text==f'Confirm {name} caravan?']
                if len(found)!=1:continue
                detail={'observed_commodity':found[0],'confirmation_executed':False}
            else:
                split=next((i for i,r in enumerate(panel) if r['text'] in commodities),len(panel))
                body,choices=panel[:split],panel[split:]
                names=[r['text'] for r in choices]
                if (not body or not 1<=len(names)<=4 or len(set(names))!=len(names)
                        or any(name not in commodities for name in names) or 'Food' not in names):continue
                text=_normal(' '.join(r['text'] for r in body))
                found=re.fullmatch('('+NAME+r') builds ('+NAME+r')\. What trade goods shall it carry\?',text)
                if not found:continue
                units=[u for u in rules.get('units',[]) if isinstance(u,dict) and u.get('name')==found[2]
                       and u.get('domain')==0 and u.get('role')==7]
                if len(units)!=1:continue
                detail={'observed_city':found[1],'observed_unit':found[2],
                        'offered_commodities':names,'cargo_selected':False}
        if (any(choices[i+1]['center'][1]-choices[i]['center'][1]<20 for i in range(len(choices)-1))
                or choices[-1]['bounds'][1]+choices[-1]['bounds'][3]>min(r['bounds'][1] for r in buttons)-8
                or (body and body[-1]['bounds'][1]+body[-1]['bounds'][3]>=choices[0]['bounds'][1])):continue
        proof=_pixel_layout(observation,title,buttons,choices,source['width'])
        if proof is None:continue
        left,top,right,bottom=proof['frame_bounds']
        inside=[];bad=False
        for row in rows:
            x,y,w,h=row['bounds']
            if x+w<=left or x>=right or y+h<=top or y>=bottom:continue
            if not (left<=x and top<=y and x+w<=right and y+h<=bottom):bad=True;break
            inside.append(row)
        if bad or len(inside)!=1+len(panel)+len(buttons) or any(r not in [title,*panel,*buttons] for r in inside):continue
        def control(row,kind):
            return {k:deepcopy(row[k]) for k in ('text','center','source_line','confidence')}|{'control':kind,'enabled':None}
        options=[control(r,'option') for r in choices]+[control(r,'button') for r in buttons if r['text']!='OK']
        matches.append(dict(kind={'CARAVANMENU':'caravan_arrival_choice','CARAVANBUILT':'cargo_choice',
            'CARACONFIRM':'cargo_confirmation'}[tag],title=title['text'],resource_tag=tag,
            options=options,buttons=[control(r,'button') for r in buttons],requires_model=True,mechanical_action=None,
            evidence={'caravan_choice':dict(source='Original GAME.TXT, LABELS.TXT and RULES @CARAVAN',
                resource_sha256=SOURCE_HASHES[tag],labels_sha256=hashlib.sha256(labels_text.encode()).hexdigest(),
                commodity_resource_sha256=None if arrival else COMMODITY_SHA256,
                observed_body='\n'.join(r['text'] for r in body),observed_options=[r['text'] for r in choices],
                source_lines=[r['source_line'] for r in [title,*panel,*buttons]],details=detail,pixels=proof,
                scope='Every cargo, confirmation, trade, wonder, movement or report-button choice requires an actual model decision; no delivery or economic effect inferred')}))
    return matches[0] if len(matches)==1 else None
