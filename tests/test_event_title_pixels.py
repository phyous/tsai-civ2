"""Synthetic TEST event crops and optional retained original frames."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class EventTitlePixelsTests(unittest.TestCase):
    def test_revolt_notice_requires_full_body_single_ok_and_exact_paired_title(self):
        base=[prepared('Repobntion!',286,184,70,14),
              prepared('The TEST Romans are revolting! Citizens',238,206,236,18),
              prepared('demand new government.',236,228,170,16),prepared('OK',309,282,24,13)]
        good=prepared('Revolution!',286,184,70,14)
        for case in ('good','different','partial','extra','weak','distant'):
            rows=copy.deepcopy(base);peer=copy.deepcopy(good)
            if case=='different':peer['text']='Revolation!'
            if case=='partial':rows[1]['text']='The TEST Romans are revolting!'
            if case=='extra':rows.append(prepared('No',400,282,24,13))
            if case=='weak':peer['confidence']=.5
            if case=='distant':peer=prepared('Revolution!',286,140,70,14)
            with patch.object(observe,'_crop_text',side_effect=[[good],[peer]]):
                observe._recover_revolt_notice_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],good['text'] if case=='good' else base[0]['text'],case)

    def test_completion_crop_keeps_actual_city_item_and_both_strategic_options(self):
        base=[prepared('Domestic Advisor',260,170,120,16),prepared('TEST Rome huilds Settlers.',170,192,148,14),
              prepared('Zoom to City',205,220,90,16),prepared('Continue',205,240,70,16),prepared('OK',309,280,24,14)]
        good=prepared('TEST Rome builds Settlers.',170,192,148,14)
        for case in ('good','wrong_item','wrong_city','partial','weak'):
            rows=copy.deepcopy(base);peer=copy.deepcopy(good)
            if case=='wrong_item':peer['text']='TEST Rome builds Warriors.'
            if case=='wrong_city':peer['text']='TEST Veii builds Settlers.'
            if case=='partial':rows.pop(3)
            if case=='weak':peer['confidence']=.5
            with patch.object(observe,'_crop_text',side_effect=[[good],[peer]]):
                observe._recover_completion_zoom(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[1]['text'],good['text'] if case=='good' else base[1]['text'],case)

    def test_optional_original_revolt_and_completion(self):
        root=Path(__file__).resolve().parents[1]
        paths=[root/'runs/attempt-008/screens/ui-0000256.png',root/'runs/attempt-006/screens/ui-0001164.png']
        if not all(p.exists() for p in paths) or not(root/'.runtime/ocr').exists():self.skipTest('Private original frames unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        a=observe.recognize(paths[0]);d=classify_dialog(a,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertFalse(d['requires_model'])
        self.assertEqual(next(r for r in a['lines'] if r['text']=='Revolution!')['provenance'][0]['text'],'Repobntion!')
        b=observe.recognize(paths[1]);d=classify_dialog(b,game_text=game_text(),state={'cities':[{'name':'Antium'}]},rules={'units':[{'name':'Settlers'}]})
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_notice');self.assertTrue(d['requires_model'])
        self.assertEqual(len(d['options']),2)
        self.assertEqual(next(r for r in b['lines'] if r['text']=='Antium builds Settlers.')['provenance'][0]['text'],'Antium huilds Settlers.')


if __name__=='__main__':unittest.main()
