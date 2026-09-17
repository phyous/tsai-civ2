"""TEST paired closing sentence; acknowledgement remains source-classified."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class TreatyClosingPixels(unittest.TestCase):
    def test_pair_does_not_change_civilization_or_terms(self):
        for case in ('valid','different_civ','different_terms','extra_button'):
            rows=[prepared('TEST Emissary',345,340,180,16),
                prepared('"We affirm this treaty of eternal friendship and',312,365,314,16),
                prepared('goodwill between the people of the OTHER and',312,385,314,16),
                prepared('TEST civilizations. We shall withdraw ou',312,405,285,15),
                prepared('forces from your ternitory at once."',310,421,239,19),prepared('OK',425,454,25,13)]
            first=prepared('TEST civilizations. We shall withdraw our',312,405,288,14)
            last=prepared('forces from your territory at once."',312,423,238,18)
            if case=='different_civ':first['text']='OTHER civilizations. We shall withdraw our'
            elif case=='different_terms':last['text']='forces from your territory after TEST payment."'
            elif case=='extra_button':rows.append(prepared('No',550,455,20,16))
            original=deepcopy(rows)
            with patch.object(observe,'_crop_text',side_effect=[[deepcopy(first)],[deepcopy(first)],[deepcopy(last)],[deepcopy(last)]]) as crop:
                observe._recover_treaty_closing_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            if case=='valid':self.assertEqual([r['text'] for r in rows[3:5]],[first['text'],last['text']])
            elif case=='different_civ':self.assertEqual(rows[3],original[3])
            elif case=='different_terms':self.assertEqual(rows[4],original[4])
            else:crop.assert_not_called()

    def test_optional_original_010_acknowledges_only_complete_treaty(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-010/screens/ui-0000576.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original treaty absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertFalse(d['requires_model'])
        self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertIn('Roman civilizations. We shall withdraw our',o['text'])
        self.assertIn('forces from your territory at once."',o['text'])
