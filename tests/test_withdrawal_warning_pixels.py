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

    def test_treaty_word_and_observed_radio_residual_require_complete_pixel_reads(self):
        for case in ('valid','wrong_treaty','peer','weak','missing_choice'):
            original=rows();original[3]['text']='freaty, you must withdraw immediately or face'
            original[6]['text']='O '+original[6]['text']
            if case=='missing_choice':original.pop(5)
            before=deepcopy(original)
            def crop(image,old,mode,*args,**kwargs):
                fresh=deepcopy(old)
                if 'withdrawal_2' in mode:
                    fresh['text']='treaty, you must withdraw immediately or face'
                    if case=='wrong_treaty':fresh['text']='treaty, you may withdraw immediately or face'
                elif 'withdrawal_4' in mode:fresh['text']='Withdraw troops to nearest city.'
                else:
                    fresh['text']='"No! We renounce this worthless treaty!"'
                    if kwargs['scale']==3:fresh['text']='• '+fresh['text']
                    elif case=='peer' and kwargs.get('grayscale'):fresh['text']='"Yes! We accept this treaty!"'
                    elif case=='weak':fresh['confidence']=.5
                return [fresh]
            with self.subTest(case=case),patch('civ2.observe._crop_text',side_effect=crop):
                _recover_withdrawal_warning(Image.new('RGB',(640,480)),original,None,None,{})
            if case=='valid':
                self.assertEqual(original[3]['text'],'treaty, you must withdraw immediately or face')
                self.assertEqual(original[6]['text'],'"No! We renounce this worthless treaty!"')
                self.assertEqual(len(original[6]['provenance']),5)
                self.assertEqual(original[0],before[0]);self.assertEqual(original[2],before[2])
            else:self.assertEqual(original,before)

    def test_actual_toledo_preserves_two_complete_treaty_choices(self):
        p=Path('runs/attempt-011/screens/ui-0002868.png')
        if not p.exists():self.skipTest('Private original frame absent')
        from civ2.run import game_text
        from civ2.dialogs import classify_dialog
        o=recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'VIOLATOR')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text']for r in d['options']],['Withdraw troops to nearest city.','"No! We renounce this worthless treaty!"'])
        body=next(r for r in o['lines'] if r['text'].startswith('treaty,'))
        self.assertTrue(body['provenance'][0]['text'].startswith('freaty,'))
        refusal=next(r for r in o['lines'] if r['text'].startswith('"No!'))
        self.assertEqual([r.get('scale') for r in refusal['provenance'][1:]],[3,3,2,2])
        self.assertIn('Toledo',d['visible_text'])

    def test_actual_seville_warning_needs_full_spaced_radio_read(self):
        p=Path('runs/attempt-012/screens/ui-0002149.png')
        if not p.exists():self.skipTest('Private original frame absent')
        from civ2.run import game_text
        from civ2.dialogs import classify_dialog
        o=recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'VIOLATOR')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text'] for r in d['options']],['Withdraw troops to nearest city.','"No! We renounce this worthless treaty!"'])
        option=next(r for r in o['lines'] if r['text']=='Withdraw troops to nearest city.')
        self.assertEqual(option['provenance'][0]['text'],'O Withdraw troops to nearest city.')
        self.assertEqual({r['preprocessing'] for r in option['provenance'][1:]},
                         {'withdrawal_4_wide_rgb3','withdrawal_4_wide_gray3'})

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

    def test_both_radio_prefixes_need_complete_agreeing_actual_reads(self):
        for agree in (True,False):
            original=rows();original[3]['text']=original[3]['text'].replace('inmediately','immediately')
            original[6]['text']='• '+original[6]['text'];before=deepcopy(original)
            a=deepcopy(original[5]);a['text']=a['text'][2:]
            b=deepcopy(original[6]);b['text']=b['text'][2:];peer=deepcopy(b)
            if not agree:peer['text']='"No! We accept this treaty!"'
            with patch('civ2.observe._crop_text',side_effect=[[a],[a],[b],[peer]]):
                _recover_withdrawal_warning(Image.new('RGB',(640,480)),original,None,None,{})
            if agree:self.assertEqual([r['text']for r in original[5:7]],[a['text'],b['text']])
            else:self.assertEqual(original,before)

    def test_actual_original_german_warning_keeps_both_alternatives(self):
        p=Path('runs/attempt-010/screens/ui-0002117.png')
        if not p.exists():self.skipTest('Private original frame absent')
        from civ2.run import game_text
        from civ2.dialogs import classify_dialog
        o=recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'VIOLATOR')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text']for r in d['options']],['Withdraw troops to nearest city.','"No! We renounce this worthless treaty!"'])
        self.assertIn('Hamburg',d['visible_text'])
        option=next(r for r in o['lines']if r['text'].startswith('"No!'))
        self.assertTrue(option['provenance'][0]['text'].startswith('• '))


if __name__=='__main__':unittest.main()
