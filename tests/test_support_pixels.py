"""Synthetic TEST support-loss crops and original paused notice."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class SupportPixelTests(unittest.TestCase):
    def test_lowercase_radio_requires_exact_paired_label_and_atomic_body(self):
        for case in ('valid','disagree','different','weak'):
            values=[prepared('bllitary Advisor',270,168,102,14),
                    prepared("Veii can't support Warriors. Unit dishanded.",170,190,290,18),
                    prepared('Zoom to City',206,217,86,18),prepared('o Continue',180,240,87,19),
                    prepared('OK',308,298,24,16)]
            def crop(image,row,name,*args,**kwargs):
                result=copy.deepcopy(row)
                if 'title' in name:result['text']='Military Advisor'
                elif 'body' in name:result['text']="Veii can't support Warriors. Unit disbanded."
                elif 'option' in name:
                    result['text']='Continue'
                    if case=='disagree' and 'gray' in name:result['text']='o Continue'
                    if case=='different':result['text']='Zoom to City'
                    if case=='weak':result['confidence']=.5
                return [result]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_support_notice(Image.new('RGB',(640,480)),values,None,None,{})
            self.assertEqual(values[0]['text'],'Military Advisor' if case=='valid' else 'bllitary Advisor',case)
            self.assertEqual(values[3]['text'],'Continue' if case=='valid' else 'o Continue',case)

    def test_actual_veii_support_preserves_two_model_choices(self):
        p=Path('runs/attempt-011/screens/ui-0003267.png')
        if not p.exists():self.skipTest('Private original notice unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),
            state={'cities':[{'name':'Veii'}]},rules={'units':[{'name':'Warriors'}]})
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['resource_tag'],'SUPPORT')
        self.assertEqual([v['text'] for v in d['options']],['Zoom to City','Continue'])
        option=next(r for r in o['lines'] if r['text']=='Continue')
        self.assertEqual(option['provenance'][0]['text'],'o Continue')
        self.assertEqual({r['preprocessing'] for r in option['provenance'][1:]},
                         {'support_option_rgb2','support_option_gray2'})

    def test_black_glyph_fallback_requires_two_complete_unchanged_body_reads(self):
        for case in ('valid','disagree','city_changed','unit_changed','low'):
            values=[prepared('Aflitary Advisor',270,168,102,14),
                    prepared("Neapolis can't support Warriors. Unit dishanded.",168,192,324,16),
                    prepared('Zoom to City',206,217,86,17),prepared('Continue',206,242,60,14),prepared('OK',308,298,24,16)]
            def crop(image,row,name,*args,**kwargs):
                result=copy.deepcopy(row)
                if 'title' in name:result['text']='Military Advisor' if name.endswith(('rgb4','gray4')) else 'Nlitary Advisor'
                elif 'black70' in name:
                    result['text']="Neapolis can't support Warriors. Unit disbanded."
                    if case=='disagree' and name.endswith('3x'):result['text']=row['text']
                    if case=='city_changed':result['text']=result['text'].replace('Neapolis','Rome')
                    if case=='unit_changed':result['text']=result['text'].replace('Warriors','Settlers')
                    if case=='low':result['confidence']=.5
                return [result]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_support_notice(Image.new('RGB',(640,480)),values,None,None,{})
            self.assertEqual(values[0]['text'],'Military Advisor' if case=='valid' else 'Aflitary Advisor',case)
            self.assertEqual(values[1]['text'],"Neapolis can't support Warriors. Unit disbanded." if case=='valid' else "Neapolis can't support Warriors. Unit dishanded.",case)

    def test_actual_neapolis_support_loss_preserves_model_alternatives(self):
        p=Path('runs/attempt-010/screens/ui-0002549.png')
        if not p.exists():self.skipTest('Private original notice unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),
            state={'cities':[{'name':'Neapolis'}]},rules={'units':[{'name':'Warriors'}]})
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['resource_tag'],'SUPPORT')
        self.assertEqual([v['text'] for v in d['options']],['Zoom to City','Continue'])
        body=next(r for r in o['lines'] if 'can\'t support' in r['text'])
        self.assertEqual(body['provenance'][0]['text'],"Neapolis can't support Warriors. Unit dishanded.")
        self.assertEqual({p['preprocessing'] for p in body['provenance'][1:]},{'support_body_black70_2x','support_body_black70_3x'})

    def test_title_and_body_are_atomic_preserving_city_unit_and_two_options(self):
        rows=[prepared('Iflitary Advisor',268,168,104,16),
              prepared("TEST Rome can't support Settlers, Unit dishanded.",168,192,298,16),
              prepared('Zoom to City',206,217,86,17),prepared('Continue',206,242,60,14),prepared('OK',308,298,24,16)]
        title=prepared('Military Advisor',268,168,104,16)
        body=prepared("TEST Rome can't support Settlers. Unit disbanded.",168,192,298,16)
        for case in ('good','different','city_changed','unit_changed','weak','partial','extra'):
            current=copy.deepcopy(rows);a=copy.deepcopy(body);b=copy.deepcopy(body)
            if case=='different':b['text']=b['text'].replace('disbanded','dishanded')
            if case=='city_changed':a['text']=b['text']=body['text'].replace('Rome','Veii')
            if case=='unit_changed':a['text']=b['text']=body['text'].replace('Settlers','Warriors')
            if case=='weak':b['confidence']=.5
            if case=='partial':current.pop(3)
            if case=='extra':current.append(prepared('Cancel',400,298,50,16))
            with patch.object(observe,'_crop_text',side_effect=[[title],[title],[a],[b]]):
                observe._recover_support_notice(Image.new('RGB',(640,480)),current,None,None,{'passes':[]})
            self.assertEqual(current[0]['text'],title['text'] if case=='good' else rows[0]['text'],case)
            self.assertEqual(current[1]['text'],body['text'] if case=='good' else rows[1]['text'],case)

    def test_optional_original_support_loss_still_requires_a_model_choice(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-009/screens/ui-0000357.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original notice unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),
            state={'cities':[{'name':'Rome'}]},rules={'units':[{'name':'Settlers'}]})
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['kind'],'support_loss_notice');self.assertEqual(d['resource_tag'],'SUPPORT')
        self.assertEqual([v['text'] for v in d['options']],['Zoom to City','Continue'])
        self.assertEqual(next(v for v in o['lines'] if v['text']=='Military Advisor')['provenance'][0]['text'],'Iflitary Advisor')

    def test_actual_copyright_radio_support_warning(self):
        p=Path('runs/attempt-012/screens/ui-0003330.png')
        if not p.exists():self.skipTest('Private original notice unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),
            state={'cities':[{'name':'Neapolis'}]},rules={'units':[{'name':'Warriors'}]})
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['resource_tag'],'SUPPORT')
        self.assertEqual([r['text']for r in d['options']],['Zoom to City','• Continue'])
        row=next(r for r in o['lines']if r['text']=='Zoom to City')
        self.assertEqual([p['text']for p in row['provenance']],['© Zoom to City','Zoom to City','Zoom to City'])


if __name__=='__main__':unittest.main()
