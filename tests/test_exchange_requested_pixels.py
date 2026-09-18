from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('Cordial TEST Emissary',395,260,145,14),
        prepared('"We note that your primitive civilization has not',308,284,316,16),
        prepared('even discovered Construction. We desire the',308,305,300,16),
        prepared('secret of Mathematits, Do you care to',308,326,258,16),
        prepared('exchange knowledge with us?"',308,347,240,16),
        prepared('"No. We do not need Construction."',343,370,250,16),
        prepared('"Okay, let\'s exchange knowledge."',343,395,230,16),
        prepared('"Will you accept Writing instead?"',343,420,250,16),
        prepared('OK',540,453,24,14)]


class RequestedAdvancePixels(unittest.TestCase):
    def test_requires_full_context_unique_known_advance_and_matching_pixels(self):
        for case in ('valid','different_advance','different_words','disagree','weak','moved','partial','extra','ambiguous'):
            values=rows();names={'mathematics','construction','writing'}
            if case=='partial':values[1]['text']='"You must give us your technology'
            if case=='extra':values.append(prepared('Cancel',400,453,45,14))
            if case=='ambiguous':names.add('mathematits')
            before=deepcopy(values)
            def crop(image,old,name,*args,**kwargs):
                fresh=deepcopy(old);fresh['text']='secret of Mathematics. Do you care to'
                if case=='different_advance':fresh['text']='secret of Construction. Do you care to'
                if case=='different_words':fresh['text']='secret of Mathematics. Do you want to'
                if case=='disagree' and kwargs.get('grayscale'):fresh['text']=old['text']
                if case=='weak':fresh['confidence']=.5
                if case=='moved':fresh['bounds'][1]+=20;fresh['center'][1]+=20
                return [fresh]
            with patch.object(observe,'_research_names',return_value=names),patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_exchange_requested_advance(Image.new('RGB',(640,480)),values,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(values[3]['text'],'secret of Mathematics. Do you care to')
                self.assertEqual(values[:3]+values[4:],before[:3]+before[4:]);self.assertEqual(len(values[3]['provenance']),3)
            else:self.assertEqual(values,before,case)

    def test_actual_3312_keeps_all_three_genuine_choices(self):
        path=Path('runs/attempt-010/screens/ui-0003312.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(path);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EXCHANGE0')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text']for r in d['options']],['"No. We do not need Construction."','"Okay, let\'s exchange knowledge."','"Will you accept Writing instead?"'])
        row=next(r for r in o['lines']if r['text'].startswith('secret of'))
        self.assertEqual(row['text'],'secret of Mathematics. Do you care to')
        self.assertIn('Mathematits',row['provenance'][0]['text'])
        self.assertEqual([p['text']for p in row['provenance'][-2:]],['secret of Mathematics. Do you care to']*2)


if __name__=='__main__':unittest.main()
