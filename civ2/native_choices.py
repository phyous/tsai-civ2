"""Small original landing/treaty dialogs; no inputs or automatic choices.

These source contracts have synthetic layout regressions, not live calibration.
Only complete original text and every visible alternative enable a choice.
"""
from copy import deepcopy
import hashlib
import json
import re
import unicodedata


SOURCES = {
    'LANDFALL':dict(tag='LANDFALL',title='Disembark',width=None,
        body='Shall we disembark, Sire, and leave the ships behind?',
        options=['Stay With Ships','Make Landfall'],buttons=[],listbox=False),
    'NOLANDFALL':dict(tag='NOLANDFALL',title='Disembark',width=None,
        body='Our ship cannot enter a land square, and all of the ground units on board have already moved this turn.',
        options=[],buttons=[],listbox=False),
    'NOFOREIGN':dict(tag='NOFOREIGN',title='Foreign Minister',width=320,
        body='We have not yet made contact with other civilizations.',
        options=[],buttons=[],listbox=False),
    'ANNOYPEACE':dict(tag='ANNOYPEACE',title='Foreign Minister',width=320,
        body='We have signed a peace treaty with the %STRING1! Our reputation will be damaged if we break it!',
        options=['Cancel action.','Break treaty.'],buttons=[],listbox=False),
}
KINDS={'LANDFALL':'landfall_choice','ANNOYPEACE':'treaty_break_choice','NOLANDFALL':'information','NOFOREIGN':'information'}
CONTROL_WORDS={'ok','cancel','yes','no','help','continue','close','exit','done','back','next'}


def _normal(text):
    return ' '.join(unicodedata.normalize('NFKC',text).translate(
        str.maketrans({'’':"'",'‘':"'",'“':'"','”':'"'})).casefold().split())


def _control(row,kind):
    return {k:deepcopy(row[k]) for k in ('text','center','source_line','confidence')}|{
        'control':kind,'enabled':None}


def classify_native_choice(observation,rows,resources,rules=None):
    """Rows must come from the common original-geometry validator."""
    if (not isinstance(observation,dict) or (observation.get('width'),observation.get('height'))!=(640,480)
            or not re.fullmatch('[a-f0-9]{64}',str(observation.get('sha256','')))
            or not isinstance(rows,list) or not isinstance(resources,list)
            or observation.get('ocr',{}).get('conflicts')):return None
    matches=[]
    for tag,source in SOURCES.items():
        supplied=[r for r in resources if isinstance(r,dict) and r.get('tag')==tag]
        if supplied!=[source]:continue
        title_names={_normal(source['title'])}
        if tag=='NOFOREIGN':title_names.add('foreign ifinister') # actual isolated3950/48
        if tag=='ANNOYPEACE':title_names.add('foreign mfinister') # actual011/1596
        headings=[r for r in rows if _normal(r['text']) in title_names]
        if len(headings)!=1:continue
        title=headings[0];cx,cy=title['center']
        if title['confidence']<.8 or not 80<=cx<=560 or not 45<=cy<=360:continue
        # Source widths bound the foreground; default-width dialogs receive a
        # conservative440px text region. This is a guard, not a measured border.
        # The original ANNOYPEACE illustration adds horizontal space outside
        # its @width=320 text block: actual011/1596 panel x118..522.
        half=204 if tag=='ANNOYPEACE' else (source['width'] or 440)/2+8
        controls=[r for r in rows if _normal(r['text']) in CONTROL_WORDS]
        if len(controls)!=1 or _normal(controls[0]['text'])!='ok':continue
        ok=controls[0]
        if (ok['confidence']<.8 or abs(ok['center'][0]-cx)>half
                or not 40<=ok['center'][1]-cy<=300 or ok['center'][1]>465):continue
        panel=[r for r in rows if r is not title and r is not ok
               and cy<r['center'][1]<ok['center'][1]
               and abs(r['center'][0]-cx)<=half]
        panel.sort(key=lambda r:(r['bounds'][1],r['bounds'][0]))
        if (not panel or any(r['confidence']<.8 or r['bounds'][0]<cx-half
                            or r['bounds'][0]+r['bounds'][2]>cx+half for r in panel)):continue
        count=len(source['options']);body=panel[:-count] if count else panel
        alternatives=panel[-count:] if count else []
        if not body:continue
        if count:
            if [_normal(r['text']) for r in alternatives]!=[_normal(t) for t in source['options']]:continue
            if (not 14<=alternatives[1]['center'][1]-alternatives[0]['center'][1]<=50
                    or abs(alternatives[0]['bounds'][0]-alternatives[1]['bounds'][0])>24
                    or alternatives[0]['bounds'][1]<body[-1]['bounds'][1]+body[-1]['bounds'][3]
                    or ok['bounds'][1]<alternatives[-1]['bounds'][1]+alternatives[-1]['bounds'][3]+5):continue
        if any(body[i+1]['bounds'][1]-body[i]['bounds'][1]>35 for i in range(len(body)-1)):continue
        text=_normal(' '.join(r['text'] for r in body));expected=source['body'];counterparty=None
        if tag=='ANNOYPEACE':
            names=[r.get('tribe') for r in rules.get('leaders',[]) if isinstance(r,dict)] if isinstance(rules,dict) else []
            named=[name for name in names if isinstance(name,str) and 1<=len(name)<=60
                   and text==_normal(expected.replace('%STRING1',name))]
            if len(named)!=1:continue
            counterparty=named[0]
        elif text!=_normal(expected):continue
        # Any competing title or option text outside this foreground cannot
        # masquerade as a complete second modal behind the proposed control.
        chosen=[title,*panel,ok]
        if any(r not in chosen and (_normal(r['text']) in {_normal(t) for t in source['options']}
                                    or _normal(r['text']) in title_names) for r in rows):continue
        button=_control(ok,'button');model=bool(count)
        evidence=dict(source='original GAME.TXT choice template' if model else 'original GAME.TXT event template',
            source_tag=tag,template_sha256=hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest(),
            resource_sha256=hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),
            source_image_sha256=observation['sha256'],title_source_line=title['source_line'],
            observed_title=title['text'],observed_body='\n'.join(r['text'] for r in body),
            body_source_lines=[r['source_line'] for r in body],
            option_source_lines=[r['source_line'] for r in alternatives],button_source_line=ok['source_line'],
            match='Complete original title and body, all ordered alternatives and sole observed OK',
            calibration=('Original isolated3950 F3 no-contact notice, frame48' if tag=='NOFOREIGN' else
                         'Original attempt011 treaty-break warning, frame1596' if tag=='ANNOYPEACE' else
                         'Source and synthetic-layout validation; no original live modal capture yet'))
        if _normal(title['text'])!=_normal(source['title']):
            evidence['title_recovery']=dict(raw=title['text'],original_title=source['title'],
                source=('Measured original3950 F3 Foreign Ifinister OCR; complete no-contact body independently required'
                        if tag=='NOFOREIGN' else
                        'Measured original011/1596 Foreign Mfinister OCR; complete warning and both alternatives independently required'))
        if counterparty:evidence['observed_counterparty']=counterparty
        matches.append(dict(kind=KINDS[tag],title=title['text'],resource_tag=tag,
            options=[_control(r,'option') for r in alternatives] if model else [button],buttons=[button],
            requires_model=model,mechanical_action=None if model else 'acknowledge_information',evidence=evidence))
    return matches[0] if len(matches)==1 else None
