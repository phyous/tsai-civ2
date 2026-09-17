from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2.observe import _recover_city_caption_year,recognize

class CaptionYear(unittest.TestCase):
    def fixture(self):
        old=dict(text='City of Comae, 325 B.C., TEST unchanged',bounds=[116,40,410,18],center=[321,49],confidence=1,provenance=[{'text':'TEST original'}])
        a=dict(text='City of Cumae, 825 B.C., P',bounds=[117,40,167,18],center=[201,49],confidence=1,provenance=[{'text':'TEST 3x'}])
        b={**deepcopy(a),'text':'City of Comoe, 825 B.C., P','provenance':[{'text':'TEST 4x'}]}
        return old,a,b
    def recover(self,old,a,b):
        with patch('civ2.observe._crop_text',side_effect=[[a],[b]]):
            _recover_city_caption_year(Image.new('RGB',(640,480)),[old],None,None,{'passes':[]})
    def test_only_the_agreed_year_changes(self):
        old,a,b=self.fixture();self.recover(old,a,b)
        self.assertEqual(old['text'],'City of Comae, 825 B.C., TEST unchanged')
        self.assertEqual(old['caption_year_consensus']['independent_scales'],2)
        self.assertEqual(len(old['provenance']),3)
    def test_no_guessing_city_era_digits_or_geometry(self):
        for key,value in [('text','City of Comoe, 725 B.C., P'),('text','City of Other, 825 B.C., P'),
                          ('text','City of Comoe, 825 A.D., P'),('text','City of Comoe, 1825 B.C., P'),
                          ('confidence',.5),('center',[201,65])]:
            old,a,b=self.fixture();before=deepcopy(old);b[key]=value;self.recover(old,a,b)
            self.assertEqual(old,before)
    def test_original_date_is_pixel_read_not_a_native_state_substitution(self):
        p=Path('runs/attempt-012/screens/ui-0000855.png')
        if not p.exists():self.skipTest('Private original capture unavailable')
        o=recognize(p);row=next(r for r in o['lines'] if r['text'].startswith('City of'))
        self.assertIn('Comae, 825 B.C.',row['text'])
        self.assertEqual(row['caption_year_consensus']['old_year'],'325')
        self.assertEqual(row['caption_year_consensus']['observed_year'],'825')

if __name__=='__main__':unittest.main()
