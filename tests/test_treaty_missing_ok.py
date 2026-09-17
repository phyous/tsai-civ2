from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('Receptive TEST Emissary',350,338,174,20),
        prepared('"We affirm this treaty of eternal friendship and',312,362,316,18),
        prepared('goodwill hetween the people of the OTHER and',312,384,314,16),
        prepared('TEST civilizations. We shall withdraw ou',314,404,284,14),
        prepared('forces from your territory at once.',312,422,238,18)]


class TreatyMissingOK(unittest.TestCase):
    def test_only_actual_agreeing_button_reads_are_added(self):
        for case in ('valid','disagree','low','moved','terms','other_button'):
            data=rows();a=prepared('OK',425,453,24,14);b=deepcopy(a)
            if case=='disagree':b['text']='No'
            elif case=='low':b['confidence']=.5
            elif case=='moved':b=prepared('OK',300,453,24,14)
            elif case=='terms':data[2]['text']='Pay us 100 gold to accept this treaty.'
            elif case=='other_button':data.append(prepared('Cancel',490,453,35,14))
            before=deepcopy(data)
            with patch.object(observe,'_crop_text',side_effect=[[a],[b]]) as crop:
                observe._recover_treaty_missing_ok(Image.new('RGB',(640,480)),data,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(data[:-1],before);self.assertEqual(data[-1]['text'],'OK')
                self.assertEqual(crop.call_args_list[0].kwargs['scale'],3)
                self.assertEqual(crop.call_args_list[1].kwargs['scale'],4)
            else:self.assertEqual(data,before)

    def test_actual_notice_requires_complete_source_before_acknowledgement(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-012/screens/ui-0001209.png'
        if not p.exists():self.skipTest('Private original treaty unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'TREATY')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        button=next(r for r in o['lines'] if r['text']=='OK')
        self.assertEqual({p['preprocessing'] for p in button['provenance']},
                         {'treaty_missing_ok_3x','treaty_missing_ok_4x'})
