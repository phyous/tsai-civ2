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


class DialogObservationError(ValueError):
    pass


def _normal(text):
    return ' '.join(unicodedata.normalize('NFKC',text).translate(str.maketrans({'“':'"','”':'"','’':"'",'‘':"'"})).casefold().split()).strip(' .:!?')


def _pattern(template):
    """A GAME.TXT placeholder matches observed text, never generates a choice."""
    text=_normal(template.replace('^',' '))
    pieces=re.split(r'(%string\d+|%number\d+)',text)
    return ''.join(r'.{1,180}?' if p.startswith('%string') else r'[0-9,+.\-]+' if p.startswith('%number') else re.escape(p) for p in pieces)


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
        rows.append(dict(text=text,normal=_normal(text),center=list(center),bounds=list(bounds),
                         source_line=index,confidence=confidence))
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
    digest=state.get('evidence',{}).get('save_sha256')
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


def _production_stat(text):
    return bool(re.fullmatch(r'\(\d+\s+(?:turns?|tums?)(?:,\s*adm:\s*\d+/\d+/\d+\s+hp:\s*\d+/\d+)?\)',text))


def _native_map_kind(rows, observation, state):
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
    years=[r for r in status if re.fullmatch(r'\d{1,5}\s+(?:b\.?\s*c\.?|a\.?\s*d\.?)',r['normal'])]
    # Original narrow status-font 1 is observed as I/l and 5 as E. This is only a pane
    # layout marker, never an OCR-derived treasury value; economy comes from SAV.
    gold=[r for r in status if re.fullmatch(r'[0-9ile,]{1,16}\s+gold(?:\s+[0-9.]+)?',r['normal'])]
    if len(people)!=1 or len(years)!=1 or len(gold)!=1:
        return None, 'Native population, year and treasury status markers are incomplete'
    if any(r['confidence']<.8 for r in map_titles+worlds+people+years+gold):
        return None, 'Native map pane or status text has low OCR confidence'
    # City labels legitimately appear over the playfield. Only names already in
    # the supplied owned/remembered observation qualify; no unseen city is inferred.
    city_names={_normal(c['name']) for key in ('cities','known_cities') for c in state.get(key,[])
                if isinstance(c,dict) and isinstance(c.get('name'),str)}
    for r in rows:
        if r['bounds'][1]>=65 and r['bounds'][0]<462:
            known_city=r['confidence']>=.8 and any(re.fullmatch(re.escape(name)+r'(?:\s+\(?\d+\)?)?',r['normal']) for name in city_names)
            if not known_city:
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


