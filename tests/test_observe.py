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
    def test_map_art_color_evidence_uses_original_patch_and_hash(self):
        image=Image.new('RGB',(640,480),(120,120,120))
        image.paste((50,180,40),(100,200,110,210))
        rows=[{'text':"T'R",'bounds':[100,200,10,10],'confidence':.3},
              {'text':'Help!','bounds':[120,200,10,10],'confidence':.3},
              {'text':'TEST','bounds':[100,200,10,10],'confidence':1}]
        observe._map_patch_colors(image,rows,'a'*64)
        self.assertEqual(rows[0]['map_patch_colors']['chromatic_pixels'],100)
        self.assertEqual(rows[1]['map_patch_colors']['chromatic_pixels'],0)
        self.assertEqual(rows[0]['map_patch_colors']['source_sha256'],'a'*64)
        self.assertEqual(rows[0]['map_patch_colors']['bounds'],rows[0]['bounds'])
        self.assertEqual(rows[2]['map_patch_colors']['chromatic_pixels'],100)

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

    def test_exact_pixel_pair_can_replace_damaged_first_glyph_without_prefix_alias(self):
        native=broken_status();native[0]['text']='Bnd of Tum';native[1]['text']='(Press ECTER)'
        result,_=self.recognize(native,[],status_pair())
        self.assertEqual([r['text'] for r in result['lines']],list(observe.STATUS_PHRASES))
        self.assertEqual(result['lines'][0]['provenance'][0]['text'],'Bnd of Tum')

    def test_status_pair_native_boxes_may_share_only_a_thin_adjacent_edge(self):
        native=[row('Bnd of Tum',x=476,y=446,width=64,height=12),
                row('(Press ECTER)',x=478,y=456,width=78,height=12)]
        pair=[dict(text='End of Turn',confidence=1,x=10/174,y=5/40,width=62/174,height=11/40),
              dict(text='(Press ENTER)',confidence=1,x=13/174,y=17/40,width=76/174,height=12/40)]
        result,_=self.recognize(native,[],pair)
        self.assertEqual([r['text'] for r in result['lines']],list(observe.STATUS_PHRASES))
        native[0]['height']=17/480
        result,_=self.recognize(native,[],pair)
        self.assertEqual(result['lines'][0]['text'],'Bnd of Tum')

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


