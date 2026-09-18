from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class StatusPopulationPixels(unittest.TestCase):
    def test_four_complete_reads_preserve_every_known_digit_and_geometry(self):
        for mode in ('valid','different','changed_digit','comma','weak','moved','extra','missing_status','valid_native'):
            rows=[prepared('Statos',532,184,40,12),prepared('6:0,000 People',474,206,82,10)]
            if mode=='missing_status':rows[0]['text']='Other'
            if mode=='valid_native':rows[1]['text']='670,000 People'
            before=deepcopy(rows)
            def crop(image,row,name,*args,**kwargs):
                r=deepcopy(row);r['text']='670,000 People'
                if mode=='different' and kwargs.get('scale')==2:r['text']='680,000 People'
                if mode=='changed_digit':r['text']='671,000 People'
                if mode=='comma':r['text']='670.000 People'
                if mode=='weak':r['confidence']=.5
                if mode=='moved':r['bounds'][1]+=15;r['center'][1]+=15
                return [r,r] if mode=='extra' else [r]
            with patch.object(observe,'_crop_text',side_effect=crop) as called:
                observe._recover_status_population(Image.new('RGB',(640,480)),rows,None,None,{})
            if mode=='valid':
                self.assertEqual(rows[1]['text'],'670,000 People')
                self.assertEqual(len(rows[1]['provenance']),5)
                self.assertEqual(rows[1]['provenance'][0]['text'],'6:0,000 People')
            else:self.assertEqual(rows,before,mode)
            if mode in ('missing_status','valid_native'):called.assert_not_called()

    def test_actual_population_four_complete_reads(self):
        p=Path('runs/attempt-011/screens/ui-0003403.png')
        if not p.exists():self.skipTest('Private original calibration unavailable')
        o=observe.recognize(p)
        row=next(r for r in o['lines'] if r['text']=='670,000 People')
        self.assertEqual(row['provenance'][0]['text'],'6:0,000 People')
        self.assertEqual({r['preprocessing'] for r in row['provenance'][1:]},
                         {'status_population_rgb3','status_population_gray3',
                          'status_population_rgb2','status_population_gray2'})


if __name__=='__main__':unittest.main()
