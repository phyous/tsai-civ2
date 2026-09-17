"""Synthetic TEST sentence boundary and optional original diplomatic notice."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class GapePixelsTests(unittest.TestCase):
    def test_only_punctuation_can_change_and_requires_two_actual_reads(self):
        base=[prepared('TEST Viking Emissary',350,340,220,16),
              prepared('wonders of TEST Advance Absolutely no',308,405,297,15),prepared('OK',455,458,24,16)]
        good=prepared('wonders of TEST Advance. Absolutely no',308,405,297,15)
        for case in ('good','different','other_advance','weak','extra','outside'):
            rows=copy.deepcopy(base);a=copy.deepcopy(good);b=copy.deepcopy(good)
            if case=='different':b['text']=base[1]['text']
            if case=='other_advance':a['text']=b['text']=good['text'].replace('TEST Advance','OTHER Advance')
            if case=='weak':b['confidence']=.5
            if case=='extra':rows.append(prepared('No',520,458,24,16))
            if case=='outside':rows[1]['bounds'][0]=50
            with patch.object(observe,'_crop_text',side_effect=[[a],[b]]):
                observe._recover_gape_boundary(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[1]['text'],good['text'] if case=='good' else base[1]['text'],case)

    def test_optional_original_complete_gape_template(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-006/screens/ui-0001276.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original diplomatic notice unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'GAPE')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        r=next(r for r in o['lines'] if r['text']=='wonders of Horseback Riding. Absolutely no')
        self.assertEqual(r['provenance'][0]['text'],'wonders of Horseback Riding, Absolutely no')
        self.assertIn('wonders of Horseback Riding Absolutely no',[v['text'] for v in r['provenance']])


if __name__=='__main__':unittest.main()