class NativeRowCropTests(unittest.TestCase):
    def test_save_caption_requires_two_actual_reads_and_original_notice_body(self):
        old=self.prepared('Gaue saved!!',x=278,y=196,width=84,height=12)
        good=self.prepared('Game samed!',x=279,y=196,width=84,height=12,source='TEST crop')
        anchors=[self.prepared('Dictator TEST Caesar of the Romans'),self.prepared('OK')]
        for second,accepted in [(good,True),(self.prepared('Game loaded!'),False)]:
            rows=anchors+[dict(old)]
            with patch.object(observe,'_crop_text',side_effect=[[good],[second]]):
                observe._recover_saved_caption(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[-1]['text'],'Game samed!' if accepted else 'Gaue saved!!')
        with patch.object(observe,'_crop_text') as crop:
            observe._recover_saved_caption(Image.new('RGB',(640,480)),[old],None,None,{})
        crop.assert_not_called()

    def test_city_sections_need_complete_layout_and_two_exact_pixel_reads(self):
        original=self.prepared('Units Preseni',x=276,y=278,width=80,height=12)
        good=self.prepared('Units Present',x=275,y=277,width=80,height=12,source='TEST crop')
        anchors=[self.prepared(t) for t in ('Food Storage','City Resources','Resource Map','Buy','Change','Exit')]
        image=Image.new('RGB',(640,480))
        for second,accepted in [(good,True),(self.prepared('Units Precent'),False)]:
            rows=anchors+[dict(original)]
            with patch.object(observe,'_crop_text',side_effect=[[good],[second]]):
                observe._recover_city_section_labels(image,rows,None,None,{})
            self.assertEqual(rows[-1]['text'],'Units Present' if accepted else 'Units Preseni')
        with patch.object(observe,'_crop_text') as crop:
            observe._recover_city_section_labels(image,[original],None,None,{})
        crop.assert_not_called()

    """Synthetic TEST readings; crop geometry never becomes a guessed target."""
    def prepared(self,text,x=218,y=222,width=30,height=14,source='native'):
        return observe._prepare_rows([row(text,x,y,width,height)],640,480,source)[0]

    def test_same_row_recovery_retains_raw_reading_and_rejects_ambiguity(self):
        original=self.prepared('Veu');fresh=self.prepared('Veii',source='test_crop')
        rows=[original]
        self.assertFalse(observe._replace_crop_row(rows,0,[fresh,fresh],lambda a,b:True))
        self.assertFalse(observe._replace_crop_row(rows,0,[self.prepared('Veii',y=180)],lambda a,b:True))
        self.assertTrue(observe._replace_crop_row(rows,0,[fresh],lambda a,b:True))
        self.assertEqual([p['text'] for p in rows[0]['provenance']],['Veu','Veii'])

    def test_production_title_requires_two_agreeing_reads_same_city_and_complete_controls(self):
        image=Image.new('RGB',(640,480),'gray')
        original=self.prepared('What shall we bodkd in TEST?',x=200,y=130,width=280)
        buttons=[self.prepared(t,x=x,y=310,width=30) for t,x in [('Auto',210),('Help',310),('OK',410)]]
        good=self.prepared('What shall me bukd in TEST?',x=200,y=130,width=280,source='TEST independent crop')
        for peer,accept in ((good,True),(self.prepared('What shall me bukd in OTHER?',x=200,y=130,width=280),False),
                            (self.prepared('What shall me bukd in TEST?',x=200,y=200,width=280),False)):
            rows=[dict(original),*buttons]
            with patch.object(observe,'_crop_text',side_effect=[[good],[peer],[good],[peer]]),patch.object(observe,'_production_names',return_value=set()):
                observe._recover_city_and_production_rows(image,rows,None,None,{})
            self.assertEqual(rows[0]['text'],good['text'] if accept else original['text'])
            if accept:self.assertEqual(rows[0]['provenance'][0]['text'],original['text'])
        for text in ('What shall me bukd in OTHER?','What shall we purchase in TEST?'):
            rows=[dict(original),*buttons];bad=self.prepared(text,x=200,y=130,width=280)
            with patch.object(observe,'_crop_text',side_effect=[[bad],[bad],[bad],[bad]]),patch.object(observe,'_production_names',return_value=set()):
                observe._recover_city_and_production_rows(image,rows,None,None,{})
            self.assertEqual(rows[0]['text'],original['text'])
        with patch.object(observe,'_crop_text') as crop:
            observe._recover_city_and_production_rows(image,[original,*buttons[:-1]],None,None,{})
        crop.assert_not_called()

    def test_map_label_requires_two_agreeing_pixel_reads_and_complete_menu(self):
        menu=[self.prepared(s,x=10+i*60,y=22,width=40) for i,s in enumerate(('Game','Kingdom','View','Orders'))]
        original=self.prepared('Veu');fresh=self.prepared('Veii',source='test_crop')
        image=Image.new('RGB',(640,480),'gray')
        for readings,expected in (([[fresh],[fresh]],'Veii'),([[fresh],[self.prepared('Vei')],[],[],[]],'Veu'),([[],[fresh],[],[],[]],'Veu')):
            rows=menu+[dict(original)]
            with patch.object(observe,'_crop_text',side_effect=readings):
                observe._recover_map_labels(image,rows,None,None,{})
            self.assertEqual(rows[-1]['text'],expected)
        for rows in (menu[1:]+[original],menu+[original,self.prepared('OK',y=300)]):
            with patch.object(observe,'_crop_text') as crop:
                observe._recover_map_labels(image,rows,None,None,{})
            crop.assert_not_called()

    def test_production_crops_require_complete_buttons_and_preserve_numeric_values(self):
        rows=[self.prepared('What shall me boild in TEST?',x=190,y=130,width=280),
              self.prepared('Seilers',x=180,y=172,width=50),
              self.prepared('65 lurnsi',x=470,y=258,width=66),
              *[self.prepared(t,x=x,y=310,width=30) for t,x in [('Auto',210),('Help',310),('OK',410)]]]
        image=Image.new('RGB',(640,480),'gray')
        for x in range(180,230):
            for y in range(172,176):image.putpixel((x,y),(255,255,255))
        def read(im,r,*args,**kwargs):
            text='Settlers' if r['text']=='Seilers' else '(65 Turns)'
            return [self.prepared(text,*r['bounds'],source='TEST independent crop')]
        with patch.object(observe,'_crop_text',side_effect=read),patch.object(observe,'_production_names',return_value={'settlers','phalanx'}):
            observe._recover_city_and_production_rows(image,rows,None,None,{})
        self.assertEqual([r['text'] for r in rows[1:3]],['Settlers','(65 Turns)'])
        rows[2]=self.prepared('65 lurnsi',x=470,y=258,width=66)
        with patch.object(observe,'_crop_text',return_value=[self.prepared('(85 Turns)',x=470,y=258,width=66)]):
            observe._recover_city_and_production_rows(image,rows,None,None,{})
        self.assertEqual(rows[2]['text'],'65 lurnsi')
        with patch.object(observe,'_crop_text') as crop:
            observe._recover_city_and_production_rows(image,rows[:-1],None,None,{})
        crop.assert_not_called()

    def test_stat_number_recovery_is_narrowly_bound_to_observed_glyph_shapes(self):
        self.assertTrue(observe._stat_numbers_compatible('2/ lurnsi','(27 Turns)'))
        self.assertTrue(observe._stat_numbers_compatible('167 Turnsi','(67 Turns)'))
        self.assertFalse(observe._stat_numbers_compatible('65 lurnsi','(85 Turns)'))
        self.assertEqual(observe._stat_reading('(67 Turns)|'),'(67 Turns)')
        self.assertEqual(observe._stat_reading('(7 Tums, ADM: 1/2/1 HP: 1/1))'),'(7 Tums, ADM: 1/2/1 HP: 1/1)')
        self.assertIsNone(observe._stat_reading('67 Turns'))

    def test_moving_heading_requires_two_exact_pixel_reads_inside_unit_pane(self):
        image=Image.new('RGB',(640,480));old=self.prepared('Morng Thits',x=514,y=251,width=72,height=15)
        good=self.prepared('Moving Units',x=514,y=254,width=73,height=11,source='TEST crop')
        for fresh,expected in (([good],'Moving Units'),([],'Morng Thits')):
            rows=[dict(old)]
            with patch.object(observe,'_crop_text',side_effect=[[good],fresh,[good],fresh]):
                observe._recover_moving_status(image,rows,None,None,{})
            self.assertEqual(rows[0]['text'],expected)
        rows=[self.prepared('Morng Thits',x=200,y=251,width=72,height=15)]
        with patch.object(observe,'_crop_text') as crop:observe._recover_moving_status(image,rows,None,None,{})
        crop.assert_not_called()

    def test_completion_zoom_requires_source_heading_and_two_exact_pixel_readings(self):
        image=Image.new('RGB',(640,480));old=self.prepared('Loom to City',x=206,y=216,width=87,height=19)
        good=self.prepared('Zoom to City',x=205,y=218,width=88,height=15,source='TEST crop')
        rows=[self.prepared('Domestic Advisor',x=255,y=166,width=135),old,self.prepared('OK',x=310,y=298,width=24)]
        with patch.object(observe,'_crop_text',side_effect=[[good],[good]]):
            observe._recover_completion_zoom(image,rows,None,None,{})
        self.assertEqual(rows[1]['text'],'Zoom to City')
        self.assertEqual(rows[1]['provenance'][0]['text'],'Loom to City')
        with patch.object(observe,'_crop_text') as crop:observe._recover_completion_zoom(image,[old],None,None,{})
        crop.assert_not_called()

    def test_production_never_replaces_an_exact_original_rule_name(self):
        rows=[self.prepared('What shall me boild in TEST?',x=190,y=130,width=280),
              self.prepared('Phalanx',x=180,y=172,width=50),
              *[self.prepared(t,x=x,y=310,width=30) for t,x in [('Auto',210),('Help',310),('OK',410)]]]
        with patch.object(observe,'_production_names',return_value={'phalanx'}),patch.object(observe,'_crop_text') as crop:
            observe._recover_city_and_production_rows(Image.new('RGB',(640,480),'white'),rows,None,None,{})
        crop.assert_not_called();self.assertEqual(rows[1]['text'],'Phalanx')

    def test_city_caption_requires_pixel_read_same_city_era_and_near_date(self):
        original='Cicy of TEST Rome, 3000 B.C., Population 10,000'
        good='City of TEST Rome, 3800 B.C., Population 10,000'
        for fresh,accepted in [(good,True),(good.replace('Rome','Veii'),False),
                               (good.replace('B.C.','A.D.'),False),(good.replace('3800','3950'),False)]:
            rows=[self.prepared(original,x=120,y=40,width=400,height=16)]
            candidate=self.prepared(fresh,x=120,y=40,width=400,height=16,source='TEST actual crop')
            with patch.object(observe,'_crop_text',return_value=[candidate]):
                observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[0]['text'],fresh if accepted else original)


