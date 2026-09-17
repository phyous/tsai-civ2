"""Synthetic TEST radio labels; real words, numbers and choices stay intact."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class HeraldOptionPixels(unittest.TestCase):
    def test_pair_cannot_invent_words_numbers_or_an_extra_choice(self):
        old=prepared('© "Pay 100 TEST gold."',294,394,268,18)
        fresh=prepared('"Pay 100 TEST gold."',314,394,248,20)
        for case in ('valid','missing_quote','disagree','changed_amount','changed_word','extra_choice','leading_apostrophe','low_confidence','wrong_place','extra_button'):
            rows=[prepared('TEST Emissary',390,257,134,18),deepcopy(old),prepared('OK',444,453,24,16)]
            second=deepcopy(fresh)
            if case=='missing_quote':rows[1]['text']='"Pay 100 TEST gold.'
            elif case=='disagree':second['text']='"Pay 100 TEST gold!"'
            elif case=='changed_amount':fresh_case=deepcopy(fresh);fresh_case['text']='"Pay 200 TEST gold."';second=deepcopy(fresh_case)
            elif case=='changed_word':fresh_case=deepcopy(fresh);fresh_case['text']='"Pay 100 OTHER gold."';second=deepcopy(fresh_case)
            elif case=='extra_choice':second['text']='"Pay 100 TEST gold." "No."'
            elif case=='leading_apostrophe':second['text']='"\'Pay 100 TEST gold."'
            elif case=='low_confidence':second['confidence']=.5
            elif case=='wrong_place':second.update(bounds=[20,30,248,20],center=[144,40])
            elif case=='extra_button':rows.append(prepared('Cancel',550,450,50,16))
            first=fresh_case if case in ('changed_amount','changed_word') else fresh
            before=deepcopy(rows)
            with patch.object(observe,'_crop_text',side_effect=lambda *args,**kwargs:[deepcopy(second if kwargs.get('grayscale') else first)]) as crop:
                observe._recover_herald_options(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            if case in ('valid','missing_quote'):
                self.assertEqual(rows[1]['text'],fresh['text']);self.assertEqual(len(rows[1]['provenance']),3)
            else:self.assertEqual(rows,before)
            if case=='extra_button':crop.assert_not_called()

    def test_optional_original_010_has_all_three_source_choices(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-010/screens/ui-0000521.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original trade absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EXCHANGE0')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text'] for r in d['options']],['"No. We do not need Warrior Code."',
            '"Okay, let\'s exchange knowledge."','"Will you accept Ceremonial Burial instead?"'])
        recovered=next(r for r in o['lines'] if r['text']=='"Will you accept Ceremonial Burial instead?"')
        self.assertEqual(recovered['provenance'][0]['text'],'© "Will you accept Ceremonial Burial instead?"')

    def test_optional_original_010_followup_does_not_accept_residual_apostrophe(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-010/screens/ui-0000547.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original followup absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EXCHANGE0')
        self.assertTrue(d['requires_model'])
        self.assertEqual(d['options'][1]['text'],'"Okay, let\'s exchange knowledge."')
        self.assertEqual(d['options'][2]['text'],'"Will you accept Bronze Working instead?"')

    def test_optional_original_010_treaty_closing_quote_is_read_not_appended(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-010/screens/ui-0000563.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original treaty absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['options'][0]['text'],'"Yes, we welcome peace with the Germans."')
        self.assertEqual(d['options'][1]['text'],'"No, your terms are not acceptable."')
        r=next(r for r in o['lines'] if r['text']==d['options'][0]['text'])
        self.assertEqual(r['provenance'][0]['text'],'"Yes, we welcome peace with the Germans.')

    def test_wider_horizontal_pair_still_requires_identical_complete_words(self):
        raw=prepared('"No. We do not need TEST Riding.',336,370,280,18)
        correct=prepared('"No. We do not need TEST Riding."',345,368,285,20)
        for corrupted in (False,True):
            rows=[prepared('TEST Emissary',390,257,134,18),deepcopy(raw),prepared('OK',444,453,24,16)]
            bad=deepcopy(correct);bad['text']='"No. We do not need OTHER Riding."'
            with patch.object(observe,'_crop_text',side_effect=[[raw],[raw],[correct],[bad if corrupted else correct]]) as crop:
                observe._recover_herald_options(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(crop.call_args_list[-1].kwargs['padding'],(18,3))
            self.assertEqual(rows[1]['text'],raw['text'] if corrupted else correct['text'])

    def test_optional_original_long_technology_label_restores_all_real_choices(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-010/screens/ui-0001782.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original trade absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EXCHANGE0')
        self.assertTrue(d['requires_model']);self.assertEqual(len(d['options']),3)
        self.assertEqual(d['options'][0]['text'],'"No. We do not need Horseback Riding."')
        r=next(r for r in o['lines'] if r['text']==d['options'][0]['text'])
        self.assertEqual(r['provenance'][0]['text'],'"No. We do not need Horseback Riding.')
        self.assertEqual(len(r['provenance']),3)


if __name__=='__main__':unittest.main()
