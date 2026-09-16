"""OCR fallback uses image evidence without inventing labels or coordinates."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from civ2 import observe


def row(text, x=300, y=330, width=40, height=14):
    return dict(text=text, confidence=1., x=x/640, y=y/480,
                width=width/640, height=height/480)


def status_pair():
    """Synthetic TEST crop-relative boxes, approximately native font spacing."""
    return [dict(text='End of Turn', confidence=1., x=10/174, y=7/40, width=64/174, height=10/40),
            dict(text='(Press ENTER)', confidence=1., x=12/174, y=20/40, width=78/174, height=10/40)]


def broken_status():
    return [row('Endofhum', x=476, y=447, width=64, height=10),
            row('(Press KHEERO', x=478, y=460, width=78, height=10)]


class ObserveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root/'.runtime').mkdir()
        (self.root/'.runtime/ocr').touch()
        self.path = self.root/'original.png'
        image = Image.new('RGB', (640, 480), 'gray')
        image.putpixel((17, 23), (255, 0, 0))
        image.save(self.path)
        self.original = self.path.read_bytes()
        self.root_patch = patch.object(observe, 'ROOT', self.root)
        self.root_patch.start(); self.addCleanup(self.root_patch.stop)

    def recognize(self, *passes):
        with patch.object(observe, '_run_ocr', side_effect=list(passes)) as recognize:
            result = observe.recognize(self.path)
            return result, recognize.call_count

    def test_top_edge_floating_point_error_is_clamped_but_real_out_of_bounds_fails(self):
        r=row('DOS startup line'); r['y']=-1.6666668e-10
        result,_=self.recognize([r],[])
        self.assertEqual(result['lines'][0]['bounds'][1],0)
        r['y']=-.01
        with self.assertRaises(ValueError):self.recognize([r],[])

    def test_missing_control_uses_native_coordinates_hash_and_temporary_nearest_copy(self):
        native = [row('Native heading', y=100, width=100)]
        def ocr(executable, path):
            self.assertEqual(executable, self.root/'.runtime/ocr')
            with Image.open(path) as image:
                if path == self.path:
                    self.assertEqual(image.size, (640, 480)); return native
                self.assertEqual(image.size, (1280, 960))
                self.assertEqual(image.getpixel((34, 46)), (255, 0, 0))
                self.assertEqual(image.getpixel((35, 47)), (255, 0, 0))
                return [row('OK')]
        with patch.object(observe, '_run_ocr', side_effect=ocr):
            result = observe.recognize(self.path)
        self.assertEqual((result['width'], result['height']), (640, 480))
        self.assertEqual(result['sha256'], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list((self.root/'.runtime').iterdir()), [self.root/'.runtime/ocr'])
        control = result['lines'][1]
        self.assertEqual(control['center'], [320, 337])
        self.assertEqual(control['bounds'], [300, 330, 40, 14])
        self.assertEqual(control['provenance'][0]['preprocessing'], 'nearest_2x')
        self.assertEqual(result['lines'][0]['text'], 'Native heading')

    def test_spatial_duplicate_is_one_line_with_both_readings(self):
        result, calls = self.recognize([row('OK')], [row('OK', x=301)])
        self.assertEqual(calls, 2); self.assertEqual(len(result['lines']), 1)
        self.assertEqual(result['lines'][0]['center'], [320, 337])
        self.assertEqual([x['preprocessing'] for x in result['lines'][0]['provenance']], ['native', 'nearest_2x'])
        self.assertEqual(observe.find_text(result, 'OK', exact=True), [320, 337])

    def test_cyrillic_ok_needs_overlapping_ascii_corroboration(self):
        result, _ = self.recognize([row('OК')], [row('OK', x=301)])
        self.assertEqual(result['lines'][0]['text'], 'OK')
        self.assertEqual(result['lines'][0]['provenance'][0]['text'], 'OК')
        for fallback in ([], [row('OК')], [row('OK', y=200)]):
            with self.subTest(fallback=fallback):
                result, _ = self.recognize([row('OК')], fallback)
                self.assertEqual(result['lines'][0]['text'], 'OК')

    def test_contradictory_or_broad_overlaps_are_not_new_click_targets(self):
        for native in ([row('OR')], [row('Long native sentence', x=150, width=250)]):
            with self.subTest(native=native):
                result, _ = self.recognize(native, [row('OK')])
                self.assertEqual(len(result['lines']), 1)
                self.assertEqual(result['lines'][0]['text'], native[0]['text'])
                self.assertEqual(len(result['ocr']['conflicts']), 1)
                with self.assertRaises(ValueError): observe.find_text(result, 'OK', exact=True)

    def test_distinct_controls_remain_ambiguous_and_other_fallback_text_is_ignored(self):
        result, _ = self.recognize([row('OK')], [row('OK', y=200), row('Invented replacement title', y=50)])
        self.assertEqual(len(result['lines']), 2)
        with self.assertRaises(ValueError): observe.find_text(result, 'OK', exact=True)
        self.assertNotIn('replacement', result['text'])

    def test_failed_fallback_keeps_native_without_raw_exception_details(self):
        result, calls = self.recognize([row('Cancel')], subprocess.TimeoutExpired('private details', 20))
        self.assertEqual(calls, 2); self.assertEqual(result['text'], 'Cancel')
        self.assertEqual(result['ocr']['fallback_errors'], [dict(pass_name='nearest_2x', error='TimeoutExpired')])

    def test_heading_requires_founded_body_exact_scaled_text_and_same_location(self):
        native = [row('Foond New City', y=120, width=110), row('Rome Founded: 4000 B.C.', y=155, width=180)]
        result, calls = self.recognize(native, [row('OK')], [row('Found New City', y=121, width=110)])
        self.assertEqual(calls, 3)
        self.assertEqual(result['lines'][0]['text'], 'Found New City')
        self.assertEqual(result['lines'][0]['provenance'][0]['text'], 'Foond New City')
        self.assertEqual(result['lines'][0]['provenance'][1]['preprocessing'], 'bicubic_3x')
        for scaled in ([row('Found New City', y=50, width=110)], [row('Foond New City', y=121, width=110)]):
            result, _ = self.recognize(native, [row('OK')], scaled)
            self.assertEqual(result['lines'][0]['text'], 'Foond New City')
        result, calls = self.recognize(native[:1], [row('OK')])
        self.assertEqual(calls, 2); self.assertEqual(result['lines'][0]['text'], 'Foond New City')

    def test_invalid_fallback_geometry_cannot_create_a_control(self):
        for value in (float('nan'), -1, True, 1.5):
            candidate = row('OK'); candidate['x'] = value
            result, _ = self.recognize([row('Native')], [candidate])
            self.assertEqual(result['text'], 'Native')
            self.assertEqual(result['ocr']['fallback_errors'][0]['error'], 'ValueError')

    def test_status_pair_maps_crop_boxes_and_replaces_only_corroborated_native_rows(self):
        result, calls = self.recognize(broken_status(), [], status_pair())
        self.assertEqual(calls, 3)
        self.assertEqual([line['text'] for line in result['lines']], ['End of Turn', '(Press ENTER)'])
        self.assertEqual(result['lines'][0]['bounds'], [476, 447, 64, 10])
        self.assertEqual(result['lines'][1]['center'], [517, 465])
        self.assertAlmostEqual(result['lines'][0]['x'], 476/640)
        proof = result['lines'][0]['provenance']
        self.assertEqual(proof[0]['text'], 'Endofhum')
        self.assertEqual(proof[1]['crop'], [466, 440, 640, 480])
        self.assertEqual(proof[1]['normalized_crop_bounds'], [10/174, 7/40, 64/174, 10/40])
        self.assertEqual(result['sha256'], hashlib.sha256(self.original).hexdigest())

    def test_status_recovery_requires_both_exact_phrases_and_normal_order(self):
        good = status_pair()
        variants = [good[:1], [dict(good[0]), dict(good[1], text='(Press SPACE)')],
                    [dict(good[0], y=.7), dict(good[1], y=.1)],
                    [dict(good[0]), dict(good[1], confidence=.4)],
                    [*good, dict(good[0], text='Unrelated text')]]
        for masked in variants:
            with self.subTest(masked=masked):
                result, _ = self.recognize(broken_status(), [], masked)
                self.assertEqual([line['text'] for line in result['lines']], ['Endofhum', '(Press KHEERO'])

    def test_status_merge_is_atomic_when_second_line_conflicts(self):
        native = broken_status(); native[1]['text'] = 'No orders'
        result, _ = self.recognize(native, [], status_pair())
        self.assertEqual([line['text'] for line in result['lines']], ['Endofhum', 'No orders'])
        self.assertEqual(len(result['ocr']['conflicts']), 1)

    def test_status_avoids_duplicate_displaced_near_rows(self):
        native = broken_status(); native[0]['y'] = 435/480
        # This near row crosses outside the status crop but still overlaps its
        # recovered phrase's text bounds: uncertainty must reject the pair.
        native[0]['height'] = 20/480
        result, _ = self.recognize(native, [], status_pair())
        self.assertEqual(len(result['lines']), 2)
        self.assertNotIn('End of Turn', result['text'])

    def test_missing_status_can_be_added_only_with_verified_roman_title_and_no_moving_marker(self):
        roman = row('Roman Map', x=190, y=45, width=80)
        result, calls = self.recognize([roman], [], status_pair())
        self.assertEqual(calls, 3)
        self.assertEqual(result['lines'][-1]['center'], [517, 465])
        for native in ([row('Other Map', x=190, y=45, width=80)],
                       [roman, row('Moving Units', x=510, y=252, width=100)],
                       [row('Roman Map', x=190, y=145, width=80)]):
            result, calls = self.recognize(native, [])
            self.assertEqual(calls, 2)
            self.assertNotIn('End of Turn', result['text'])

    def test_correct_native_pair_skips_extra_pass_and_wrong_dimensions_never_crop(self):
        native = broken_status(); native[0]['text'] = 'End of Turn'; native[1]['text'] = '(Press ENTER)'
        result, calls = self.recognize(native, [])
        self.assertEqual(calls, 2)
        Image.new('RGB', (800, 600), 'gray').save(self.path)
        result, calls = self.recognize(broken_status(), [])
        self.assertEqual(calls, 2)

    def test_status_analysis_uses_only_white_glyph_roi_and_leaves_source_intact(self):
        with Image.open(self.path) as original:
            im = original.copy()
        for x in range(476, 480):
            for y in range(447, 451): im.putpixel((x, y), (255, 255, 255))
        im.save(self.path); before = self.path.read_bytes()
        def ocr(executable, path):
            if path == self.path: return broken_status()
            if path.name == 'nearest_2x.png': return []
            with Image.open(path) as transformed:
                self.assertEqual(transformed.size, (696, 160))
                self.assertEqual(transformed.mode, 'L')
                self.assertEqual(transformed.getpixel((48, 36)), 0)
                self.assertEqual(transformed.getpixel((400, 36)), 255)
            return status_pair()
        with patch.object(observe, '_run_ocr', side_effect=ocr):
            result = observe.recognize(self.path)
        self.assertIn('End of Turn', result['text'])
        self.assertEqual(self.path.read_bytes(), before)


class PrivateCalibrationTests(unittest.TestCase):
    def test_optional_actual_end_turn_status_recovery(self):
        root = Path(__file__).resolve().parents[1]
        path = root/'runs/attempt-002/screens/ui-0000037.png'
        if not path.exists() or not (root/'.runtime/ocr').exists():
            self.skipTest('Private original end-turn screenshot/OCR unavailable')
        before = path.read_bytes(); result = observe.recognize(path)
        self.assertEqual(len([row for row in result['lines'] if row['text'] == 'End of Turn']), 1)
        self.assertEqual(len([row for row in result['lines'] if row['text'] == '(Press ENTER)']), 1)
        self.assertLessEqual(abs(observe.find_text(result, 'End of Turn', exact=True)[1] - 452), 1)
        self.assertEqual(observe.find_text(result, '(Press ENTER)', exact=True), [517, 465])
        self.assertEqual(result['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(path.read_bytes(), before)

    def test_optional_four_original_dialog_controls(self):
        root = Path(__file__).resolve().parents[1]
        cases = [
            ('runs/attempt-001/screens/ui-0000013.png', (321, 344)),
            ('runs/attempt-001/screens/ui-0000008.png', (207, 273)),
            ('.runtime/campaign-03-check/ui-0000002.png', (470, 99)),
            ('.runtime/campaign-03-check/ui-0000004.png', (320, 276)),
        ]
        if not (root/'.runtime/ocr').exists() or not all((root/name).exists() for name, _ in cases):
            self.skipTest('Private original screenshots/OCR executable unavailable')
        for name, expected in cases:
            with self.subTest(name=name):
                path = root/name; before = path.read_bytes()
                result = observe.recognize(path)
                actual = observe.find_text(result, 'OK', exact=True)
                self.assertLessEqual(max(abs(a-b) for a, b in zip(actual, expected)), 2)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(result['sha256'], hashlib.sha256(before).hexdigest())
                if '0000013' in name:
                    self.assertIn('Found New City', result['text'])
                if 'check/ui-0000004' in name:
                    self.assertIn('Game saved!!', result['text'])


if __name__ == '__main__':
    unittest.main()
