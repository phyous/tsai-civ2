"""Golden Age names and punctuation come from paired original pixels."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,mock
from PIL import Image
from civ2.observe import _recover_golden_age_city_line,recognize
from tests.test_herald import prepared


def rows():
    return [prepared('Golden Age of Philosophy',240,176,162,18),
        prepared('The Golden Age of Philosophy begins in the',200,200,292,16),
        prepared('TEST city of Veill Great TEST thinkers',202,220,284,16),
        prepared('articulate scientific, moral, and metaphysical',200,238,298,18),
        prepared('systems which endure for centuries to come.',200,260,296,16),
        prepared('OK',309,290,24,13)]


class GoldenAgePixels(TestCase):
    def test_paired_actual_city_and_punctuation_with_complete_literal_prose(self):
        for case in ('valid','disagreement','nation','city','punctuation','terms','extra_choice','repeated_identity','geometry'):
            with self.subTest(case=case):
                original=rows();a=prepared('TEST city of Veii! Great TEST thinkers',202,220,284,16);b=deepcopy(a)
                if case=='disagreement':b['text']='TEST city of Veil! Great TEST thinkers'
                if case=='nation':a['text']=b['text']='OTHER city of Veii! Great OTHER thinkers'
                if case=='city':a['text']=b['text']='TEST city of Ravenna! Great TEST thinkers'
                if case=='punctuation':a['text']=b['text']='TEST city of Veii? Great TEST thinkers'
                if case=='terms':original[3]['text']='articulate scientific and military systems'
                if case=='extra_choice':original.insert(-1,prepared('Cancel',280,280,40,10))
                if case=='repeated_identity':original[2]['text']='TEST city of Veill Great OTHER thinkers'
                if case=='geometry':a['center'][1]+=15
                before=deepcopy(original)
                with TemporaryDirectory() as d,mock.patch('civ2.observe._crop_text',side_effect=[[a],[b]]) as crop:
                    _recover_golden_age_city_line(Image.new('RGB',(640,480)),original,None,d,{'passes':[]})
                if case=='valid':
                    self.assertEqual(original[2]['text'],a['text'])
                    self.assertEqual(original[:2]+original[3:],before[:2]+before[3:])
                    self.assertEqual(len(original[2]['provenance']),3)
                else:self.assertEqual(original,before)
                if case in ('terms','extra_choice','repeated_identity'):crop.assert_not_called()

    def test_actual_011_notice_retains_complete_source_and_sole_ok(self):
        p=Path('runs/attempt-011/screens/ui-0002959.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'GOLDENAGE')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertEqual([r['text'] for r in d['options']],['OK'])
        city=next(r for r in o['lines'] if r['text'].startswith('Roman city of'))
        self.assertEqual(city['text'],'Roman city of Veii! Great Roman thinkers')
        self.assertEqual([r['preprocessing'] for r in city['provenance'][-2:]],['golden_age_city_rgb3','golden_age_city_gray3'])

    def test_actual_012_rome_uses_complete_second_scale_readings(self):
        p=Path('runs/attempt-012/screens/ui-0002628.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'GOLDENAGE')
        city=next(r for r in o['lines'] if r['text'].startswith('Roman city of'))
        self.assertEqual(city['text'],'Roman city of Rome! Great Roman thinkers')
        self.assertEqual(city['provenance'][0]['text'],'Roman city of Romel Great Roman thinkers')
        self.assertEqual([r['preprocessing'] for r in city['provenance'][-2:]],['golden_age_city_rgb2','golden_age_city_gray2'])
