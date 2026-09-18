from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('Worshipful TEST Emissary',386,306,164,14),
        prepared('"You have made peace with our evil neighhors:',304,330,316,16),
        prepared('the TEST. We request you cancel this treaty',304,350,320,16),
        prepared('at oncel"',304,370,64,16),
        prepared('"Never! The TEST are our friends."',339,394,260,16),
        prepared('"Yes! Let us teach the TEST a lesson!"',339,419,285,16),
        prepared('OK',463,453,24,14)]


class CancelTreatyPixels(unittest.TestCase):
    def test_atomic_prose_and_matching_target_choices_are_required(self):
        for case in ('valid','disagree','weak','other_words','wrong_target','partial','extra','moved'):
            values=rows()
            if case=='wrong_target':values[5]['text']=values[5]['text'].replace('TEST','OTHER')
            if case=='partial':values.pop(5)
            if case=='extra':values.append(prepared('Cancel',400,453,40,14))
            before=deepcopy(values)
            def crop(image,old,name,*args,**kwargs):
                r=deepcopy(old);r['text']='"You have made peace with our evil neighbors:' if 'intro' in name else 'at once!"'
                if case=='other_words':r['text']=r['text'].replace('peace','war')
                if case=='disagree' and kwargs.get('scale')==3:r['text']=old['text']
                if case=='weak':r['confidence']=.5
                if case=='moved':r['bounds'][1]+=12;r['center'][1]+=12
                return [r]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_cancel_treaty_body(Image.new('RGB',(640,480)),values,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(values[1]['text'],'"You have made peace with our evil neighbors:')
                self.assertEqual(values[3]['text'],'at once!"')
                self.assertEqual(values[2],before[2]);self.assertEqual(values[4:],before[4:])
                self.assertEqual(len(values[3]['provenance']),3)
            else:self.assertEqual(values,before,case)

    def test_actual_3351_has_two_genuine_treaty_choices(self):
        path=Path('runs/attempt-010/screens/ui-0003351.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(path);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'CANCELTREATY1')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text']for r in d['options']],['"Never! The Germans are our friends."','"Yes! Let us teach the Germans a lesson!"'])
        tail=next(r for r in o['lines']if r['text']=='at once!"')
        self.assertEqual(tail['provenance'][0]['text'],'at oncel"')
        self.assertEqual([p['scale']for p in tail['provenance'][-2:]],[2,3])


if __name__=='__main__':unittest.main()
