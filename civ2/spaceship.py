"""Original spaceship allocation and launch confirmations, always model choices.

The original game assembles completed parts itself. This module neither places
parts nor implements the F12 ship report. Its layouts have source and synthetic
pixel coverage; no live spaceship dialog calibration is claimed.
"""
from copy import deepcopy
import hashlib
import re
from .caravan import _pixel_layout


SOURCES={
    'COMPONENT':dict(tag='COMPONENT',title='Select Spaceship Component',width=320,
        body='Propulsion (%NUMBER0 so far) Fuel       (%NUMBER1 so far)',
        options=[],buttons=[],listbox=False),
    'MODULE':dict(tag='MODULE',title='Select Spaceship Module',width=320,
        body='Habitation   (%NUMBER0 so far) Life Support (%NUMBER1 so far) Solar Panel  (%NUMBER2 so far)',
        options=[],buttons=[],listbox=False),
    'LAUNCH':dict(tag='LAUNCH',title='Science Advisor',width=320,
        body='Confirm spaceship launch. (%NUMBER0%% chance of success)',
        options=['No Launch.','Launch CONFIRMED!'],buttons=[],listbox=False),
}
SOURCE_HASHES={
    'COMPONENT':'caa5c7aad6dc44f3a36f4b382c3aea6038f622e05ccecd9329e6709eeef52e1c',
    'MODULE':'b9f15ba7dcb100d83500a3eea26e3eb292197bfae256f4978e00e8e18e80ffe7',
    'LAUNCH':'e5141e606b89c87643aa9898b17101e63df6276292c32acbe581a6c46ae10c62',
}
PARTS={'COMPONENT':['Propulsion','Fuel'],'MODULE':['Habitation','Life Support','Solar Panel']}
OPTION_LINES={
    'COMPONENT':['Propulsion (%NUMBER0 so far)','Fuel       (%NUMBER1 so far)'],
    'MODULE':['Habitation   (%NUMBER0 so far)','Life Support (%NUMBER1 so far)','Solar Panel  (%NUMBER2 so far)'],
}


def _declared_options(game_text,tag):
    """Prove the @options directive that the legacy generic parser omits."""
    lines=game_text.splitlines();starts=[i for i,line in enumerate(lines) if line.strip()=='@'+tag]
    if len(starts)!=1:return False
    start=starts[0]+1
    end=next((i for i in range(start,len(lines)) if re.fullmatch(r'@[A-Z][A-Z0-9_]*',lines[i].strip())),len(lines))
    content=[line.strip() for line in lines[start:end] if line.strip()]
    return content==['@width=320','@title='+SOURCES[tag]['title'],'@options',*OPTION_LINES[tag]]


def _label(text):
    # The optional observed marker remains in the actionable option text.
    return ' '.join(re.sub(r'^[O○●•]\s+','',text).split())


def classify_spaceship(observation,rows,resources,game_text):
    if (not isinstance(observation,dict) or (observation.get('width'),observation.get('height'))!=(640,480)
            or not re.fullmatch('[a-f0-9]{64}',str(observation.get('sha256','')))
            or observation.get('ocr',{}).get('conflicts') or not isinstance(rows,list)
            or not isinstance(resources,list) or not isinstance(game_text,str)):
        return None
    headings=[r for r in rows if r['text'] in {s['title'] for s in SOURCES.values()}]
    if len(headings)!=1:return None
    title=headings[0];cx,cy=title['center']
    if title['confidence']<.8 or not 280<=cx<=360 or not 50<=cy<=320:return None
    controls=[r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no','help','close','exit')]
    if len(controls)!=1 or controls[0]['text']!='OK':return None
    ok=controls[0]
    if ok['confidence']<.8 or abs(ok['center'][0]-cx)>8 or not 65<=ok['center'][1]-cy<=210:return None
    panel=sorted((r for r in rows if r not in (title,ok) and cy<r['center'][1]<ok['center'][1]
                  and abs(r['center'][0]-cx)<=171),key=lambda r:(r['center'][1],r['center'][0]))
    if (not panel or any(r['confidence']<.8 or r['bounds'][0]<cx-168
                        or r['bounds'][0]+r['bounds'][2]>cx+168 for r in panel)):return None
    matches=[]
    for tag,source in SOURCES.items():
        if title['text']!=source['title'] or [r for r in resources if r.get('tag')==tag]!=[source]:continue
        body=[];details={}
        if tag in PARTS:
            if len(panel)!=len(PARTS[tag]) or not _declared_options(game_text,tag):continue
            choices=panel;counts=[]
            for row,part in zip(choices,PARTS[tag]):
                match=re.fullmatch(re.escape(part)+r' \(([0-9]{1,3}) so far\)',_label(row['text']))
                if match is None:break
                counts.append(dict(part=part,count=int(match[1]),observed_text=row['text']))
            if len(counts)!=len(choices):continue
            details={'observed_counts':counts,'allocation_executed':False}
        else:
            if not 3<=len(panel)<=4:continue
            body,choices=panel[:-2],panel[-2:]
            if [_label(r['text']) for r in choices]!=source['options']:continue
            text=' '.join(' '.join(r['text'].split()) for r in body)
            match=re.fullmatch(r'Confirm spaceship launch\. \(([0-9]{1,3})% chance of success\)',text)
            if match is None or not 0<=int(match[1])<=100:continue
            details={'observed_success_percent':int(match[1]),'launch_executed':False,
                     'probability_source':'Original dialog text; no probability calculation'}
        if (choices[-1]['bounds'][1]+choices[-1]['bounds'][3]>ok['bounds'][1]-8
                or (body and body[-1]['bounds'][1]+body[-1]['bounds'][3]>=choices[0]['bounds'][1])):continue
        proof=_pixel_layout(observation,title,[ok],choices,320)
        if proof is None:continue
        # Reuse only generic, originally measured frame/radio primitives; the
        # spaceship-specific placement remains a synthetic guarded fixture.
        proof['calibration']='Original generic 640x480 frame/radio primitives; spaceship layout not live calibrated'
        left,top,right,bottom=proof['frame_bounds'];inside=[];invalid=False
        for row in rows:
            x,y,w,h=row['bounds']
            if x+w<=left or x>=right or y+h<=top or y>=bottom:continue
            if not (left<=x and top<=y and x+w<=right and y+h<=bottom):invalid=True;break
            inside.append(row)
        if invalid or len(inside)!=len(panel)+2 or any(r not in [title,*panel,ok] for r in inside):continue
        def control(row,kind):
            return {k:deepcopy(row[k]) for k in ('text','center','source_line','confidence')}|{'control':kind,'enabled':None}
        matches.append(dict(kind={'COMPONENT':'spaceship_component_choice','MODULE':'spaceship_module_choice',
            'LAUNCH':'spaceship_launch_confirmation'}[tag],title=title['text'],resource_tag=tag,
            options=[control(r,'option') for r in choices],buttons=[control(ok,'button')],
            requires_model=True,mechanical_action=None,
            evidence={'spaceship_choice':dict(source='Original GAME.TXT spaceship choices',
                resource_sha256=SOURCE_HASHES[tag],game_text_sha256=hashlib.sha256(game_text.encode()).hexdigest(),
                options_directive_verified=tag in PARTS,observed_body='\n'.join(r['text'] for r in body),
                observed_options=[r['text'] for r in choices],details=details,pixels=proof,
                source_lines=[r['source_line'] for r in [title,*panel,ok]],
                scope='Every part allocation and launch or cancellation requires an actual model choice; no assembly, launch, arrival or victory inferred')}))
    return matches[0] if len(matches)==1 else None