def classify_dialog(observation, *, rules=None, game_text=None, state=None):
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
    founded=single_title(r'f(?:ou|oo)nd new city')
    if founded:
        if len(founded)!=1 or founded[0]['confidence']<.8:
            return unknown('Founding notice title is ambiguous','founding_notice')
        title=founded[0]
        body,button_rows,_=body_rows(title,{'ok','cancel','yes','no'},600)
        # The illustrated notice can expose unrelated map labels outside its
        # horizontal body band. Only the single actual founding line establishes
        # the notice; other text inside that band would be an unknown modal.
        matching=[(r,re.fullmatch(r'(.+?)\s+founded\s*:\s*(\d{1,5}\s+(?:b\.?\s*c\.?|a\.?\s*d\.?))',r['normal'])) for r in body]
        matching=[(r,m) for r,m in matching if m]
        if len(matching)!=1 or len(body)!=1 or matching[0][0]['confidence']<.8:
            return unknown('Founding notice lacks one complete original founded-city line','founding_notice',title['text'])
        if len(button_rows)!=1 or button_rows[0]['normal']!='ok' or button_rows[0]['confidence']<.8:
            return unknown('Founding notice requires one observed OK button','founding_notice',title['text'])
        result['resource_tag']='FOUNDED'
        result['founded_city']={'name':re.split(r'\s+founded\s*:',matching[0][0]['text'],maxsplit=1,flags=re.I)[0].strip(),
                                'year_text':matching[0][1].group(2),'source':'Original founding notice text'}
        result['observed_city_name']=result['founded_city']['name']
        ok=_option(button_rows[0],'button')
        return finish('information',title['text'],[ok],[ok],mechanical='acknowledge_information',
                      reason='Original founding notice acknowledged after observed title, body and OK')
    patterns={
        'new_city_name':r'what shall we name "?this city',
        'research_choice':r'what discovery shall our .+ pursue',
        'production_choice':r'what shall we build in .+',
        'government_choice':r'select type of government',
        'diplomacy':r'.+ emissary',
        'tax_rate':r'select new tax rate',
        'luxury_rate':r'select new luxury rate',
        'revolution_choice':r'revolution',
        'revolution_offer':r'civ rules: governments',
        'city_locator':r'where in the (?:heck|beck) is',
    }
    matches=[(kind,r) for kind,p in patterns.items() for r in single_title(p)]
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
        city_names={(_saved_city_name(name,state) or {}).get('name',name) for name in city_names}
        rule_names={_normal(r['name']) for table in ('units','improvements') for r in rules.get(table,[]) if r.get('name') and r['name']!='Nothing'}
        approximate=[]
        for title in rows:
            m=re.fullmatch(r'what shall (?:we|me) ([a-z]{3,7}) in (.{1,60})',title['normal'])
            if not m or title['confidence']<.8 or (_edit_distance(m[1],'build')>2 and m[1]!='bodd'):
                continue
            names=[name for name in city_names if _edit_distance(m[2],_normal(name))<=1]
            if len(names)!=1:
                continue
            body,buttons,_=body_rows(title,{'ok','auto','help'},440)
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
        source_width={'research_choice':300,'production_choice':440,'government_choice':240,
                      'new_city_name':460,'diplomacy':440,'tax_rate':260,'luxury_rate':260,
                      'revolution_choice':240,'revolution_offer':440,'city_locator':360}[kind]
        body,button_rows,_=body_rows(title,{'ok','cancel','help','goal','auto','zoom to city'},source_width)
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
            choices=[_option(r,'option') for r in body if r['normal'] in ('yes','no')]
            if 'do we want a revolution to overthrow' not in body_text or {_normal(r['text']) for r in choices}!={'yes','no'}:
                return unknown('Revolution question or both actual alternatives missing',kind,title['text'])
            return finish(kind,title['text'],choices,buttons,model=True)
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
                if row['normal'] in names or (kind=='production_choice' and base in names):
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
        below=[r for r in rows if r['bounds'][1]>title['bounds'][1]+title['bounds'][3]-2 and r not in button_rows]
        actual=' '.join(r['normal'] for r in below)
        found=[]
        for template in templates:
            if not template['body']:continue
            match=re.match(_pattern(template['body']),actual)
            if not match:continue
            # Match choices after the complete body, not phrases quoted by the
            # emissary within the body. Handle OCR-wrapped options in 1..3 rows.
            used=0;after=[]
            for row in below:
                start=used;used+=len(row['normal'])+1
                if start>=match.end():after.append(row)
            options=[];i=0;valid=True
            while i<len(after):
                matches_option=[]
                for count in range(1,min(3,len(after)-i)+1):
                    segment=after[i:i+count]
                    if count>1 and any(segment[j+1]['bounds'][1]-segment[j]['bounds'][1]>28 for j in range(count-1)):continue
                    joined=' '.join(r['normal'] for r in segment)
                    if any(re.fullmatch(_pattern(t),joined) for t in template['options']):
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
            if template['tag'] not in ('DIPLOMACY','TREATYMENU') and len(options)!=len(template['options']):continue
            found.append((template,options))
        if len(found)!=1:return unknown('Diplomatic text/options do not match one complete original template',kind,title['text'])
        template,choices=found[0];result['resource_tag']=template['tag']
        if not choices:
            choices=[_option(r,'button') for r in button_rows if r['normal']=='ok']
            if len(choices)!=1:return unknown('No visible acknowledgement button',kind,title['text'])
            return finish(kind,title['text'],choices,buttons,mechanical='acknowledge_information')
        return finish(kind,title['text'],choices,buttons,model=True)
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
    if city_markers<=labels:
        if re.search(r'\b(?:select|choose|emissary|confirmation|warning|please|really|are you sure)\b',full):
            return unknown('Possible unrecognized foreground modal over the city screen','city_screen')
        buttons=[_option(r,'button') for r in rows if r['normal'] in ('buy','change','info','map','happy','view','rename','exit')
                 and r['center'][0]>width*.65 and r['center'][1]>height*.45]
        if not {'buy','change','exit'}<={_normal(b['text']) for b in buttons}:
            return unknown('City controls incomplete','city_screen')
        titles=[r for r in rows if r['bounds'][1]<height*.15 and ('treasury' in r['normal'] or 'dreasury' in r['normal'])]
        title=titles[0]['text'] if len(titles)==1 else 'Original city screen'
        if len(titles)==1:
            match=re.match(r'city of (.+?),\s*\d+\s+(?:b\.?\s*c\.?|a\.?\s*d\.?)',titles[0]['text'],re.I)
            if match:
                raw_name=match[1].strip()
                result['observed_city_name']=raw_name
                city=_saved_city_name(raw_name,state) if titles[0]['confidence']>=.8 else None
                if city is not None:
                    result['observed_city_name']=city['name']
                    if _normal(city['name'])!=_normal(raw_name):
                        result['city_name_recovery']={'source':'Unique one-edit match to owned city in original save',
                            'ocr_text':raw_name,'canonical_name':city['name'],'city_id':city['id'],
                            'save_sha256':state['evidence']['save_sha256'],'source_line':titles[0]['source_line']}
        return finish('city_screen',title,buttons,buttons,model=True)
    map_kind,map_reason=_native_map_kind(rows,observation,state)
    if map_kind:
        return finish(map_kind,'End of Turn' if map_kind=='end_turn' else 'Original map',reason=map_reason)
    result['reason']=map_reason
    return result


# Short alias for callers that do not need to distinguish OCR and save parsers.
classify = classify_dialog
