"""Original F12 selector and text report; source/synthetic, not live calibrated.

Report values are read, never computed. A Launch button only requests the
separate original LAUNCH confirmation; it cannot itself authorize launch.
"""
from copy import deepcopy
from io import BytesIO
import hashlib
from pathlib import Path
import re
from PIL import Image
from .caravan import _pixel_layout


SOURCES={
    'SPACESHIPS':dict(tag='SPACESHIPS',title='View Which Spaceship',width=320,body='',options=[],buttons=[],listbox=False),
    'SPACESHIP':dict(tag='SPACESHIP',title='Spaceship Report',width=480,
        body='^^%STRING0.S.S. %STRING1 (%STRING2)',options=[],buttons=[],listbox=True),
}
SOURCE_HASHES={'SPACESHIPS':'26d4d16a3257bcb1d34031e89704e674544a489f0cd0154678fbf52f1173c429',
               'SPACESHIP':'86badf089f158b66ccf7466fe69c27e49396555ff377368430b517e9eea06ba1'}
LABELS={8:'OK',10:'Cancel',50:'Population',82:'Support',214:'Structural',215:'Propulsion',216:'Fuel',
    217:'Habitation',218:'Life Support',219:'Solar Panel',221:'Energy',222:'Mass',223:'Flight Time',
    224:'Prob. of Success',225:'tons',226:'years',227:'Launched',228:'Landed',229:'Launch',
    234:'Arrives in',251:'Fusion Powered!'}
PARTS=['Structural','Propulsion','Fuel','Habitation','Life Support','Solar Panel']
EXE_SHA256='b5a64ecbd8ebdd37e3ca2391c57319fec7ac227fcd2c3b9c96498969ea51ef96'
STATIC_SOURCE='Original 1.06 NE22:09a4 report; 22:1127 LABELS Launch; 22:118f LAUNCH confirmation; 22:1d29 selector'


def space_review_available(state):
    """Public Apollo completion or current owned part production only."""
    if not isinstance(state,dict) or state.get('settings',{}).get('bloodlust') is True:return False
    player=state.get('player',{}).get('id')
    if type(player) is not int or not 1<=player<=7:return False
    return (any(isinstance(w,dict) and type(w.get('improvement_id')) is int
                and w['improvement_id']==64 and w.get('status')=='built' for w in state.get('wonders',[]))
        or any(isinstance(c,dict) and c.get('owner')==player and type(c.get('owner')) is int
               and isinstance(c.get('production'),dict) and c['production'].get('kind')=='improvement'
               and type(c['production'].get('id')) is int and c['production']['id'] in (35,36,37)
               for c in state.get('cities',[])))


def _image(observation):
    path=observation.get('path')
    if not isinstance(path,(str,Path)):return None
    try:
        data=Path(path).read_bytes()
        if hashlib.sha256(data).hexdigest()!=observation['sha256']:return None
        with Image.open(BytesIO(data)) as source:
            if source.format!='PNG' or source.size!=(640,480):return None
            return source.convert('RGB')
    except (OSError,ValueError):return None


