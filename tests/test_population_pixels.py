"""Synthetic TEST population punctuation and optional original notice."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class PopulationPixelsTests(unittest.TestCase):
    def test_only_digits_preserving_two_actual_readings_replace_punctuation(self):
        base=[prepared('Domestic Advisor',263,182,116,16),
              prepared('The population of the fertile TEST empire now exceeds',146,208,390,16),
              prepared('100.000 citizens.',146,228,110,14),prepared('OK',309,281,24,16)]
        good=prepared('100,000 citizens.',146,228,110,14)
        for case in ('good','different','number_changed','extra','partial','weak','distant'):
            rows=copy.deepcopy(base);a=copy.deepcopy(good);b=copy.deepcopy(good)
            if case=='different':b['text']='100.000 citizens.'
            if case=='number_changed':a['text']=b['text']='200,000 citizens.'
            if case=='extra':rows.append(prepared('Cancel',400,281,50,16))
            if case=='partial':rows[1]['text']='The population now exceeds'
            if case=='weak':b['confidence']=.5
            if case=='distant':b=prepared(good['text'],146,250,110,14)
            with patch.object(observe,'_crop_text',side_effect=[[a],[b]]):
                observe._recover_population_notice(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[2]['text'],good['text'] if case=='good' else base[2]['text'],case)
            if case=='good':self.assertEqual(rows[2]['provenance'][0]['text'],'100.000 citizens.')

    def test_optional_original_fertile_notice(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-005/screens/ui-0001970.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original frame unavailable')
        from civ2.run import game_text
        from civ2.dialogs import classify_dialog
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'FERTILE')
        self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertFalse(d['requires_model'])
        row=next(r for r in o['lines'] if r['text']=='100,000 citizens.')
        self.assertEqual(row['provenance'][0]['text'],'100.000 citizens.')


if __name__=='__main__':unittest.main()
