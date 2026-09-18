"""Original automatic production upgrade notice: both radio choices stay real."""
from copy import deepcopy
import hashlib
import json
import re

SOURCE=dict(tag='UPGRADED',title='Domestic Advisor',width=320,
    body='Production orders in %STRING0 upgraded from %STRING1 to %STRING2.',
    options=[],buttons=[],listbox=False)


def normal(text):return ' '.join(text.casefold().split())
def radio(text):return re.sub(r'^(?:O|[○●•])\s+','',text)


def _one_edit(a,b):
    if len(a)==len(b):return sum(x!=y for x,y in zip(a,b))<=1
    if abs(len(a)-len(b))!=1:return False
    longer,shorter=(a,b) if len(a)>len(b) else (b,a)
    return any(longer[:i]+longer[i+1:]==shorter for i in range(len(longer)))


def _paired_city_reading(observation,row):
    index=row.get('source_line');lines=observation.get('lines',[])
    if type(index)is not int or not 0<=index<len(lines):return None
    proof=lines[index].get('production_upgrade_city_reading')
    if (not isinstance(proof,dict) or set(proof)!={'source_sha256','native_text','row_bounds','text','readings'}
            or proof['source_sha256']!=observation.get('sha256') or proof['native_text']!=row['text']
            or proof['row_bounds']!=row['bounds'] or not isinstance(proof['text'],str)):return None
    pattern=r'Production orders in ([A-Za-z][A-Za-z -]{1,59}) upgraded from'
    old,new=re.fullmatch(pattern,row['text']),re.fullmatch(pattern,proof['text'])
    if not old or not new or not _one_edit(normal(old[1]),normal(new[1])):return None
    reads=proof['readings'];modes=['upgrade_city_rgb3','upgrade_city_gray3','upgrade_city_rgb2','upgrade_city_gray2']
    if not isinstance(reads,list) or len(reads)!=4:return None
    for reading,mode in zip(reads,modes):
        if (not isinstance(reading,dict) or reading.get('preprocessing')!=mode or reading.get('text')!=proof['text']
                or type(reading.get('confidence'))not in (int,float) or not .8<=reading['confidence']<=1
                or type(reading.get('scale'))is not int or reading['scale']!=int(mode[-1])
                or reading.get('transform')!=('grayscale; bicubic enlargement' if 'gray' in mode else 'bicubic enlargement')):return None
        box=reading.get('normalized_bounds');crop=reading.get('crop')
        if (not isinstance(box,list) or len(box)!=4 or any(type(v)not in (int,float) or not 0<=v<=1 for v in box)
                or not isinstance(crop,list) or len(crop)!=4 or any(type(v)is not int for v in crop)):return None
        x,y,w,h=row['bounds'];bx,by,bw,bh=[v*m for v,m in zip(box,(640,480,640,480))]
        if (bw<=0 or bh<=0 or abs(by+bh/2-row['center'][1])>4
                or abs(bx+bw/2-row['center'][0])>max(6,min(w,bw)*.3)
                or max(0,min(x+w,bx+bw)-max(x,bx))*max(0,min(y+h,by+bh)-max(y,by))<.6*min(w*h,bw*bh)
                or crop!=[max(0,x-3),max(0,y-3),min(640,x+w+3),min(480,y+h+3)]):return None
    return proof


