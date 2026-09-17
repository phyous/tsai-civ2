"""VIOLATOR remains a two-choice treaty decision after exact pixel recovery."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2.observe import _recover_withdrawal_warning,recognize
from test_treaty_reminder import row


def rows():
    return [row('Neubral TEST Emissary',240,148,160),
        row('"Your troops have violated the territory of our',196,172,310),
        row('city of TEST City. By the terms of our peace',196,192,286),
        row('treaty, you must withdraw inmediately or face',198,214,306),
        row('the consequences! Will you comply?"',196,232,252),
        row('O Withdraw troops to nearest city.',206,258,242),
        row('"No! We renounce this worthless treaty!"',232,282,282),row('OK',308,318,24)]


class WithdrawalPixels(unittest.TestCase):
    def test_every_read_must_agree_and_replacements_are_atomic(self):
        for mode in ('valid','body_disagrees','option_disagrees','changed_words','weak','missing_terms','missing_choice'):
            original=rows();before=deepcopy(original)
            body=deepcopy(original[3]);body['text']=body['text'].replace('inmediately','immediately')
            option=deepcopy(original[5]);option['text']=option['text'][2:]
            reads=[[deepcopy(body)],[deepcopy(body)],[deepcopy(option)],[deepcopy(option)]]
            if mode=='body_disagrees':reads[1][0]['text']=original[3]['text']
            elif mode=='option_disagrees':reads[3][0]['text']=original[5]['text']
            elif mode=='changed_words':reads[2][0]['text']=reads[3][0]['text']='Disband troops now.'
            elif mode=='weak':reads[3][0]['confidence']=.5
            elif mode=='missing_terms':original[4]['text']='Will you comply?';before=deepcopy(original)
            elif mode=='missing_choice':original.pop(6);before=deepcopy(original)
            with self.subTest(mode=mode),patch('civ2.observe._crop_text',side_effect=reads):
                _recover_withdrawal_warning(Image.new('RGB',(640,480)),original,None,None,{})
            if mode=='valid':
                self.assertEqual(original[0],before[0]);self.assertEqual(original[2],before[2])
                self.assertEqual(original[3]['text'],body['text']);self.assertEqual(original[5]['text'],option['text'])
                self.assertEqual(len(original[3]['provenance']),3);self.assertEqual(len(original[5]['provenance']),3)
            else:self.assertEqual(original,before)

    def test_actual_complete_original_warning_requires_independent_model_choice(self):
        p=Path('runs/attempt-011/screens/ui-0001616.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame absent')
        from civ2.run import game_text
        from civ2.dialogs import classify_dialog
        o=recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'VIOLATOR')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text'] for r in d['options']],['Withdraw troops to nearest city.','"No! We renounce this worthless treaty!"'])
        self.assertIn('Madrid',d['visible_text']);self.assertIn('immediately',d['visible_text'])
        body=next(r for r in o['lines'] if r['text'].startswith('treaty,'))
        self.assertIn('inmediately',body['provenance'][0]['text'])


if __name__=='__main__':unittest.main()
