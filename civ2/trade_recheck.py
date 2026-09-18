"""Optional offline re-reading of retained original exchange offer pixels.

This does not contact the game or modify evidence. The portable verifier does
not import this path unless its caller explicitly requests the OCR recheck.
"""
import hashlib
from pathlib import Path
from PIL import Image


SOURCE_PINS = {
    'EXCHANGE0': '8fbbf07b8214d9afe08754c3eab0b05744430da1130230e8176b51931c977887',
    'EXCHANGE1': '3662cf980a23d2480897856c6483bdf78525ef439b771dc7cc1fa1abac583dc2',
}


def recheck_foreground(path, source, dialog, action, tag, game_hash):
    """Return the independently reproduced foreground and bounded metadata.

The entire current OCR text must equal the immutable original request. Only
rows wholly above a complete, pixel-verified original herald window may be
excluded. The current source classifier must independently reproduce the
same title, source tag, all options, and selected control coordinates.
"""
    from .dialogs import classify_dialog, dialog_resources, _rows
    from .evidence import canonical
    from .gdi_text import _sources
    from .observe import recognize
    path = Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != source:
        raise ValueError('Retained trade source differs')
    game, labels = _sources()
    if hashlib.sha256(game.encode('utf-8')).hexdigest() != game_hash:
        raise ValueError('Original trade source catalog differs')
    resources = [r for r in dialog_resources(game) if r['tag'] == tag
                 and hashlib.sha256(canonical(r)).hexdigest() == SOURCE_PINS.get(tag)]
    if len(resources) != 1:
        raise ValueError('Original exchange template differs')
    observation = recognize(path)
    if observation.get('sha256') != source or (observation.get('width'), observation.get('height')) != (640, 480):
        raise ValueError('Trade recheck image differs')
    classified = classify_dialog(observation, game_text=game, labels_text=labels)
    if (classified.get('supported') is not True or classified.get('requires_model') is not True
            or classified.get('kind') != 'diplomacy' or classified.get('resource_tag') != tag
            or classified.get('title') != dialog['title']
            or classified.get('visible_text') != dialog['observed_text']
            or [r['text'] for r in classified.get('options', [])] != dialog['options']
            or classified['options'][1].get('center') != action['parameters']['center']):
        raise ValueError('Trade recheck differs from the recorded offer')
    rows = _rows(observation)
    titles = [r for r in rows if r['text'] == dialog['title']]
    if len(titles) != 1 or not 200 <= titles[0]['bounds'][1] <= 420:
        raise ValueError('Trade title geometry differs')
    with Image.open(path) as original:
        if original.format != 'PNG' or original.size != (640, 480):
            raise ValueError('Trade source is not an original PNG')
        image = original.convert('RGB')
    def black(rect):
        return image.crop(rect).getextrema() == ((0, 0),) * 3
    tops = [y for y in range(titles[0]['bounds'][1] - 16, titles[0]['bounds'][1])
            if black((298, y, 640, y + 1))]
    if len(tops) != 1:
        raise ValueError('Trade window top is not unique')
    top = tops[0]
    inside, outside = [], []
    for row in rows:
        x, y, w, h = row['bounds']
        if 298 <= x < x + w <= 640 and top <= y < y + h <= 479:
            inside.append(row)
        elif y + h <= top:
            outside.append(row)
        else:
            raise ValueError('Trade text overlaps or lies beside its window')
    if len(outside) > 8 or any(r['text'].strip().casefold() in ('ok', 'cancel', 'yes', 'no', 'help') for r in outside):
        raise ValueError('Unexpected exterior trade controls')
    # No text is excluded in the one-glyph-only case. A cursor can cover part
    # of the border there; the exact full request is still matched below.
    # Any actual exclusion additionally requires all four complete edges.
    if outside and not all(black(rect) for rect in ((298, top, 299, 479),
                                                   (639, top, 640, 479), (298, 478, 640, 479))):
        raise ValueError('Trade window frame is incomplete')
    if hashlib.sha256(path.read_bytes()).hexdigest() != source:
        raise ValueError('Trade source changed during recheck')
    return (' '.join(r['text'] for r in inside),
            dict(image_sha256=source, resource_tag=tag,
                 source_template_sha256=SOURCE_PINS[tag],
                 window_bounds=[298, top, 640, 479], excluded_above_window_rows=len(outside)))
