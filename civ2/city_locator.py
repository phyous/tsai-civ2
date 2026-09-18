"""Visible foreign labels are locator context, never owned-city targets."""
import hashlib
import io
from pathlib import Path
import re
from PIL import Image
from .evidence import canonical

SOURCE_SHA256='8bdab60c2ec47ca3e291137f4d13ed3513869cd4b72b9d25a470ce43a150f249'
LIST_BORDERS={
    (137,97,503,100):'5adfbe349b0c1601822eb9a97307621f24821595fa809e2a5a337755de5c24f4',
    (137,98,140,378):'ee844ea635639c3ad30edad91cc8339a64473f54d2e2312d5584efc56de83a0c',
    (500,98,503,378):'715d8253c2beecb3b9336482e2e032b419249584a386fdd40545b4e04841029f',
    (137,375,503,378):'443638956e6b0349b54158bae80e6297e7c795ad9916bbab6f7434c7f07fe8d0',
}


def foreign_locator_context(observation,title,body,buttons,owned_names,resources,rules):
    """Prove the fixed native list; return only already-bound owned targets."""
    sources=[r for r in resources if r.get('tag')=='FINDCITY'
             and hashlib.sha256(canonical(r)).hexdigest()==SOURCE_SHA256]
    if (len(sources)!=1 or not isinstance(rules,dict) or not isinstance(observation.get('path'),str)
            or not 1<=len(body)<=16 or len(buttons)!=3
            or {r['normal'] for r in buttons}!={'ok','cancel','zoom to city'}
            or not 78<=title['center'][1]<=90 or not 308<=title['center'][0]<=328):return None
    ordered=sorted(body,key=lambda r:r['center'][1])
    if (any(r['confidence']<.8 or not 141<=r['bounds'][0]<=147
            or not 100<=r['bounds'][1] or r['bounds'][1]+r['bounds'][3]>373
            or r['bounds'][0]+r['bounds'][2]>498 for r in ordered)
            or not 105<=ordered[0]['center'][1]<=114
            or any(not 13<=b['center'][1]-a['center'][1]<=21 for a,b in zip(ordered,ordered[1:]))
            or len({r['normal'] for r in ordered})!=len(ordered)):return None
    positions={'zoom to city':196,'ok':320,'cancel':445}
    if any(r['confidence']<.8 or not 388<=r['center'][1]<=400
           or abs(r['center'][0]-positions[r['normal']])>7 for r in buttons):return None
    adjectives={r['adjective'].casefold() for r in rules.get('leaders',[])
                if isinstance(r,dict) and isinstance(r.get('adjective'),str)}
    owned=[];foreign=[]
    for row in ordered:
        if row['normal'] in owned_names:owned.append(row);continue
        match=re.fullmatch(r"[A-Za-z][A-Za-z '\-]{0,59} \(([A-Za-z][A-Za-z -]{0,39})\)",row['text'])
        if not match or match[1].casefold() not in adjectives:return None
        foreign.append(row)
    if not owned or not foreign:return None
    try:
        data=Path(observation['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=observation.get('sha256'):return None
        image=Image.open(io.BytesIO(data));image.load();image=image.convert('RGB')
        if image.size!=(640,480):return None
        for box in ((130,70,512,71),(130,70,131,412),(511,70,512,412),(130,411,512,412)):
            if image.crop(box).getextrema()!=((0,0),)*3:return None
        if any(hashlib.sha256(image.crop(box).tobytes()).hexdigest()!=digest
               for box,digest in LIST_BORDERS.items()):return None
        bottom=max(r['bounds'][1]+r['bounds'][3] for r in ordered)+3
        if bottom>=373 or image.crop((142,bottom,500,373)).getextrema()!=((207,207),)*3:return None
    except (OSError,ValueError):return None
    fields=lambda row:{k:row[k] for k in ('text','bounds','center','source_line')}
    return owned,dict(source='Original FINDCITY resource and complete calibrated native locator frame',
        source_image_sha256=observation['sha256'],source_template_sha256=SOURCE_SHA256,
        frame_bounds=[130,70,512,412],list_bounds=[140,100,500,374],
        observed_rows=[fields(r) for r in ordered],foreign_context_rows=[fields(r) for r in foreign],
        blank_tail_bounds=[142,bottom,500,373],
        scope='Foreign-labelled rows are retained context only. Only an exact uniquely requested owned-city row can be navigated.')
