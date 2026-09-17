"""TEST wider framing still requires two exact reads of the printed intro."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class DiplomacyIntroPixels(unittest.TestCase):
    def test_clipped_first_crop_needs_two_complete_fallback_reads(self):
        for case in ('valid','disagrees'):
            rows=[prepared('TEST Emissary',378,270,182,16),prepared('You respond: "We.',308,294,130,16),
                  prepared('"TEST option one."',344,318,250,18),prepared('"TEST option two."',344,344,250,18),
                  prepared('OK',456,454,25,13)]
            raw={'text':'You respond: "We..."','confidence':1,'x':.02,'y':.13,'width':.94,'height':.7}
            bad={**raw,'text':'You respond: "We...'};last=raw if case=='valid' else bad
            with tempfile.TemporaryDirectory() as directory,patch.object(observe,'_run_ocr',side_effect=[[bad],[deepcopy(raw)],[deepcopy(last)]]):
                observe._recover_diplomacy_intro(Image.new('RGB',(640,480)),rows,None,directory,{'passes':[]})
            self.assertEqual(rows[1]['text'],'You respond: "We..."' if case=='valid' else 'You respond: "We.')
            if case=='valid':self.assertEqual(len(rows[1]['provenance']),3)

    def test_optional_original_010_keeps_all_five_model_options(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-010/screens/ui-0000588.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original menu absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'DIPLOMACY')
        self.assertTrue(d['requires_model']);self.assertEqual(len(d['options']),5)
        self.assertEqual(d['options'][0]['text'],'"Consider this discussion complete."')
