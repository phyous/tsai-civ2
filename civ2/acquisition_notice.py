"""One titleless original acquisition notice, bound to public names and pixels."""
import hashlib
from pathlib import Path
import re
from PIL import Image
from .notice_icons import _frame


def classify_acquisition_notice(observation,rows,labels_text,rules,state):
    if ((observation.get('width'),observation.get('height'))!=(640,480)
            or not isinstance(labels_text,str) or not isinstance(rules,dict) or not isinstance(state,dict)):
        return None
    labels=labels_text.splitlines()
    if len(labels)<=111 or labels[111]!='acquire' or labels.count('acquire')!=1:return None
    tribe=state.get('player',{}).get('tribe')
    if not isinstance(tribe,str) or not 1<=len(tribe)<=40:return None
    controls=[r for r in rows if r['text'].casefold() in {'ok','cancel','yes','no','help','continue','close','exit'}]
    if len(controls)!=1 or controls[0]['text']!='OK' or controls[0]['confidence']<.8:return None
    ok=controls[0];matches=[]
    for row in rows:
        match=re.fullmatch(re.escape(tribe)+r' acquire (.{1,80})!',row['text'])
        if not match or row['confidence']<.8:continue
        advances=[a for a in rules.get('advances',[]) if isinstance(a,dict)
                  and type(a.get('id')) is int and a.get('name')==match[1]]
        if len(advances)==1:matches.append((row,advances[0]))
    if len(matches)!=1:return None
    body,advance=matches[0];x,y,w,h=body['bounds']
    if (not 185<=x<=215 or not 200<=y<=245 or not 80<=w<=310 or h>24
            or not 310<=ok['center'][0]<=330 or not 24<=ok['center'][1]-body['center'][1]<=64):return None
    path=observation.get('path')
    if not isinstance(path,(str,Path)):return None
    try:
        data=Path(path).read_bytes()
        if hashlib.sha256(data).hexdigest()!=observation.get('sha256'):return None
        with Image.open(path) as original:
            if original.format!='PNG' or original.size!=(640,480):return None
            pixels=original.convert('RGB').load()
        frames=[(left,top) for left in range(x-84,x-71) for top in range(y-8,y+5)
                if 0<=left<=568 and 0<=top<=440 and _frame(pixels,left,top)]
    except (OSError,ValueError):return None
    if len(frames)!=1:return None
    left,top=frames[0];window=(left-10,top-30,left+400,ok['bounds'][1]+ok['bounds'][3]+10)
    # Other map/status text can remain behind the original notice. Unknown
    # text inside its actual illustrated body/control band cannot be ignored.
    inside=[r for r in rows if window[0]<=r['center'][0]<=window[2]
            and window[1]<=r['center'][1]<=window[3]]
    if any(r is not body and r is not ok for r in inside):return None
    button={key:ok[key] for key in ('text','center','source_line','confidence')}
    button.update(control='button',enabled=None)
    return {'title':body['text'],'resource_tag':'LABELS_ACQUIRE_ADVANCE','button':button,
        'evidence':{'source':'Original LABELS.TXT acquisition verb and observed original illustrated notice',
            'labels_sha256':hashlib.sha256(labels_text.encode()).hexdigest(),'label_line':111,
            'image_sha256':observation['sha256'],'body_source_line':body['source_line'],
            'observed_text':body['text'],'observed_player_tribe':tribe,
            'original_advance':{'id':advance['id'],'name':advance['name']},
            'icon_frame':[left,top,72,40],
            'effect_scope':'Acknowledge visible text only; acquisition is not inferred from input'}}