def _frame(image,title,buttons,width):
    pixels=image.load();found=[];size=width+22;cx=title['center'][0]
    last=max(r['bounds'][1]+r['bounds'][3] for r in buttons)
    for left in range(cx-size//2-3,cx-size//2+4):
        right=left+size-1
        if left<0 or right>=640:continue
        for top in range(max(0,title['bounds'][1]-13),max(0,title['bounds'][1]-3)):
            if not all(pixels[x,top]==(0,0,0) for x in range(left,right+1)):continue
            for bottom in range(last+3,min(480,last+19)):
                if (all(pixels[x,bottom]==(0,0,0) for x in range(left,right+1))
                        and all(pixels[x,y]==(0,0,0) for x in (left,right) for y in range(top,bottom+1))
                        and all(pixels[x,top+1]==(223,223,223) for x in range(left+1,right-1))
                        and all(pixels[right-1,y]==(65,65,65) for y in range(top+2,bottom))):
                    found.append([left,top,right+1,bottom+1])
    return found[0] if len(found)==1 else None


def _button_rectangles(image,frame,buttons):
    """Count all raised native buttons in the bottom band, including OCR loss.

    Black rectangular border, white top bevel and gray130 right bevel were
    independently measured on the original F3 report's three buttons.
    """
    pixels=image.load();left,top,right,bottom=frame;rects=[]
    first=min(r['bounds'][1] for r in buttons)
    for y in range(max(top+20,first-13),first-1):
        start=None;runs=[]
        for x in range(left+3,right-2):
            black=pixels[x,y]==(0,0,0)
            if black and start is None:start=x
            if not black and start is not None:runs.append((start,x-1));start=None
        if start is not None:runs.append((start,right-3))
        for a,b in runs:
            if b-a<25 or not all(pixels[x,y+1]==(255,255,255) for x in range(a+1,b)):continue
            for z in range(y+22,min(y+35,bottom-2)):
                if (all(pixels[x,z]==(0,0,0) for x in range(a,b+1))
                        and all(pixels[x,yy]==(0,0,0) for x in (a,b) for yy in range(y,z+1))
                        and all(pixels[b-1,yy]==(130,130,130) for yy in range(y+3,z))):
                    rects.append([a,y,b+1,z+1])
    if len(rects)!=len(buttons):return None
    associated=[]
    for row in buttons:
        x,y,w,h=row['bounds']
        matches=[r for r in rects if r[0]+3<=x and x+w<=r[2]-3 and r[1]+2<=y and y+h<=r[3]-2
                 and abs((r[0]+r[2]-1)/2-row['center'][0])<=8]
        if len(matches)!=1 or matches[0] in associated:return None
        associated.append(matches[0])
    return associated


def _inside(rows,frame):
    result=[];left,top,right,bottom=frame
    for row in rows:
        x,y,w,h=row['bounds']
        if x+w<=left or x>=right or y+h<=top or y>=bottom:continue
        if not (left<=x and top<=y and x+w<=right and y+h<=bottom) or row['confidence']<.8:return None
        result.append(row)
    return result


def _logical(rows):
    """Join only aligned, nonoverlapping OCR columns; retain every source row."""
    groups=[]
    for row in sorted(rows,key=lambda r:(r['center'][1],r['bounds'][0])):
        if groups and abs(groups[-1][0]['center'][1]-row['center'][1])<=3:groups[-1].append(row)
        else:groups.append([row])
    result=[]
    for group in groups:
        group.sort(key=lambda r:r['bounds'][0])
        if any(a['bounds'][0]+a['bounds'][2]>b['bounds'][0]+1 for a,b in zip(group,group[1:])):return None
        result.append((' '.join(' '.join(r['text'].split()) for r in group),group))
    return result


def _report_values(logical):
    if not 14<=len(logical)<=15:return None
    header=logical[0][0]
    if not re.fullmatch(r"[A-Za-z][A-Za-z '-]{0,39}\.S\.S\. [A-Za-z][A-Za-z .'-]{0,59} \([A-Za-z][A-Za-z '-]{0,39}\)",header):return None
    counts=[]
    for index,part in enumerate(PARTS,1):
        match=re.fullmatch(re.escape(part)+r'\s*:?\s+([0-9]{1,3})(\*)?',logical[index][0])
        if match is None or index!=1 and match[2]:return None
        counts.append({'part':part,'observed_text':logical[index][0],'count':int(match[1]),
                       'observed_asterisk':bool(match[2])})
    number=r'(?:[0-9]{1,7}|[0-9]{1,3}(?:,[0-9]{3}){1,2})'
    specs=[('Population',number),('Support',r'[0-9]{1,3}%'),('Energy',r'[0-9]{1,3}%'),
           ('Mass',number+r' tons'),('Fuel',r'[0-9]{1,3}%(?: Fusion Powered!)?'),
           ('Flight Time',r'[0-9]{1,4}\.[0-9] years'),('Prob. of Success',r'--- [0-9]{1,3}% ---')]
    values={}
    for index,(label,pattern) in enumerate(specs,7):
        match=re.fullmatch(re.escape(label)+r'\s*:?\s+('+pattern+')',logical[index][0])
        if match is None:return None
        values[label]=match[1]
    # Optional native post-launch status is observed prose only, never a
    # transition inferred from a stored counter or the success percentage.
    status=None
    if len(logical)==15:
        status=logical[-1][0]
        if not re.fullmatch(r'--- (?:Landed|Launched! Arrives in [0-9]{1,4}(?: A\.D\.)?)! ---',status):return None
    return {'observed_header':header,'observed_part_counts':counts,'observed_statistics':values,
            'observed_status':status,'scope':'Displayed public report values only; no ship ownership, readiness, launch or victory inferred'}


def classify_spaceship_report(observation,rows,resources,rules,labels_text,game_text):
    if (not isinstance(observation,dict) or (observation.get('width'),observation.get('height'))!=(640,480)
            or not re.fullmatch('[a-f0-9]{64}',str(observation.get('sha256','')))
            or observation.get('ocr',{}).get('conflicts') or not isinstance(rules,dict)
            or not isinstance(labels_text,str) or not isinstance(game_text,str)):return None
    labels=labels_text.splitlines()
    if any(i>=len(labels) or labels[i]!=text for i,text in LABELS.items()):return None
    titles=[r for r in rows if r['text'] in {s['title'] for s in SOURCES.values()}]
    if len(titles)!=1 or titles[0]['confidence']<.8:return None
    title=titles[0];cx,cy=title['center']
    tag='SPACESHIPS' if title['text']==SOURCES['SPACESHIPS']['title'] else 'SPACESHIP';source=SOURCES[tag]
    if [r for r in resources if r.get('tag')==tag]!=[source] or not 280<=cx<=360:return None
    expected={'OK','Cancel'} if tag=='SPACESHIPS' else {'OK','Launch'}
    buttons=[r for r in rows if r['text'] in expected and cy+35<r['center'][1]<470
             and abs(r['center'][0]-cx)<source['width']/2]
    names=[r['text'] for r in buttons]
    if ('OK' not in names or len(names)!=len(set(names)) or (tag=='SPACESHIPS' and set(names)!=expected)
            or (tag=='SPACESHIP' and set(names) not in ({'OK'},expected))
            or max(r['center'][1] for r in buttons)-min(r['center'][1] for r in buttons)>4):return None
    image=_image(observation)
    if image is None:return None
    frame=_frame(image,title,buttons,source['width'])
    if frame is None:return None
    inside=_inside(rows,frame)
    if inside is None:return None
    content=[r for r in inside if r not in [title,*buttons]]
    if (not content or any(r['bounds'][1]<=title['bounds'][1]+title['bounds'][3]
                         or r['bounds'][1]+r['bounds'][3]>=min(b['bounds'][1] for b in buttons)-8 for r in content)):return None
    rectangles=_button_rectangles(image,frame,buttons)
    if rectangles is None:return None
    def control(row,kind):return {k:deepcopy(row[k]) for k in ('text','center','source_line','confidence')}|{'control':kind,'enabled':None}
    proof={'frame_bounds':frame,'frame_rgb_sha256':hashlib.sha256(image.crop(frame).tobytes()).hexdigest(),
           'button_bounds':rectangles,'image_sha256':observation['sha256'],
           'calibration':'Original generic frame/button/radio primitives; spaceship report/selector layout not live calibrated'}
    if tag=='SPACESHIPS':
        blocks=re.findall(r'(?ms)^@SPACESHIPS\s*\n(.*?)(?=^@[A-Z][A-Z0-9_]*\s*$|\Z)',game_text)
        if len(blocks)!=1 or [r.strip() for r in blocks[0].splitlines() if r.strip()]!=[
                '@width=320','@title=View Which Spaceship','@options']:return None
        content.sort(key=lambda r:(r['center'][1],r['center'][0]))
        names=[re.sub(r'^[O○●•]\s+','',r['text']) for r in content]
        known={leader[k] for leader in rules.get('leaders',[]) if isinstance(leader,dict)
               for k in ('tribe','adjective') if isinstance(leader.get(k),str)}
        if not 1<=len(names)<=7 or len(set(names))!=len(names) or any(n not in known for n in names):return None
        radio=_pixel_layout(observation,title,buttons,content,320)
        if radio is None:return None
        proof['radio_centers']=radio['radio_centers'];options=[control(r,'option') for r in content]
        options += [control(r,'button') for r in buttons if r['text']=='Cancel']
        details={'observed_civilization_labels':names,'scope':'Only observed original tribe/adjective labels; no civilization slot or hidden ship inferred'}
        model=True;mechanical=None;kind='spaceship_selector'
    else:
        logical=_logical(content)
        if logical is None:return None
        details=_report_values(logical)
        if details is None:return None
        if details['observed_status'] is not None and 'Launch' in names:return None
        options=[control(r,'button') for r in sorted(buttons,key=lambda r:r['center'][0])]
        model=len(options)>1;mechanical=None if model else 'acknowledge_information';kind='spaceship_report'
    return dict(kind=kind,title=title['text'],resource_tag=tag,options=options,
        buttons=[control(r,'button') for r in buttons],requires_model=model,mechanical_action=mechanical,
        evidence={'spaceship_report':dict(source='Original GAME.TXT/LABELS.TXT and executable report construction',
            resource_sha256=SOURCE_HASHES[tag],labels_sha256=hashlib.sha256(labels_text.encode()).hexdigest(),
            executable_sha256=EXE_SHA256,static_source=STATIC_SOURCE,details=details,pixels=proof,
            source_lines=[r['source_line'] for r in inside],
            scope='Selector and any Launch/OK choice are separate actual model decisions. Launch only requests the original confirmation. Sole report OK only dismisses this complete report.')})
