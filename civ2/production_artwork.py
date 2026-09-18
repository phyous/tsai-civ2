"""One exact original sprite fragment; no guessed text or generic digit filter."""
import hashlib
import io
from pathlib import Path
from PIL import Image

BOUNDS=[152,149,21,27]
REGION_SHA256='f880f956b50415d9a1d52990bec303285644160a177a1c1d8c84cdca0c9fd049'
CALIBRATION_IMAGE='a59beba943227da6e24f773def68c9be3733fa225e590d3ddbaea5ec9fa49bf5'


def exact_fragment(observation,row):
    if (not isinstance(observation,dict) or row.get('bounds')!=BOUNDS
            or not isinstance(observation.get('path'),str)):return None
    try:
        data=Path(observation['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=observation.get('sha256'):return None
        image=Image.open(io.BytesIO(data));image.load()
        if image.size!=(640,480):return None
        region=image.convert('RGB').crop((152,149,173,176))
        if hashlib.sha256(region.tobytes()).hexdigest()!=REGION_SHA256:return None
    except (OSError,ValueError):return None
    return dict(calibration='original-production-pikemen-sprite-fragment-v1',bounds=list(BOUNDS),
        region_rgb_sha256=REGION_SHA256,calibration_image_sha256=CALIBRATION_IMAGE,
        source_image_sha256=observation['sha256'],
        scope='Exact colored sprite fragment beside a complete independently read label/stat pair; not an option or statistic.')
