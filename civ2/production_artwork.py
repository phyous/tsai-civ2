"""Finite exact original sprite fragments; no guessed text or broad filters."""
import hashlib
import io
from pathlib import Path
from PIL import Image

BOUNDS=[152,149,21,27]
REGION_SHA256='f880f956b50415d9a1d52990bec303285644160a177a1c1d8c84cdca0c9fd049'
CALIBRATION_IMAGE='a59beba943227da6e24f773def68c9be3733fa225e590d3ddbaea5ec9fa49bf5'
PALACE_BOUNDS=[150,292,28,18]
PALACE_REGION_SHA256='c37416142cf29f029a84cf2f7f961b2be7cead1f2183c4dee912967dcd3b0b83'
PALACE_CALIBRATION_IMAGE='91972c77513ac763e9acc6c44bb8d466c3ca8f8587947dc26f8bbd61bac07a57'


def exact_fragment(observation,row):
    if not isinstance(observation,dict) or not isinstance(observation.get('path'),str):return None
    if row.get('bounds')==BOUNDS:
        bounds,digest,calibration,original=BOUNDS,REGION_SHA256,'original-production-pikemen-sprite-fragment-v1',CALIBRATION_IMAGE
    elif row.get('bounds')==PALACE_BOUNDS and row.get('text')=='nill' and row.get('confidence',1)<.5:
        bounds,digest,calibration,original=PALACE_BOUNDS,PALACE_REGION_SHA256,'original-production-palace-sprite-fragment-v1',PALACE_CALIBRATION_IMAGE
    else:return None
    try:
        data=Path(observation['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=observation.get('sha256'):return None
        image=Image.open(io.BytesIO(data));image.load()
        if image.size!=(640,480):return None
        x,y,w,h=bounds;region=image.convert('RGB').crop((x,y,x+w,y+h))
        if hashlib.sha256(region.tobytes()).hexdigest()!=digest:return None
    except (OSError,ValueError):return None
    return dict(calibration=calibration,bounds=list(bounds),
        region_rgb_sha256=digest,calibration_image_sha256=original,
        source_image_sha256=observation['sha256'],
        scope='Exact colored sprite fragment beside a complete independently read label/stat pair; not an option or statistic.')
