"""Recognize one visible original TAKECIV list entry; never authorize a choice.

A caller still needs the immediately preceding Jev-accepted exchange and matching
advance before treating its sole continuation as mechanical. This module reads
only the supplied original frame and public original advance specifications.
"""
from io import BytesIO
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from PIL import Image


EMPTY_RECT=(310,186,628,440)
SELECTED_RECT=(580,170,627,183)
ACCEPT='"Okay, let\'s exchange knowledge."'


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def accepted_trade_context(dialog,action,decision,rules):
    """Bind only an already dispatched, source-classified Jev exchange choice.

    The runner must call this after actual dispatch and clear it on any later
    strategic input. A verifier must independently compare the recorded prior
    model action and original source screen; a context hash alone is not proof.
    """
    if (not isinstance(dialog,dict) or not isinstance(action,dict) or not isinstance(rules,dict)
            or type(decision) is not int or decision<1 or dialog.get('supported') is not True
            or dialog.get('kind')!='diplomacy' or dialog.get('requires_model') is not True
            or dialog.get('resource_tag') not in ('EXCHANGE0','EXCHANGE1')
            or not re.fullmatch('[a-f0-9]{64}',str(dialog.get('sha256','')))):
        return None
    options=dialog.get('options');params=action.get('parameters',{});pre=action.get('preconditions',{})
    if (not isinstance(options,list) or len(options) not in (2,3)
            or any(not isinstance(row,dict) for row in options)
            or not isinstance(params,dict) or not isinstance(pre,dict)
            or action.get('kind')!='dialog_choice' or type(params.get('option_index')) is not int or params['option_index']!=1
            or options[1].get('text')!=ACCEPT or params.get('observed_text')!=ACCEPT
            or params.get('center')!=options[1].get('center')
            or pre.get('image_sha256')!=dialog['sha256']
            or action.get('actor')!={'kind':'dialog','id':dialog.get('id'),'title':dialog.get('title')}):
        return None
    decline=options[0].get('text')
    match=re.fullmatch(r'"No\. We do not need ([^".]{1,80})\."',decline) if isinstance(decline,str) else None
    if not match:return None
    advances=[a for a in rules.get('advances',[]) if isinstance(a,dict)
              and type(a.get('id')) is int and a.get('name')==match[1]]
    if len(advances)!=1:return None
    context={'decision':decision,'resource_tag':dialog['resource_tag'],'source_image_sha256':dialog['sha256'],
             'action_sha256':_fingerprint(action),'offered_advance':{'id':advances[0]['id'],'name':advances[0]['name']},
             'accepted_option_index':1,'observed_acceptance_text':ACCEPT,'decline_text':decline}
    return {**context,'context_sha256':_fingerprint(context)}


def _matching_prior_trade(state,advance):
    pending=state.get('pending_trade') if isinstance(state,dict) else None
    keys={'decision','resource_tag','source_image_sha256','action_sha256','offered_advance',
          'accepted_option_index','observed_acceptance_text','decline_text','context_sha256'}
    if (not isinstance(pending,dict) or set(pending)!=keys or type(pending.get('decision')) is not int
            or pending['decision']<1 or pending['resource_tag'] not in ('EXCHANGE0','EXCHANGE1')
            or pending['offered_advance']!=advance or type(pending['accepted_option_index']) is not int or pending['accepted_option_index']!=1
            or pending['observed_acceptance_text']!=ACCEPT
            or pending['decline_text']!=f'"No. We do not need {advance["name"]}."'
            or any(not re.fullmatch('[a-f0-9]{64}',str(pending[k])) for k in ('source_image_sha256','action_sha256','context_sha256'))):
        return None
    payload={k:v for k,v in pending.items() if k!='context_sha256'}
    return deepcopy(pending) if _fingerprint(payload)==pending['context_sha256'] else None