class PrivateCalibrationTests(unittest.TestCase):
    def test_optional_original_saved_heading_and_damaged_footer_prefix(self):
        root=Path(__file__).resolve().parents[1]
        saved=root/'runs/attempt-005/screens/ui-0000819.png';footer=root/'runs/attempt-004/screens/ui-0000573.png'
        if not all(p.exists() for p in (saved,footer,root/'.runtime/ocr')):self.skipTest('Private original saved/footer frames unavailable')
        from civ2.ui import saved_notice
        self.assertTrue(saved_notice(observe.recognize(saved)))
        o=observe.recognize(footer)
        for phrase in observe.STATUS_PHRASES:self.assertIn(phrase,[r['text'] for r in o['lines']])

    def test_optional_original005_city_section_crop_reads_exact_headings(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-005/screens/ui-0000741.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original city frame unavailable')
        from civ2.dialogs import classify_dialog
        before=p.read_bytes();o=observe.recognize(p)
        for heading in ('Units Supported','Units Present'):
            match=next(r for r in o['lines'] if r['text']==heading)
            self.assertGreaterEqual(len(match['provenance']),3)
        self.assertEqual(classify_dialog(o)['kind'],'city_screen')
        self.assertEqual(p.read_bytes(),before)

    def test_optional_original006_production_heading_keeps_independent_reading(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-006/screens/ui-0000653.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original production frame unavailable')
        before=p.read_bytes();o=observe.recognize(p)
        title=next(r for r in o['lines'] if r['text'].startswith('What shall'))
        self.assertEqual(title['text'],'What shall me bukd in Antiom?')
        self.assertEqual(title['provenance'][0]['text'],'What shall we bodkd in Antiom?')
        self.assertEqual(title['center'],[320,145]);self.assertEqual(p.read_bytes(),before)

    def test_optional_actual_city_production_and_map_label_crops(self):
        root=Path(__file__).resolve().parents[1]
        production=root/'runs/attempt-005/screens/ui-0000112.png'
        native_map=root/'runs/attempt-004/screens/ui-0000152.png'
        if not all(p.exists() for p in (production,native_map,root/'.runtime/ocr')):
            self.skipTest('Private original crop calibration images unavailable')
        for path,words in [(production,['Settlers','(65 Turns)']), (native_map,['Veii'])]:
            before=path.read_bytes();result=observe.recognize(path)
            for word in words:
                matches=[r for r in result['lines'] if r['text']==word]
                self.assertEqual(len(matches),1)
                self.assertGreaterEqual(len(matches[0]['provenance']),2)
            self.assertFalse(result['ocr']['fallback_errors'])
            self.assertEqual(path.read_bytes(),before)
        self.assertIn('3800 B.C.',observe.recognize(production)['text'])

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
