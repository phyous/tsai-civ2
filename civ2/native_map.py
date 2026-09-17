"""Fresh native map-window proof tied to one bracketed original screenshot.

This only permits map artwork in OCR. It never supplies status text, an actor,
click coordinates, or permission to dismiss a modal.
"""
from dataclasses import dataclass
import hashlib
import struct
from pathlib import Path
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


def evidence_for(context, observation):
    """Revalidate source bytes; an unchecked dictionary or old image cannot pass."""
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
