"""Synthetic TEST pixels plus optional retained original paragraph regressions."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
from civ2 import gdi_bodies as g
from civ2.dialogs import classify_dialog
from tests.test_gdi_text import TestAtlas
from tests.test_herald import prepared

SOURCES = {
 'PROPOSECEASE': ('"The %STRING1 people grow weary of this endless war. We suggest a cease fire."',
                 ['"We accept--let us end this terrible war."', '"Cowards! We shall fight to the bitter end!"']),
 'CRUSADE': ('"We invite you to join our crusade to rid the world of the evil %STRING1. We will %STRING2 alliance for the duration of the hostilities."',
             ['"No, not interested."', 'Yes, declare war on %STRING1.']),
 'GREETINGS00': ('"Greetings from the most exalted %STRING1: %STRING2 of the %STRING3_._._."', []),
 'GREETINGS03': ('"I speak for %STRING5 who makes mortals tremble: %STRING2 %STRING1 of the %STRING3_._._."', []),
}
TEXTS = {
 'PROPOSECEASE': ['"The TEST people grow weary of this endless', 'war. We suggest a cease fire."'],
 'CRUSADE': ['"We invite you to join our crusade to rid the', 'world of the evil TEST. We will sign an alliance', 'for the duration of the hostilities."'],
 'GREETINGS00': ['"Greetings from the most exalted TEST:', 'King of the TEST . . ."'],
 'GREETINGS03': ['"I speak for she who makes mortals tremble:', 'Empress TEST of the TEST . . ."'],
}


def source(tag):
    body, options = SOURCES[tag]
    return f'@{tag}\n@width=320\n@title=%STRING0 Emissary\n{body}\n\n' + '\n'.join(options) + '\n'


class BearingAtlas(TestAtlas):
    def render(self, text):
        mask = super().render(text)
        # Independently exercise a negative left bearing at the native origin.
        if text.startswith('w'):
            mask.putpixel((3, 11), 255)
        return mask


def fixture(tag='PROPOSECEASE'):
    image = Image.new('RGB', (640, 480), (190, 190, 190))
    left, top, inset, count, radios, _ = g.LAYOUTS[tag]
    p = image.load()
    for x in range(left, 640):
        p[x, top] = p[x, 478] = (0, 0, 0)
    for y in range(top, 479):
        p[left, y] = p[639, y] = (0, 0, 0)
    for x in range(left + 1, 638):
        p[x, top + 1] = (223, 223, 223)
    for y in range(top + 1, 478):
        p[left + 1, y] = (223, 223, 223)
    for x in (637, 638):
        for y in range(top + 2, 478):
            p[x, y] = (65, 65, 65)
    for x in range(left + 2, 639):
        p[x, 477] = (65, 65, 65)
    atlas = BearingAtlas()
    rows = [prepared('TEST Emissary', 400, top + 6, 136, 18)]
    for i, text in enumerate(TEXTS[tag]):
        mask = atlas.render(text)
        mask.paste(0, (0, 0, 4, mask.height))
        ox, oy = left + inset - 4, top + 26 + 20 * i
        image.paste((48, 48, 48), (ox, oy), mask)
        x, y, right, bottom = mask.getbbox()
        raw = text.replace(' . . .', '..').replace('"', '')
        rows.append(prepared(raw, ox + x, oy + y, right - x, bottom - y))
    for i, option in enumerate(SOURCES[tag][1]):
        cx, cy = left + 95, 402 + 25 * i
        for dx, dy in g.WHITE_RING:
            p[cx + dx, cy + dy] = (255, 255, 255)
        for dx, dy in g.BLACK_RING:
            p[cx + dx, cy + dy] = (0, 0, 0)
        text = option.replace('%STRING1', 'TEST')
        rows.append(prepared(text, cx + 18, cy - 8, 260, 16))
    button = (left + 7, 447, 633, 475)
    ImageDraw.Draw(image).rectangle((button[0], 447, 632, 474), fill=(195, 195, 195), outline=(0, 0, 0))
    rows.append(prepared('OK', 456, 454, 26, 16))
    layout = (*g.LAYOUTS[tag][:-1], g._sha(image.crop(button).tobytes()))
    return image, rows, atlas, layout


def recover(image, rows, atlas, layout, tag='PROPOSECEASE', evidence=None, game_text=None):
    with patch.dict(g.LAYOUTS, {tag: layout}):
        return g.recover_herald_paragraph(image, rows, evidence=evidence, atlas=atlas,
                                         game_text=source(tag) if game_text is None else game_text)


class ParagraphTests(unittest.TestCase):
    def test_four_sources_keep_words_provenance_and_original_decisions(self):
        for tag in SOURCES:
            with self.subTest(tag=tag):
                image, rows, atlas, layout = fixture(tag)
                before = deepcopy(rows)
                e = {}
                self.assertTrue(recover(image, rows, atlas, layout, tag, e))
                self.assertEqual(g._words(' '.join(r['text'] for r in rows)),
                                 g._words(' '.join(r['text'] for r in before)))
                for old, new in zip(before[1:-1], rows[1:-1]):
                    self.assertEqual(old['provenance'][0], new['provenance'][0])
                count = layout[4]
                self.assertEqual(rows[-count-1:] if count else rows[-1:], before[-count-1:] if count else before[-1:])
                d = classify_dialog(dict(width=640, height=480, sha256='a'*64, lines=rows), game_text=source(tag))
                self.assertTrue(d['supported'], d)
                self.assertEqual(d['requires_model'], bool(count))
                self.assertEqual(d['mechanical_action'], None if count else 'acknowledge_information')
                self.assertEqual(len(d['options']), count or 1)
                self.assertEqual(e['gdi_paragraph'][0]['missing_pixels'], 0)

    def test_complete_body_pixel_and_frame_tampering_abstains_atomically(self):
        for mode in ('missing', 'extra', 'gap', 'black', 'colored', 'new_gray', 'frame', 'button', 'radio', 'extra_radio', 'origin'):
            with self.subTest(mode=mode):
                image, rows, atlas, layout = fixture()
                if mode == 'missing':
                    point = next((x, y) for y in range(347, 390) for x in range(304, 637)
                                 if image.getpixel((x, y)) == (48, 48, 48))
                    image.putpixel(point, (190, 190, 190))
                elif mode in ('extra', 'gap', 'black', 'colored', 'new_gray'):
                    point = (631, 366 if mode == 'gap' else 355)
                    color = {'black': (0, 0, 0), 'colored': (48, 0, 0), 'new_gray': (65, 65, 65)}.get(mode, (48, 48, 48))
                    image.putpixel(point, color)
                elif mode == 'frame':
                    image.putpixel((225, 355), (190, 190, 190))
                elif mode == 'button':
                    image.putpixel((600, 455), (0, 0, 0))
                elif mode == 'radio':
                    image.putpixel((320, 394), (190, 190, 190))
                elif mode == 'extra_radio':
                    for dx, dy in g.WHITE_RING:
                        image.putpixel((560+dx, 425+dy), (255,255,255))
                    for dx, dy in g.BLACK_RING:
                        image.putpixel((560+dx, 425+dy), (0,0,0))
                else:
                    region = image.crop((304, 347, 637, 390))
                    image.paste((190,190,190), (304,347,637,390))
                    image.paste(region, (305,347))
                before = deepcopy(rows)
                self.assertFalse(recover(image, rows, atlas, layout))
                self.assertEqual(rows, before)

    def test_missing_extra_or_changed_words_and_controls_never_recovered(self):
        for mode in ('word', 'number', 'case', 'unicode', 'missing_row', 'extra_row', 'missing_option', 'changed_option', 'extra_control', 'missing_ok', 'source', 'duplicate_source', 'confidence', 'conflict'):
            with self.subTest(mode=mode):
                image, rows, atlas, layout = fixture()
                text = source('PROPOSECEASE'); evidence = {}
                if mode == 'word': rows[1]['text'] = rows[1]['text'].replace('TEST', 'WRONG')
                elif mode == 'number': rows[1]['text'] += ' 200'
                elif mode == 'case': rows[1]['text'] = rows[1]['text'].replace('The', 'the')
                elif mode == 'unicode': rows[1]['text'] += '\u0412'
                elif mode == 'missing_row': rows.pop(2)
                elif mode == 'extra_row': rows.insert(2, prepared('Extra TEST', 400, 365, 100, 12))
                elif mode == 'missing_option': rows.pop(-2)
                elif mode == 'changed_option': rows[-2]['text'] = 'Withdraw troops instead.'
                elif mode == 'extra_control': rows.append(prepared('Cancel', 550, 454, 50, 16))
                elif mode == 'missing_ok': rows.pop()
                elif mode == 'source': text = text.replace('cease fire', 'peace treaty')
                elif mode == 'duplicate_source': text += text
                elif mode == 'confidence': rows[1]['confidence'] = .5
                else: evidence['conflicts'] = ['TEST conflicting observation']
                before = deepcopy(rows)
                self.assertFalse(recover(image, rows, atlas, layout, evidence=evidence, game_text=text))
                self.assertEqual(rows, before)

    def test_unique_binding_preserves_repeated_variables_and_rejects_ambiguity(self):
        self.assertIsNone(g._binding('"%STRING0 %STRING1."', 'One Two Three'))
        self.assertIsNone(g._binding('"%STRING0 meets %STRING0."', 'TEST meets OTHER'))
        self.assertIsNone(g._binding('"Pay %NUMBER0 gold."', 'Pay ten gold'))
        self.assertEqual(g._binding('"Pay %NUMBER0 gold."', 'Pay 17 gold'), ('"Pay 17 gold."', {'%NUMBER0': '17'}))
        self.assertIsNone(g._wrap_observed('"do-not"', [dict(text='do'), dict(text='not')]))

    def test_crusade_body_and_actual_option_must_name_the_same_target(self):
        image, rows, atlas, layout = fixture('CRUSADE')
        rows[-2]['text'] = 'Yes, declare war on OTHER.'
        before = deepcopy(rows)
        self.assertFalse(recover(image, rows, atlas, layout, 'CRUSADE'))
        self.assertEqual(rows, before)

    def test_missing_atlas_abstains_without_touching_rows(self):
        image, rows, atlas, layout = fixture(); before = deepcopy(rows)
        with patch.dict(g.LAYOUTS, {'PROPOSECEASE': layout}), patch.object(g, 'load_atlas', return_value=None):
            self.assertFalse(g.recover_herald_paragraph(image, rows, game_text=source('PROPOSECEASE')))
        self.assertEqual(rows, before)

    def test_optional_actual_original_paragraphs(self):
        root = Path(__file__).resolve().parents[1]
        if g.load_atlas() is None or not (root/'.runtime/ocr').exists():
            self.skipTest('Private original atlas/OCR absent')
        from civ2.observe import recognize
        for attempt, number, tag in [('010',2955,'PROPOSECEASE'), ('011',2900,'CRUSADE'), ('010',2672,'GREETINGS00'), ('011',2888,'GREETINGS03')]:
            with self.subTest(tag=tag):
                path = root/f'runs/attempt-{attempt}/screens/ui-{number:07d}.png'
                if not path.exists(): self.skipTest('Private original screenshot absent')
                observation = recognize(path); rows = observation['lines']; image = Image.open(path)
                l,t,inset,count,radios,_ = g.LAYOUTS[tag]
                body = [r for r in rows if l+3 <= r['center'][0] < 637 and t+24 <= r['center'][1] < (390 if radios else 447)]
                if tag == 'GREETINGS03':
                    original = deepcopy(rows)
                    body[-1]['text'] = body[-1]['provenance'][0]['text']
                    before = deepcopy(rows)
                    self.assertIn('Isahella', body[-1]['text'])
                    self.assertFalse(g.recover_herald_paragraph(image, rows))
                    self.assertEqual(rows, before)
                    # Independently recovered Isabella is eligible; simulate
                    # punctuation loss only, never derive the leader from state.
                    rows[:] = original
                    body = [r for r in rows if l+3 <= r['center'][0] < 637 and t+24 <= r['center'][1] < 447]
                    body[-1]['text'] = body[-1]['text'].rstrip('"')
                else:
                    for row in body: row['text'] = row['provenance'][0]['text']
                raw = deepcopy(rows); e = {}
                self.assertTrue(g.recover_herald_paragraph(image, rows, evidence=e))
                self.assertEqual(g._words(' '.join(r['text'] for r in raw)), g._words(' '.join(r['text'] for r in rows)))
                self.assertEqual(e['gdi_paragraph'][0]['resource_tag'], tag)
                self.assertEqual(e['gdi_paragraph'][0]['extra_pixels'], 0)
                # Extra ink after the last word still belongs to the full ROI.
                bad = image.convert('RGB'); bad.putpixel((634,t+35), (48,48,48))
                self.assertFalse(g.recover_herald_paragraph(bad, raw))


if __name__ == '__main__':
    unittest.main()
