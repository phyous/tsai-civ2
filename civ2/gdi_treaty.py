"""One source-bound treaty word, proven by the complete original GDI row."""
from copy import deepcopy
import re
from zipfile import BadZipFile
from .gdi_text import load_atlas,_sources,_sha,_canonical,ATLAS_ID,ATLAS_SHA256,METRICS_SHA256,ROW_PALETTE

TREATY_SHA256='cde0f8f6dd9feb79ca49489bc394557a894b7eb78c0a926016f931d86a3da19d'
PALETTE=(ROW_PALETTE-{(0,0,0)})|{(48,48,48)}


def _bits(mask):
    p=mask.load()
    return [sum(1<<x for x in range(mask.width) if p[x,y]) for y in range(mask.height)]


def _exact_row(image,row,text,atlas):
    x,y,w,h=row['bounds']
    if not 302<=x<=320 or not 375<=y<=395 or not 8<=h<=22 or not 100<=w<=330:return None
    crop=(302,y-3,637,y+h+3);region=image.crop(crop).convert('RGB')
    colors=region.getcolors(region.width*region.height)
    if not colors or any(color not in PALETTE for _,color in colors):return None
    mask=atlas.render(text);bounds=mask.getbbox()
    if bounds is None:return None
    mask=mask.crop(bounds);mw,mh=mask.size
    if mw>region.width or mh>region.height:return None
    actual=_bits(region.getchannel('R').point(lambda value:255 if value==48 else 0));expected=_bits(mask)
    if sum(v.bit_count() for v in actual)!=sum(v.bit_count() for v in expected):return None
    matches=[]
    for dx in range(region.width-mw+1):
        shifted=[v<<dx for v in expected]
        for dy in range(region.height-mh+1):
            if actual==[0]*dy+shifted+[0]*(region.height-mh-dy):
                point=[crop[0]+dx,crop[1]+dy,mw,mh]
                if (abs(point[0]+mw/2-row['center'][0])<=8
                        and abs(point[1]+mh/2-row['center'][1])<=5):matches.append(point)
    if len(matches)!=1:return None
    return matches[0],dict(crop=list(crop),region_rgb_sha256=_sha(region.tobytes()),
        foreground_rgb=[48,48,48],palette=sorted([list(c) for _,c in colors]),extra_pixels=0,missing_pixels=0)


def recover_treaty_between(image,rows,evidence=None,*,atlas=None,game_text=None):
    """Correct no word except hetween→between, after exact whole-row proof."""
    if image.size!=(640,480) or (evidence or {}).get('conflicts'):return False
    headings=[r for r in rows if r['text'].endswith(' Emissary') and r['confidence']>=.8
              and 330<=r['center'][1]<=380]
    controls=[r for r in rows if r['text'] in ('OK','Cancel','Yes','No','Help','Goal')]
    if len(headings)!=1 or len(controls)!=1 or controls[0]['text']!='OK' or controls[0]['confidence']<.8:return False
    heading,okay=headings[0],controls[0]
    if abs(heading['center'][0]-okay['center'][0])>8 or not 450<=okay['center'][1]<=467:return False
    body=[r for r in rows if heading['center'][1]<r['center'][1]<okay['center'][1]-12 and 302<=r['bounds'][0]<=320]
    if (len(body)!=4 or any(r['confidence']<.8 for r in body)
            or body[0]['text']!='"We affirm this treaty of eternal friendship and'
            or not re.fullmatch(r'goodwill hetween the people of the [A-Za-z -]{2,40} and',body[1]['text'])
            or not re.fullmatch(r'[A-Za-z -]{2,40} civilizations\. We shall withdraw our',body[2]['text'])
            or body[3]['text']!='forces from your territory at once."'):return False
    atlas=atlas or load_atlas()
    if atlas is None:return False
    if game_text is None:
        try:game_text,_=_sources()
        except (OSError,ValueError,KeyError,BadZipFile):return False
    from .dialogs import dialog_resources,classify_dialog
    templates=[r for r in dialog_resources(game_text) if r['tag']=='TREATY' and _sha(_canonical(r))==TREATY_SHA256]
    if len(templates)!=1:return False
    old=body[1];text=old['text'].replace('goodwill hetween ','goodwill between ',1)
    try:match=_exact_row(image,old,text,atlas)
    except ValueError:return False
    if match is None:return False
    bounds,proof=match;x,y,w,h=bounds;replacement=deepcopy(old)
    replacement.update(text=text,bounds=bounds,center=[round(x+w/2),round(y+h/2)],confidence=1,
                       x=x/640,y=y/480,width=w/640,height=h/480)
    replacement['provenance']=deepcopy(old.get('provenance',[]))+[dict(
        preprocessing='original_gdi_treaty_exact',text=text,confidence=1,normalized_bounds=[x/640,y/480,w/640,h/480],
        atlas_id=ATLAS_ID,atlas_sha256=ATLAS_SHA256,metrics_sha256=METRICS_SHA256,
        source_template='TREATY',source_sha256=TREATY_SHA256,**proof)]
    proposed=deepcopy(rows);proposed[rows.index(old)]=replacement
    # RGB digest is an internal preflight identity only; normal classification
    # later binds the unchanged captured PNG hash supplied by recognize().
    checked=classify_dialog(dict(width=640,height=480,sha256=_sha(image.tobytes()),lines=proposed),game_text=game_text)
    if (not checked.get('supported') or checked.get('resource_tag')!='TREATY' or checked.get('requires_model')
            or checked.get('mechanical_action')!='acknowledge_information'
            or [r['text'] for r in checked.get('buttons',[])]!=['OK']):return False
    rows[:]=proposed
    if evidence is not None:
        evidence.setdefault('passes',[]).append('original_gdi_treaty_exact')
    return True
