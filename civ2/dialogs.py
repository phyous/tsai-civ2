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

import math
import re
import unicodedata


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
    gold=[r for r in status if re.fullmatch(r'[0-9,]+\s+gold(?:\s+[0-9.]+)?',r['normal'])]
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


def classify_dialog(observation, *, rules=None, game_text=None, state=None):
    """Return supported/unknown classification with exact visible option targets.

    ``options`` contains decision choices; ``buttons`` contains observed native
    auxiliary controls. Do not dispatch from a result with supported=False.
    Terminal text is a cue for human verification, not an automatic victory.
    """
    rows=_rows(observation);width,height=observation['width'],observation['height']
    result=dict(id='unknown',kind='unknown',supported=False,title='',width=width,height=height,
                sha256=observation['sha256'],options=[],buttons=[],requires_model=False,
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
    patterns={
        'new_city_name':r'what shall we name this city',
        'research_choice':r'what discovery shall our .+ pursue',
        'production_choice':r'what shall we build in .+',
        'government_choice':r'select type of government',
        'diplomacy':r'.+ emissary',
        'tax_rate':r'select new tax rate',
        'luxury_rate':r'select new luxury rate',
        'revolution_choice':r'revolution',
        'revolution_offer':r'civ rules: governments',
        'city_locator':r'where in the heck is',
    }
    matches=[(kind,r) for kind,p in patterns.items() for r in single_title(p)]
    if len(matches)>1:return unknown('Multiple recognized native dialog titles')
    if matches:
        kind,title=matches[0]
        if title['confidence']<.8:return unknown('Low-confidence title',kind,title['text'])
        source_width={'research_choice':300,'production_choice':440,'government_choice':240,
                      'new_city_name':320,'diplomacy':440,'tax_rate':260,'luxury_rate':260,
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
            if len(labels)!=1 or not any(r['normal']=='ok' for r in button_rows):
                return unknown('Name prompt or visible OK is missing',kind,title['text'])
            label=labels[0];suffix=label['text'].partition(':')[2].strip()
            values=[r for r in body if r is not label and -18<=r['center'][1]-label['center'][1]<=48]
            if suffix:
                result['default_name']=suffix
            elif len(values)==1:
                result['default_name']=values[0]['text']
            else:return unknown('Default city name is unreadable or ambiguous',kind,title['text'])
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
            choices=[];unknown_rows=[]
            for row in body:
                # Production suffixes must be native parenthesized stat/turn
                # annotations; no prefix stripping of unknown OCR glyphs.
                base=re.sub(r'\s+\([^()]*\)\s*$','',row['normal'])
                if row['normal'] in names or (kind=='production_choice' and base in names):
                    if row['confidence']<.8:return unknown('Low-confidence option text',kind,title['text'])
                    choices.append(_option(row,'list_item'))
                elif re.fullmatch(r'[0-9]+\s+turns?',row['normal']):
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
    info_titles=[r for r in rows if (r['normal'] in ('game saved','in the beginning','found new city','civilization advance')
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
    city_markers={'foodstorage','cityresources','unitssupported','unitspresent','resourcemap'}
    if city_markers<=labels:
        buttons=[_option(r,'button') for r in rows if r['normal'] in ('buy','change','info','map','happy','view','rename','exit')
                 and r['center'][0]>width*.65 and r['center'][1]>height*.45]
        if not {'buy','change','exit'}<={_normal(b['text']) for b in buttons}:
            return unknown('City controls incomplete','city_screen')
        titles=[r for r in rows if r['bounds'][1]<height*.15 and ('treasury' in r['normal'] or 'dreasury' in r['normal'])]
        title=titles[0]['text'] if len(titles)==1 else 'Original city screen'
        return finish('city_screen',title,buttons,buttons,model=True)
    map_kind,map_reason=_native_map_kind(rows,observation,state)
    if map_kind:
        return finish(map_kind,'End of Turn' if map_kind=='end_turn' else 'Original map',reason=map_reason)
    result['reason']=map_reason
    return result


# Short alias for callers that do not need to distinguish OCR and save parsers.
classify = classify_dialog