def classify_production_upgrade(observation,rows,resources,rules,state,labels_text):
    if ((observation.get('width'),observation.get('height'))!=(640,480)
            or not re.fullmatch('[a-f0-9]{64}',str(observation.get('sha256','')))
            or not isinstance(rules,dict) or not isinstance(state,dict)
            or not isinstance(labels_text,str) or labels_text.splitlines()[48:50]!=['Zoom to City','Continue']
            or [r for r in resources if r.get('tag')=='UPGRADED']!=[SOURCE]):return None
    titles=[r for r in rows if normal(r['text'])=='domestic advisor']
    controls=[r for r in rows if normal(r['text']) in {'ok','cancel','yes','no','help','close','exit'}]
    if len(titles)!=1 or len(controls)!=1 or normal(controls[0]['text'])!='ok':return None
    title,ok=titles[0],controls[0];cx,cy=title['center']
    if (not 300<=cx<=340 or not 140<=cy<=230 or abs(ok['center'][0]-cx)>8
            or not 100<=ok['center'][1]-cy<=160):return None
    # The original icon expands this320px prose resource to a468px panel.
    left,right=cx-234,cx+234
    conflicts=observation.get('ocr',{}).get('conflicts',[])
    if not isinstance(conflicts,list):return None
    for conflict in conflicts:
        bounds=conflict.get('bounds') if isinstance(conflict,dict) else None
        if (not isinstance(bounds,list) or len(bounds)!=4 or any(type(v)is not int for v in bounds)
                or bounds[2]<=0 or bounds[3]<=0 or bounds[0]<0 or bounds[1]<0
                or bounds[0]+bounds[2]>640 or bounds[1]+bounds[3]>480):return None
        x,y,w,h=bounds
        if x<right and x+w>left and y<ok['bounds'][1]+ok['bounds'][3] and y+h>title['bounds'][1]:return None
    panel=[r for r in rows if r not in (title,ok) and cy<r['center'][1]<ok['center'][1]
           and left<=r['center'][0]<=right]
    if any(r['confidence']<.8 or r['bounds'][0]<left-2 or r['bounds'][0]+r['bounds'][2]>right+2 for r in [*panel,title,ok]):return None
    options=sorted([r for r in panel if radio(r['text']) in ('Zoom to City','Continue')],key=lambda r:r['center'][1])
    if len(options)!=2 or [radio(r['text'])for r in options]!=['Zoom to City','Continue']:return None
    if (not 16<=options[1]['center'][1]-options[0]['center'][1]<=32
            or abs(options[0]['bounds'][0]-options[1]['bounds'][0])>20
            or options[-1]['bounds'][1]+options[-1]['bounds'][3]>ok['bounds'][1]-8):return None
    marks=[]
    for row in panel:
        if row in options or row['text'] not in ('O','○','●','•'):continue
        x,y,w,h=row['bounds']
        if (not 6<=w<=20 or not 6<=h<=20 or len([o for o in options if
                abs(row['center'][1]-o['center'][1])<=3 and 8<=o['bounds'][0]-row['center'][0]<=28])!=1):return None
        marks.append(row)
    prose=sorted([r for r in panel if r not in options and r not in marks],key=lambda r:(r['bounds'][1],r['bounds'][0]))
    if (not 1<=len(prose)<=3 or any(r['bounds'][0]<cx-104 or r['bounds'][1]+r['bounds'][3]>options[0]['bounds'][1]-5 for r in prose)
            or any(b['bounds'][1]-a['bounds'][1]>30 for a,b in zip(prose,prose[1:]))):return None
    body=' '.join(r['text']for r in prose)
    match=re.fullmatch(r'Production orders in (.{1,60}) upgraded from (.{1,60}) to (.{1,60})\.',body)
    if not match:return None
    player=state.get('player',{}).get('id')
    alternate=_paired_city_reading(observation,prose[0]) if len(prose)==2 else None
    observed_names=[match[1]]
    if alternate:
        other=re.fullmatch(r'Production orders in (.{1,60}) upgraded from',alternate['text'])
        observed_names.append(other[1])
    cities=[c for c in state.get('cities',[]) if isinstance(c,dict) and c.get('owner')==player
            and isinstance(c.get('name'),str) and normal(c['name']) in {normal(n) for n in observed_names}]
    units={u['name'] for u in rules.get('units',[]) if isinstance(u,dict) and isinstance(u.get('name'),str)}
    if type(player)is not int or len(cities)!=1 or match[2] not in units or match[3] not in units or match[2]==match[3]:return None
    def control(row,kind):return {k:deepcopy(row[k])for k in ('text','center','source_line','confidence')}|{'control':kind,'enabled':None}
    return dict(kind='production_upgrade_notice',title=title['text'],resource_tag='UPGRADED',
        options=[control(r,'option')for r in options],buttons=[control(ok,'button')],
        evidence=dict(source='Original GAME.TXT UPGRADED and LABELS.TXT49/50',
            template_sha256=hashlib.sha256(json.dumps(SOURCE,sort_keys=True).encode()).hexdigest(),
            observed_body='\n'.join(r['text']for r in prose),body_source_lines=[r['source_line']for r in prose],
            option_source_lines=[r['source_line']for r in options],source_image_sha256=observation['sha256'],
            city_name=cities[0]['name'],previous_unit=match[2],new_unit=match[3],
            city_reading_evidence=deepcopy(alternate),
            background_ocr_conflicts=deepcopy(conflicts),
            scope='Observed notice only; Zoom to City and Continue each require an actual model choice'))
