"""Fresh native map-window proof tied to one bracketed original screenshot.

This only permits map artwork in OCR. It never supplies status text, an actor,
click coordinates, or permission to dismiss a modal.
"""
from dataclasses import dataclass
import hashlib
import struct
from pathlib import Path
from io import BytesIO
from copy import deepcopy
from .memory import _validate_capsule, parse_memory, MemoryObservationError

LEFT_MAP_REASON = 'Unexpected text over the native map playfield; possible unrecognized modal'
SCOPE = 'Only left-map artwork; original modal, menu, pane and turn-status checks remain required'


@dataclass(frozen=True)
class NativeMapContext:
    capsule: bytes
    image_sha256: str
    input_sequence: int


def context_for(data, image_sha256, input_sequence):
    capsule, _ = _validate_capsule(data)
    proof = capsule['proof']
    if (type(input_sequence) is not int or proof['input_sequence_after'] != input_sequence
            or image_sha256 != proof['image_sha256'][1]):
        raise MemoryObservationError('Native map context is not the bracketed image at the current input sequence')
    return NativeMapContext(data, image_sha256, input_sequence)


@dataclass(frozen=True)
class FooterBlinkMapContext:
    original: NativeMapContext
    bracketed_png: bytes
    current_png: bytes


def footer_blink_context(context, bracketed_png, current_png):
    """Bind the current image only across a calibrated original footer blink.

    Every other RGB pixel must be identical. Both complete footer crops must
    be the two pinned members of one original white/gray calibration pair.
    This is not a tolerance for changed map art, status numbers or controls.
    """
    from PIL import Image,ImageChops
    from .footer_pixels import FOOTER_BLINK_CALIBRATIONS
    if not isinstance(context,NativeMapContext):raise MemoryObservationError('Missing bracketed native map context')
    context_for(context.capsule,context.image_sha256,context.input_sequence)
    if any(not isinstance(p,bytes) or not 24<=len(p)<=4*1024*1024 for p in (bracketed_png,current_png)):
        raise MemoryObservationError('Invalid footer comparison images')
    if hashlib.sha256(bracketed_png).hexdigest()!=context.image_sha256:
        raise MemoryObservationError('Footer comparison source is not the bracketed image')
    images=[]
    for raw in (bracketed_png,current_png):
        with Image.open(BytesIO(raw)) as image:
            if image.format!='PNG' or image.size!=(640,480):raise MemoryObservationError('Invalid original footer image')
            images.append(image.convert('RGB'))
    matches=[]
    for crop,gray,white in FOOTER_BLINK_CALIBRATIONS:
        hashes=tuple(hashlib.sha256(image.crop(crop).tobytes()).hexdigest() for image in images)
        if hashes in ((gray,white),(white,gray)):matches.append(crop)
    if len(matches)!=1:
        raise MemoryObservationError('Footer difference is not a calibrated original blink')
    crop=matches[0];bounds=ImageChops.difference(*images).getbbox()
    if not bounds or not(crop[0]<=bounds[0]<bounds[2]<=crop[2] and crop[1]<=bounds[1]<bounds[3]<=crop[3]):
        raise MemoryObservationError('Pixels outside the original footer changed')
    return FooterBlinkMapContext(context,bracketed_png,current_png)


def evidence_for(context, observation):
    """Revalidate source bytes; an unchecked dictionary or old image cannot pass."""
    if isinstance(context,FooterBlinkMapContext):
        try:footer_blink_context(context.original,context.bracketed_png,context.current_png)
        except (MemoryObservationError,ValueError,TypeError,OSError):return None
        current_hash=hashlib.sha256(context.current_png).hexdigest()
        if observation.get('sha256')!=current_hash or (observation.get('width'),observation.get('height'))!=(640,480):return None
        original=context.original
        return dict(scope=SCOPE,observation_sha256=hashlib.sha256(original.capsule).hexdigest(),
                    image_sha256=current_hash,image_index=1,input_sequence=original.input_sequence,
                    bracketed_image_sha256=original.image_sha256,
                    current_image_binding='exact_original_footer_blink_only')
    if not isinstance(context, NativeMapContext):
        return None
    try:
        context_for(context.capsule, context.image_sha256, context.input_sequence)
    except (MemoryObservationError, ValueError, TypeError):
        return None
    if (observation.get('sha256') != context.image_sha256
            or (observation.get('width'), observation.get('height')) != (640, 480)):
        return None
    return dict(scope=SCOPE, observation_sha256=hashlib.sha256(context.capsule).hexdigest(),
                image_sha256=context.image_sha256, image_index=1, input_sequence=context.input_sequence)


def archive_read(journal, result, input_sequence):
    """Keep a context read distinct from gameplay checkpoints and their filenames."""
    if not isinstance(result, dict) or set(result) != {'state', 'data', 'receipt'}:
        raise MemoryObservationError('Invalid native map observation result')
    data, receipt = result['data'], deepcopy(result['receipt'])
    capsule, _ = _validate_capsule(data)
    state = parse_memory(data)
    proof = capsule['proof']
    if (not isinstance(receipt, dict) or receipt.get('kind') != 'live_memory'
            or receipt.get('proof') != proof
            or receipt.get('observation_sha256') != hashlib.sha256(data).hexdigest()):
        raise MemoryObservationError('Native map receipt differs from its capsule proof')
    context = context_for(data, proof['image_sha256'][1], input_sequence)
    digest = hashlib.sha256(data).hexdigest()
    token = f'{journal.sequence+1:06d}-{digest}'
    paths = receipt.get('source_images')
    if not isinstance(paths, list) or len(paths) != 3:
        raise MemoryObservationError('Native map context needs three original images')
    images = []
    for index, (source, expected) in enumerate(zip(paths, proof['image_sha256'])):
        path = Path(source)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4*1024*1024:
            raise MemoryObservationError('Invalid native map source image')
        frame = path.read_bytes()
        if (not frame.startswith(b'\x89PNG\r\n\x1a\n') or frame[16:24] != struct.pack('>II',640,480)
                or hashlib.sha256(frame).hexdigest() != expected):
            raise MemoryObservationError('Native map image differs from its proof')
        images.append(journal.artifact(f'screens/native-map-{token}-{index}.png', frame))
    receipt['source_images'] = [image['path'] for image in images]
    receipt['images'] = images
    artifact = journal.artifact(f'observations/native-map-{token}.json', data)
    return state, context, artifact, receipt
