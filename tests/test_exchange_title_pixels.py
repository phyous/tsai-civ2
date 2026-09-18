from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class ExchangeTitlePixels(unittest.TestCase):
    def test_two_scales_preserve_attitude_and_bound_nation_reading(self):
        old=prepared('Receptive Test Enussary',390,262,150,14)
        for case in ('valid','pair','scale','attitude','nation','position','body','control'):
            rows=[deepcopy(old),prepared('"We note that your primitive civilization has not',308,284,320,20),prepared('OK',455,454,26,16)]
            if case=='body':rows[1]['text']='Different request'
            if case=='control':rows.append(prepared('Cancel',400,455,50,16))
            def crop(image,row,name,*args,**kwargs):
                r=prepared('Receptive Tost Emissary',390,262,150,14)
                if case=='pair' and kwargs.get('grayscale'):r['text']='Receptive Test Emissary'
                if case=='scale' and kwargs.get('scale')==4:r['text']='Receptive Test Emissary'
                if case=='attitude':r['text']='Hostile Tost Emissary'
                if case=='nation':r['text']='Receptive Unrelated Emissary'
                if case=='position':r['bounds'][1]+=40;r['center'][1]+=40
                return [r]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_exchange_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'Receptive Tost Emissary' if case=='valid' else old['text'],case)
            if case=='valid':self.assertEqual(rows[0]['provenance'][0]['text'],old['text'])

    def test_actual_trade_preserves_all_three_choices_and_both_technologies(self):
        p=Path('runs/attempt-011/screens/ui-0002219.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.run import game_text,labels_text
        from civ2.dialogs import classify_dialog
        before=p.read_bytes();o=observe.recognize(p)
        d=classify_dialog(o,game_text=game_text(),labels_text=labels_text(),rules=parse_rules(original_rules()))
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['resource_tag'],'EXCHANGE0')
        self.assertEqual([r['text'] for r in d['options']],['"No. We do not need Polytheism."',
            '"Okay, let\'s exchange knowledge."','"Will you accept Trade instead?"'])
        self.assertIn('secret of Writing.',d['visible_text'])
        title=next(r for r in o['lines'] if r['text']=='Receptive Zolu Emissary')
        self.assertEqual(title['provenance'][0]['text'],'Receptive Zoie Enussary')
        self.assertEqual(len(title['provenance']),5)
        self.assertEqual(p.read_bytes(),before)


if __name__=='__main__':unittest.main()