def _distance(a,b):
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):current.append(min(current[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=current
    return row[-1]


def _solid(image,rect,color):
    crop=image.crop(rect)
    return crop.getextrema()==tuple((value,value) for value in color)


def classify_exchange_picker(observation, rows, resources, rules, state=None):
    """Return source/layout proof or None; rows are validated classifier rows.

    Exact geometry is deliberately limited to the measured bottom-right herald
    picker. It cannot establish singleton status for another list or scrollbar.
    No names are invented from the source template or prior strategic context.
    """
    if (not isinstance(observation,dict) or (observation.get('width'),observation.get('height'))!=(640,480)
            or not isinstance(rows,list) or len(rows)!=4 or not isinstance(rules,dict)
            or not isinstance(resources,list)):
        return None
    sources=[r for r in resources if isinstance(r,dict) and r.get('tag')=='TAKECIV']
    if len(sources)!=1:return None
    source=sources[0]
    if (source.get('title')!='Select Civilization Advance' or source.get('width')!=320
            or source.get('listbox') is not True or source.get('buttons')!=['Goal']
            or source.get('body') or source.get('options')):return None
    title,option,goal,ok=sorted(rows,key=lambda r:(r['center'][1],r['center'][0]))
    # Measured bitmap-font OCR loses a few strokes only in Civilization. Keep
    # its raw reading; exact outer words, layout and all independent guards hold.
    match=re.fullmatch(r'Select ([A-Za-z]{9,14}) Advance',title['text'])
    if not match or _distance(match[1].casefold(),'civilization')>3:return None
    if any(r.get('confidence',0)<.8 for r in rows):return None
    if (not 378<=title['bounds'][0]<=398 or not 144<=title['bounds'][1]<=149
            or not 150<=title['center'][1]<=157):return None
    # Goal and OK are on the same bottom line; row sorting can differ by1px.
    controls={r['text']:r for r in (goal,ok)}
    if set(controls)!={'Goal','OK'}:return None
    goal,ok=controls['Goal'],controls['OK']
    if not (370<=goal['center'][0]<=405 and 449<=goal['center'][1]<=466
            and 538<=ok['center'][0]<=565 and 449<=ok['center'][1]<=466):return None
    if not (309<=option['bounds'][0]<=316 and 168<=option['bounds'][1]<=173
            and 173<=option['center'][1]<=180 and option['bounds'][2]<=260):return None
    advances=[a for a in rules.get('advances',[]) if isinstance(a,dict)
              and type(a.get('id')) is int and a.get('name')==option['text']]
    if len(advances)!=1:return None
    path=observation.get('path')
    if not isinstance(path,(str,Path)):return None
    try:
        frame=Path(path).read_bytes()
        if hashlib.sha256(frame).hexdigest()!=observation.get('sha256'):return None
        with Image.open(BytesIO(frame)) as original:
            if original.size!=(640,480):return None
            image=original.convert('RGB')
        if (not _solid(image,EMPTY_RECT,(207,207,207))
                or not _solid(image,SELECTED_RECT,(105,105,105))
                or not _solid(image,(309,170,310,440),(65,65,65))
                or not _solid(image,(628,170,629,440),(65,65,65))):return None
    except (OSError,ValueError):return None
    def control(row,kind):
        return {key:row[key] for key in ('text','center','source_line','confidence')}|{'control':kind,'enabled':None}
    advance={'id':advances[0]['id'],'name':advances[0]['name']}
    pending=_matching_prior_trade(state,advance)
    return dict(title=title['text'],resource_tag='TAKECIV',
        options=[control(option,'list_item')],buttons=[control(goal,'button'),control(ok,'button')],
        advance=advance,requires_model=pending is None,
        mechanical_action='accept_single_trade_advance' if pending is not None else None,
        prior_trade=pending,
        evidence={'source':'Original GAME.TXT TAKECIV and calibrated original list pixels',
            'resource_sha256':hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest(),
            'image_sha256':observation['sha256'],'empty_list_bounds':list(EMPTY_RECT),
            'empty_list_rgb':[207,207,207],'selected_row_bounds':list(SELECTED_RECT),
            'selected_row_rgb':[105,105,105], 'complete_visible_singleton':True,
            'prior_accepted_trade_required':True,'raw_title':title['text']})
