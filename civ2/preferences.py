"""Verified original UI preferences for explicit turn review and clear recording."""
from pathlib import Path
import re
from .cursor import move_cursor
from PIL import Image

# Original 640x480 Win3.1 preference checkboxes. The trailing checkmark can extend
# beyond its square. Only observed black/white/gray classes are matched; each
# probe must resolve uniquely near its independently observed option label.
CHECKED = (
    'BB............W..BBBB.', 'B............W..BBB...', 'B...........W..BBB....',
    'B..........W..BBB.....', 'BW........W..BBBB.....', 'B...........BBBWB.....',
    'B.B......W.BBB.WB.....', 'B..B....W..BB..WB.....', 'B...B.....BB...WB.....',
    'B....B...BBB...WB.....', 'B........BB....WB.....', 'B.....B.BB.....WB.....',
    'B......BBB.....WB.....', 'W.......B.....WWB.....', 'WWWWWWWWWWWWWWWBB.....')
UNCHECKED = ('BB.............WB.....',) + ('B..............WB.....',)*12 + (
    'W.............WWB.....', 'WWWWWWWWWWWWWWWBB.....')


def checkbox_state(observation, label):
    key=lambda text:re.sub(r'[^a-z0-9]','',text.casefold())
    matches=[row for row in observation['lines'] if key(label) in key(row['text'])]
    if len(matches)!=1 or observation.get('width')!=640 or observation.get('height')!=480:
        raise ValueError('Preference needs one observed label in the original screen')
    row=matches[0]
    if not 85<=row['bounds'][0]<=125 or not 95<=row['center'][1]<=365:
        raise ValueError('Preference label is outside the verified native dialog')
    with Image.open(Path(observation['path'])) as image:
        pixels=image.convert('RGB').load()
        candidates=[]
        for y in range(row['center'][1]-13,row['center'][1]-3):
            actual=tuple(''.join('B' if max(pixels[x,yy])<80 else 'W' if min(pixels[x,yy])>230 else '.'
                                 for x in range(90,112)) for yy in range(y,y+15))
            for value,pattern in ((True,CHECKED),(False,UNCHECKED)):
                if actual==pattern:candidates.append((value,y))
    if len(candidates)!=1:
        raise ValueError('Original preference checkbox was not uniquely observed')
    return candidates[0][0]


def configure_preferences(ui):
    """Ordinary display/turn-wait options; no difficulty or game-rule edits."""
    ui.game.rpc('resume')
    before=ui.observe()
    inputs=ui.game.chord('ControlLeft','KeyO',hold_ms=120)
    observation=ui.wait(lambda o:'always wait at end of turn' in o['text'].casefold()
                        and 'instant advice' in o['text'].casefold())
    opening=observation['sha256'];changes=[]
    for label,wanted in (('Always wait at end of turn',True),('Instant advice',False)):
        prior=checkbox_state(observation,label)
        receipt=None
        if prior!=wanted:
            # Keep the checkbox visible while clicking its observed label, then
            # park the arrow before both text and checkmark readback.
            key=lambda text:re.sub(r'[^a-z0-9]','',text.casefold())
            actual=next(row['text'] for row in observation['lines'] if key(label) in key(row['text']))
            receipt=ui.select_text(observation,actual,exact=True)
            receipt['pointer_park']=move_cursor(ui.game,620,410)
            observation=ui.observe()
            if checkbox_state(observation,label)!=wanted:
                raise RuntimeError('Native preference did not reach its requested state')
        changes.append(dict(label=label,before=prior,after=wanted,receipt=receipt,
                            verified_image=observation['sha256']))
    inputs+=ui.key('Enter',settle=1.2)
    after=ui.observe()
    return dict(before=before['sha256'],opening=opening,changes=changes,inputs=inputs,after=after['sha256'])


GRAPHICS_LABELS = ('Throne Room','Diplomacy Screen','Animated Heralds',
                   'Civilopedia for Advances','High Council','Wonder Movies')


def configure_graphics_preferences(ui):
    """Disable only the native post-discovery reference popup, with readback.

    Original MENU.TXT Ctrl+P / GAME.TXT @GRAPHICOPTIONS. Calibrated in the
    original 640x480 dialog; these are presentation settings, not game rules.
    Other checkbox values are observed before/after and must remain unchanged.
    """
    return _configure_graphics_option(ui, 'Civilopedia for Advances',
        'Original presentation preference only; no gameplay command')


def configure_throne_presentation(ui):
    """Disable the cosmetic Throne Room only, at a known native-map boundary.

    The original manual permits ignoring this presentation with no repercussions.
    All five other graphics checkboxes must remain equal to their observed values.
    """
    return _configure_graphics_option(ui, 'Throne Room',
        'Original cosmetic Throne Room presentation only; no gameplay command')


def _configure_graphics_option(ui, label, scope):
    key=lambda text:re.sub(r'[^a-z0-9]','',text.casefold())
    def complete(o):
        labels=[key(row['text']) for row in o['lines']]
        return (all(any(key(name) in text for text in labels) for name in GRAPHICS_LABELS)
                and labels.count('ok')==1 and labels.count('cancel')==1)
    ui.game.rpc('resume')
    before=ui.observe()
    inputs=ui.game.chord('ControlLeft','KeyP',hold_ms=120)
    observation=ui.wait(complete)
    opening=observation['sha256']
    prior={name:checkbox_state(observation,name) for name in GRAPHICS_LABELS}
    receipt=None
    if prior[label]:
        actual=next(row['text'] for row in observation['lines'] if key(label) in key(row['text']))
        receipt=ui.select_text(observation,actual,exact=True)
        receipt['pointer_park']=move_cursor(ui.game,620,410)
        observation=ui.observe()
    if not complete(observation):
        raise RuntimeError('Native graphics dialog changed during preference readback')
    after={name:checkbox_state(observation,name) for name in GRAPHICS_LABELS}
    if after[label] is not False or any(after[name]!=prior[name] for name in GRAPHICS_LABELS if name!=label):
        raise RuntimeError('Native graphics preference changed unexpectedly')
    verified_image=observation['sha256']
    inputs+=ui.key('Enter',settle=1.2)
    closed=ui.observe()
    return dict(before=before['sha256'],opening=opening,
        changes=[dict(label=label,before=prior[label],after=False,receipt=receipt,verified_image=verified_image)],
        checkbox_before=prior,checkbox_after=after,other_checkboxes_unchanged=True,
        inputs=inputs,after=closed['sha256'],scope=scope)
