"""Synthetic TEST name-form OCR; optional unchanged original pixels."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class NameCityPixels(unittest.TestCase):
    def test_complete_form_and_two_exact_title_reads_are_required(self):
        old=prepared('What Shall We LTame This Cicy?',222,200,198,16)
        fresh=prepared('What Shall We Name This City?',222,200,198,16)
        for case in ('valid','disagreement','missing_field','extra_control','wrong_location'):
            rows=[deepcopy(old),prepared('City Name:',100,228,72,16),
                  prepared('TEST NAME',188,228,70,16),prepared('OK',199,265,18,16),
                  prepared('Cancel',414,265,40,16)]
            second=deepcopy(fresh)
            if case=='disagreement':second['text']='What Shall We Name This Ciy?'
            if case=='missing_field':rows.pop(1)
            if case=='extra_control':rows.append(prepared('Yes',300,300,20,16))
            if case=='wrong_location':second.update(bounds=[20,80,198,16],center=[119,88])
            with patch.object(observe,'_crop_text',side_effect=[[fresh],[second]]) as crop:
                observe._recover_name_city_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],fresh['text'] if case=='valid' else old['text'],case)
            self.assertEqual(next(r for r in rows if r['text']=='TEST NAME')['text'],'TEST NAME')
            if case in ('missing_field','extra_control'):crop.assert_not_called()

    def test_optional_original_010_name_form_keeps_observed_default(self):
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-010/screens/ui-0000346.png'
        if not path.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original name form unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        before=path.read_bytes();o=observe.recognize(path);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'new_city_name')
        self.assertEqual(d['default_name'],'Antium')
        row=next(r for r in o['lines'] if r['text']=='What Shall We Name This City?')
        self.assertEqual(row['provenance'][0]['text'],'What Shall We LTame This Cicy?')
        self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
