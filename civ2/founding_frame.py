"""Exact illustrated FOUNDED frame: retain, but exclude exterior map rows."""
from copy import deepcopy
import hashlib
import json
import re

FRAME = [25,119,617,363]  # exclusive right/bottom
BORDER_REGIONS = [[25,119,617,122],[25,360,617,363],
                  [25,122,28,360],[614,122,617,360]]
BORDER_SHA256 = '4027ddf9c69e077b555e4d46126d95c28aaa607abed6fd5a1f5d7d547692aee4'
BUTTON = [32,331,610,359]
BUTTON_SHA256 = '9b4429563a17a9a7ee24d687c158684e5a030a99cdd578d5fb5c527ee9125ae3'
SOURCE_SHA256 = '1be91b7b018b4aa1cbee458e4d090983ae69135fe6168f569dc65cd594d0f28e'
KIND = 'original-illustrated-founding-frame-v1'


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _title(row):
    x,y,w,h = row['bounds']
    return (row.get('confidence',0) >= .8
            and re.fullmatch(r'f(?:ou|oo)nd new ci(?:t|c)y',row['text'].casefold()) is not None
            and 122 <= y and y+h <= 146 and 260 <= x and x+w <= 380
            and abs(row['center'][0]-320) <= 5)


def _button(row):
    x,y,w,h = row['bounds']
    return (row['text'] == 'OK' and row.get('confidence',0) >= .8
            and 334 <= y and y+h <= 354 and 304 <= x and x+w <= 337
            and abs(row['center'][0]-321) <= 5)


def annotate_founding_frame(image, rows, source_hash):
    """Only attach a hash-bound frame proof; never remove or change OCR rows."""
    if image.size != (640,480) or re.fullmatch('[0-9a-f]{64}',str(source_hash)) is None:
        return False
    titles = [r for r in rows if _title(r)]
    controls = [r for r in rows if r['text'].casefold() in ('ok','cancel','yes','no')]
    if len(titles) != 1 or len(controls) != 1 or not _button(controls[0]):
        return False
    image = image.convert('RGB')
    border_hash = _sha(b''.join(image.crop(region).tobytes() for region in BORDER_REGIONS))
    button_hash = _sha(image.crop(BUTTON).tobytes())
    if border_hash != BORDER_SHA256 or button_hash != BUTTON_SHA256:
        return False
    titles[0]['illustrated_founding_frame'] = dict(kind=KIND,source_image_sha256=source_hash,
        title_bounds=list(titles[0]['bounds']),frame=list(FRAME),border_regions=deepcopy(BORDER_REGIONS),
        border_rgb_sha256=border_hash,button_bounds=list(BUTTON),button_rgb_sha256=button_hash)
    return True


def exterior_body(observation, title, body, controls, resources):
    """Return (interior rows, proof) only for a complete measured source frame.

    This does not decide whether any interior text is a founding notice. The
    caller still requires its complete single city/date line and sole OK.
    """
    if ((observation.get('width'),observation.get('height')) != (640,480)
            or observation.get('ocr',{}).get('conflicts') or not _title(title)
            or len(controls) != 1 or not _button(controls[0])):
        return None
    sources = [r for r in resources if r.get('tag') == 'FOUNDED']
    if len(sources) != 1 or _sha(json.dumps(sources[0],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()) != SOURCE_SHA256:
        return None
    index = title.get('source_line')
    if type(index) is not int or not 0 <= index < len(observation.get('lines',[])):
        return None
    raw = observation['lines'][index]
    proof = raw.get('illustrated_founding_frame')
    expected = dict(kind=KIND,source_image_sha256=observation.get('sha256'),
        title_bounds=title['bounds'],frame=FRAME,border_regions=BORDER_REGIONS,
        border_rgb_sha256=BORDER_SHA256,button_bounds=BUTTON,button_rgb_sha256=BUTTON_SHA256)
    if proof != expected or re.fullmatch('[0-9a-f]{64}',str(expected['source_image_sha256'])) is None:
        return None
    l,t,r,b = FRAME;inside=[];outside=[]
    for row in body:
        x,y,w,h = row['bounds']
        # Touching/crossing any native frame edge is not evidence of an
        # exterior row. Preserve it so the ordinary complete-body check fails.
        if x+w < l or x > r-1 or y+h < t or y > b-1:
            outside.append(row)
        else:
            inside.append(row)
    if not outside or not inside:
        return None
    return inside,dict(**deepcopy(proof),source_template='FOUNDED',source_sha256=SOURCE_SHA256,
        excluded_exterior_rows=[{k:row[k] for k in ('source_line','text','bounds','center','confidence')} for row in outside],
        scope='Only whole OCR rows beyond the exact native frame are excluded from body matching; raw observation unchanged.')
