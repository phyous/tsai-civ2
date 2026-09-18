from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class DiplomacyGiftPixelsTests(TestCase):
    def test_paired_actual_option_and_complete_menu_required(self):
        texts=['Worshipful TEST Emissary','You respond: "We..."',
            '"Consider this discussion complete."','"Suggest a permanent strategic alliance."',
            '"Demand tribute for our patience."','"Insist that you withdraw your troops."',
            '"Have a proposal to make..."','"Wish to offer you a gifft..."','OK']
        for case in ('valid','disagree','changed_words','missing_choice','moved'):
            rows=[prepared(t,344,246+25*i,186,18) for i,t in enumerate(texts)]
            rows[7]=prepared(texts[7],344,420,186,18)
            rows[8]=prepared('OK',456,454,26,16)
            a=prepared('"Wish to offer you a gift..."',344,420,186,18);b=deepcopy(a)
            if case=='disagree':b['text']=texts[7]
            elif case=='changed_words':a['text']=b['text']='"Wish to demand a gift..."'
            elif case=='missing_choice':rows.pop(4)
            elif case=='moved':b['center'][1]+=15;b['bounds'][1]+=15
            original=deepcopy(rows)
            with self.subTest(case=case),TemporaryDirectory() as directory,patch.object(
                    observe,'_crop_text',side_effect=[[a],[b]]) as crop:
                observe._recover_diplomacy_gift_row(Image.new('RGB',(640,480)),rows,None,directory,{'passes':[]})
            if case=='valid':
                self.assertEqual(rows[7]['text'],a['text'])
                self.assertEqual(rows[7]['provenance'][0]['text'],texts[7])
            else:self.assertEqual(rows,original)
            if case=='missing_choice':crop.assert_not_called()

    def test_actual_0102037_all_six_options_still_require_model(self):
        p=Path('runs/attempt-010/screens/ui-0002037.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original capture absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'DIPLOMACY')
        self.assertTrue(d['requires_model']);self.assertEqual(len(d['options']),6)
        self.assertEqual(d['options'][-1]['text'],'"Wish to offer you a gift..."')
        row=next(r for r in o['lines'] if r['text'].startswith('"Wish'))
        self.assertIn('"Wish to offer you a gifft..."',[x['text'] for x in row['provenance']])
