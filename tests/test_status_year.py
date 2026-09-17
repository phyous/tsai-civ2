"""Pixel-only status date recovery never substitutes native-state values."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest import mock
from PIL import Image
from civ2.observe import _recover_status_year


def row(text='1250 В.C.',x=475,y=216):
    return dict(text=text,bounds=[x,y,60,14],center=[x+30,y+7],confidence=1,
                provenance=[{'preprocessing':'native','text':text}])


class StatusYearTests(unittest.TestCase):
    def test_two_pixel_reads_recover_only_era_and_preserve_raw_provenance(self):
        rows=[row()];a=row('1250 B.C.');b=deepcopy(a)
        a['provenance']=[{'preprocessing':'rgb3','text':a['text']}]
        b['provenance']=[{'preprocessing':'gray3','text':b['text']}]
        with mock.patch('civ2.observe._crop_text',side_effect=[[a],[b]]):
            _recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{})
        self.assertEqual(rows[0]['text'],'1250 B.C.')
        self.assertEqual([r['text'] for r in rows[0]['provenance']],['1250 В.C.','1250 B.C.','1250 B.C.'])

    def test_disagreement_changed_number_and_unrelated_geometry_reject(self):
        for case in ('different_era','different_year','low_confidence','moved','incomplete'):
            rows=[row()];a=row('1250 B.C.');b=deepcopy(a)
            if case=='different_era':b['text']='1250 A.D.'
            elif case=='different_year':a['text']=b['text']='1200 B.C.'
            elif case=='low_confidence':b['confidence']=.5
            elif case=='moved':b=row('1250 B.C.',x=200)
            elif case=='incomplete':a['text']=b['text']='1250 B'
            with mock.patch('civ2.observe._crop_text',side_effect=[[a],[b]]):
                _recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{})
            with self.subTest(case=case):self.assertEqual(rows[0]['text'],'1250 В.C.')

    def test_valid_date_or_other_pane_needs_no_extra_ocr(self):
        for r in (row('1250 B.C.'),row(x=200),row(y=100),row('80 Gold 4.0.6')):
            with mock.patch('civ2.observe._crop_text') as crop:
                _recover_status_year(Image.new('RGB',(640,480)),[r],None,None,{})
            crop.assert_not_called()

    def test_second_scale_requires_two_fresh_agreeing_reads(self):
        for final in ('1200 B.C.','1250 B.C.'):
            rows=[row('1200 В.C.')]
            readings=[[deepcopy(rows[0])],[deepcopy(rows[0])],[row('1200 B.C.')],[row(final)]]
            with mock.patch('civ2.observe._crop_text',side_effect=readings) as crop:
                _recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(crop.call_count,4)
            self.assertEqual(crop.call_args_list[-1].kwargs['scale'],2)
            self.assertEqual(rows[0]['text'],'1200 B.C.' if final=='1200 B.C.' else '1200 В.C.')

    def test_one_unreadable_digit_requires_two_reads_and_keeps_other_digits_and_era(self):
        for text,second in (('875 B.C.','875 B.C.'),('875 B.C.','865 B.C.'),
                            ('975 B.C.','975 B.C.'),('875 A.D.','875 A.D.'),
                            ('1875 B.C.','1875 B.C.')):
            rows=[row('8T5 B.C.')]
            with mock.patch('civ2.observe._crop_text',side_effect=[[row(text)],[row(second)]]):
                _recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{})
            expected='875 B.C.' if text==second=='875 B.C.' else '8T5 B.C.'
            self.assertEqual(rows[0]['text'],expected)
            self.assertEqual(rows[0]['provenance'][0]['text'],'8T5 B.C.')

    def test_unreadable_year_requires_intact_era_and_only_one_damaged_glyph(self):
        for text in ('8TT B.C.','T B.C.','8T5 В.C.','8T5 A','8T5 Gold'):
            with mock.patch('civ2.observe._crop_text') as crop:
                _recover_status_year(Image.new('RGB',(640,480)),[row(text)],None,None,{})
            crop.assert_not_called()

    def test_actual_status_digit_is_recovered_from_pixels_without_game_state(self):
        from civ2.observe import recognize
        path=Path(__file__).resolve().parents[1]/'runs/attempt-010/screens/ui-0001419.png'
        if not path.exists():self.skipTest('Private original calibration image unavailable')
        result=recognize(path)
        dates=[r for r in result['lines'] if r['text']=='875 B.C' and r['bounds'][0]>=470]
        self.assertEqual(len(dates),1)
        self.assertEqual([p['text'] for p in dates[0]['provenance']],['8T5 B.C.','875 B.C','875 B.C'])

    def test_actual_second_scale_preserves_native_year(self):
        from civ2.observe import recognize
        path=Path(__file__).resolve().parents[1]/'runs/attempt-010/screens/ui-0001194.png'
        if not path.exists():self.skipTest('Private original calibration image unavailable')
        result=recognize(path)
        dates=[r for r in result['lines'] if r['text']=='1200 B.C.' and r['bounds'][0]>=470]
        self.assertEqual(len(dates),1)
        self.assertEqual(dates[0]['provenance'][0]['text'],'1200 В.C.')
        self.assertEqual({p['preprocessing'] for p in dates[0]['provenance'][1:]},
                         {'status_year_rgb2','status_year_gray2'})

    def test_actual_original_cyrillic_era_read_recovers_ascii_without_changing_hash(self):
        from civ2.observe import recognize
        import hashlib
        path=Path(__file__).resolve().parents[1]/'runs/attempt-006/screens/ui-0001238.png'
        if not path.exists():self.skipTest('Private original calibration image unavailable')
        result=recognize(path)
        self.assertEqual(result['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
        dates=[r for r in result['lines'] if r['text']=='1250 B.C.' and r['bounds'][0]>=470]
        self.assertEqual(len(dates),1)
        self.assertTrue(any(p['text']=='1250 В.C.' for p in dates[0]['provenance']))

if __name__=='__main__':unittest.main()
