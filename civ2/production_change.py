"""Original production-category penalty: always a separate model choice."""
from copy import deepcopy
import hashlib
import json
import re

SOURCE=dict(tag='PRODCHANGE',title='Civ Rules: Change of Production',width=320,
    body='Sire, if we change our production between items of different general types (Units, City Improvements, Wonders of the World), there is a %NUMBER0%% production penalty.',
    options=['Continue producing %STRING0.','Switch to %STRING1 at %NUMBER0%% penalty.'],buttons=[],listbox=False)
TITLE_READINGS={'civ rules: change of production','civ pules: change of froduction'}


def _normal(text):return ' '.join(text.casefold().split())
def _label(text):return re.sub(r'^[•○●O0]\s+','',text)


def classify_production_change(observation,rows,resources,rules):
    if ((observation.get('width'),observation.get('height'))!=(640,480)
            or not re.fullmatch(r'[a-f0-9]{64}',str(observation.get('sha256','')))
            or not isinstance(rules,dict) or observation.get('ocr',{}).get('conflicts')
            or [r for r in resources if r.get('tag')=='PRODCHANGE']!=[SOURCE]):return None
    titles=[r for r in rows if _normal(r['text']) in TITLE_READINGS]
    if len(titles)!=1:return None
    title=titles[0];cx,cy=title['center']
    if not 280<=cx<=360 or not 90<=cy<=230 or title['confidence']<.8:return None
    buttons=[r for r in rows if _normal(r['text'])=='ok' and abs(r['center'][0]-cx)<=12
             and 120<=r['center'][1]-cy<=220]
    if len(buttons)!=1:return None
    ok=buttons[0];left,right=cx-174,cx+174
    panel=[r for r in rows if r not in (title,ok) and cy<r['center'][1]<ok['center'][1]
           and left<=r['center'][0]<=right]
    panel.sort(key=lambda r:(r['bounds'][1],r['bounds'][0]))
    if (len(panel)<3 or ok['confidence']<.8
            or any(r['confidence']<.8 or r['bounds'][0]<left or r['bounds'][0]+r['bounds'][2]>right for r in panel)):return None
    body,options=panel[:-2],panel[-2:]
    old=re.fullmatch(r'Continue producing (.{1,80})\.',_label(options[0]['text']))
    new=re.fullmatch(r'Switch to (.{1,80}) at (\d{1,3})% penalty\.',_label(options[1]['text']))
    if not old or not new or not 0<=int(new[2])<=100:return None
    names=[r['name'] for table in ('units','improvements') for r in rules.get(table,[]) if isinstance(r,dict) and isinstance(r.get('name'),str)]
    if old[1] not in names or new[1] not in names or old[1]==new[1]:return None
    expected=SOURCE['body'].replace('%NUMBER0%%',new[2]+'%')
    if _normal(' '.join(r['text'] for r in body))!=_normal(expected):return None
    if (not 14<=options[1]['center'][1]-options[0]['center'][1]<=40
            or abs(options[0]['bounds'][0]-options[1]['bounds'][0])>28
            or body[-1]['bounds'][1]+body[-1]['bounds'][3]>options[0]['bounds'][1]
            or options[-1]['bounds'][1]+options[-1]['bounds'][3]>ok['bounds'][1]-5):return None
    if any(_normal(r['text']) in {'cancel','yes','no','help','ok'} for r in panel):return None
    if any(body[i+1]['bounds'][1]-body[i]['bounds'][1]>30 for i in range(len(body)-1)):return None
    def control(row,kind):
        return {k:deepcopy(row[k]) for k in ('text','center','source_line','confidence')}|{'control':kind,'enabled':None}
    return dict(kind='production_change_choice',title=title['text'],resource_tag='PRODCHANGE',
        options=[control(r,'option') for r in options],buttons=[control(ok,'button')],
        production_change=dict(current_item=old[1],proposed_item=new[1],penalty_percent=int(new[2]),executed=False),
        evidence=dict(source='original GAME.TXT production-category confirmation',
            template_sha256=hashlib.sha256(json.dumps(SOURCE,sort_keys=True).encode()).hexdigest(),
            image_sha256=observation['sha256'],title_source_line=title['source_line'],
            observed_title=title['text'],observed_body='\n'.join(r['text'] for r in body),
            body_source_lines=[r['source_line'] for r in body],option_source_lines=[r['source_line'] for r in options],
            title_match='exact' if _normal(title['text'])==_normal(SOURCE['title']) else 'Original0111068 reviewed OCR title',
            scope='Two actual choices; neither original selection nor prior production request commits this penalty'))
