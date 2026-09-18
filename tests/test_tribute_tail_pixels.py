from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('Worshipful TEST Emissary',386,282,164,14),
        prepared('"Your pathetic civilization is hardly worth',308,308,285,16),
        prepared('conquering. We might forego this pleasure for',308,328,304,16),
        prepared('the time being in exchange for 50 gold in',308,348,272,16),
        prepared('tribute"',308,368,60,16),
        prepared('"We laugh at your petty boasts."',343,394,250,16),
        prepared('• Pay 50 gold in tribute.',331,419,182,16),prepared('OK',460,453,24,14)]


class TributeTailPixels(unittest.TestCase):
    def test_amount_and_all_prose_choices_and_pair_are_mandatory(self):
        for case in ('valid','different','disagree','weak','amount','prose','choice','extra'):
            values=rows()
            if case=='amount':values[6]['text']=values[6]['text'].replace('50','500')
            if case=='prose':values[2]['text']=values[2]['text'].replace('forego','pursue')
            if case=='choice':values.pop(5)
            if case=='extra':values.append(prepared('Cancel',400,453,40,14))
            before=deepcopy(values)
            def crop(image,old,name,*args,**kwargs):
                r=deepcopy(old);r['text']='Pay 50 gold in tribute.' if '_payment_' in name else 'tribute."'
                if case=='different':r['text']='tributes."'
                if case=='disagree' and kwargs.get('grayscale'):r['text']=old['text']
                if case=='weak':r['confidence']=.5
                return [r]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_tribute_tail(Image.new('RGB',(640,480)),values,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(values[4]['text'],'tribute."');self.assertEqual(len(values[4]['provenance']),3)
                self.assertEqual(values[:4]+values[5:6]+values[7:],before[:4]+before[5:6]+before[7:])
                self.assertEqual(values[6]['text'],'Pay 50 gold in tribute.')
            else:self.assertEqual(values,before,case)

    def test_actual_3364_payment_and_refusal_remain_real_choices(self):
        path=Path('runs/attempt-010/screens/ui-0003364.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(path);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'TRIBUTE1')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text']for r in d['options']],['"We laugh at your petty boasts."','Pay 50 gold in tribute.'])
        tail=next(r for r in o['lines']if r['text']=='tribute."')
        self.assertEqual(tail['provenance'][0]['text'],'tribute"')


if __name__=='__main__':unittest.main()
