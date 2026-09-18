from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
from civ2 import observe
from tests.test_herald import prepared


class ExchangeAdvancePixels(unittest.TestCase):
    def test_real_selected_pixels_and_two_independent_masked_reads_preserve_target(self):
        for case in ('valid','scale','word','geometry','extra','unselected'):
            image=Image.new('RGB',(640,480));ImageDraw.Draw(image).rectangle((580,170,626,182),fill=(105,105,105))
            old=prepared('TEST Adwance',312,170,90,15)
            rows=[prepared('Select Ciadization Advance',384,146,168,16),deepcopy(old),prepared('Goal',372,454,30,14),prepared('OK',538,454,25,12)]
            if case=='extra':rows.append(prepared('Cancel',480,454,40,14))
            if case=='unselected':image.putpixel((590,175),(0,0,0))
            before=deepcopy(rows)
            def crop(image,row,name,*args,**kwargs):
                text='TEST Advance'
                if case=='scale' and kwargs.get('scale')==2:text='TEST Advence'
                if case=='word':text='OTHER Advance'
                r=prepared(text,312,170,92,15)
                if case=='geometry':r['bounds'][1]+=20;r['center'][1]+=20
                return [r]
            with patch.object(observe,'_crop_text',side_effect=crop),patch.object(observe,'_research_names',return_value={'test advance','test advence','other advance'}):
                observe._recover_exchange_advance_row(image,rows,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(rows[1]['text'],'TEST Advance');self.assertEqual(rows[1]['center'],old['center'])
                self.assertEqual(rows[1]['bounds'],old['bounds']);self.assertEqual(len(rows[1]['provenance']),3)
            else:self.assertEqual(rows,before)

    def test_actual_polytheism_is_observed_not_automatically_accepted(self):
        p=Path('runs/attempt-011/screens/ui-0002239.png')
        if not p.exists():self.skipTest('Private original frame unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        before=p.read_bytes();o=observe.recognize(p);o['path']=str(p)
        d=classify_dialog(o,rules=parse_rules(original_rules()),game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'TAKECIV')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual(d['options'][0]['text'],'Polytheism')
        row=next(r for r in o['lines'] if r['text']=='Polytheism')
        self.assertEqual(row['provenance'][0]['text'],'Potytheism');self.assertEqual(row['center'],[347,177])
        self.assertEqual(p.read_bytes(),before)


if __name__=='__main__':unittest.main()
