"""Synthetic TEST support-loss crops and original paused notice."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class SupportPixelTests(unittest.TestCase):
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


if __name__=='__main__':unittest.main()
