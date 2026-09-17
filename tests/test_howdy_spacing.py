from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class HowdySpacingTests(TestCase):
    def test_two_actual_same_pixel_reads_required_and_only_spacing_changes(self):
        for case in ('valid','disagree','different_words','missing_quote','low_confidence','moved','extra_choice'):
            rows=[prepared('Worshipful TEST Emissary',381,380,177,16),
                  prepared('"We are always pleased tospeak with our',306,402,285,19),
                  prepared('friends the TEST."',307,420,147,19),prepared('OK',455,454,25,13)]
            expected='"We are always pleased to speak with our'
            a=prepared(expected,306,401,283,21);b=deepcopy(a)
            if case=='disagree':b['text']=rows[1]['text']
            elif case=='different_words':a['text']=b['text']=expected.replace('always','never')
            elif case=='missing_quote':a['text']=b['text']=expected[1:]
            elif case=='low_confidence':b['confidence']=.7
            elif case=='moved':b['center'][1]+=12;b['bounds'][1]+=12
            elif case=='extra_choice':rows.append(prepared('Pay tribute.',307,442,90,12))
            before=deepcopy(rows)
            with self.subTest(case=case),TemporaryDirectory() as directory,patch.object(
                    observe,'_crop_text',side_effect=[[a],[b]]) as crop:
                observe._recover_howdy_spacing(Image.new('RGB',(640,480)),rows,None,directory,{'passes':[]})
            if case=='valid':
                self.assertEqual(rows[1]['text'],expected)
                self.assertEqual(rows[1]['provenance'][0]['text'],before[1]['text'])
                self.assertEqual(rows[2],before[2])
            else:self.assertEqual(rows,before)
            if case=='extra_choice':crop.assert_not_called()

    def test_actual_0102025_complete_source_notice_only(self):
        p=Path('runs/attempt-010/screens/ui-0002025.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original capture unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d)
        self.assertEqual(d['resource_tag'],'HOWDYPEACE')
        self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertFalse(d['requires_model'])
        row=next(r for r in o['lines'] if r['text'].startswith('"We are always'))
        self.assertEqual(row['text'],'"We are always pleased to speak with our')
        self.assertIn('"We are always pleased tospeak with our',[x['text'] for x in row['provenance']])
        self.assertEqual([r['text'] for r in d['buttons']],['OK'])
