from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class AmbiguousStatusEra(unittest.TestCase):
    def test_two_scales_must_resolve_ambiguous_era_without_changing_digits(self):
        for case in ('valid','different_era','different_digits','one_pair','ambiguous_again'):
            original=prepared('B.D. 140',474,218,48,10);rows=[deepcopy(original)]
            a=prepared('A.D. 140',476,218,44,11);b=deepcopy(a);c=deepcopy(a);d=deepcopy(a)
            if case=='different_era':c['text']=d['text']='140 B.C.'
            if case=='different_digits':c['text']=d['text']='A.D. 150'
            if case=='one_pair':d['text']='B.D. 140'
            if case=='ambiguous_again':a['text']=b['text']='B.D. 140'
            with patch.object(observe,'_crop_text',side_effect=[[a],[b],[c],[d]]):
                observe._recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'A.D. 140' if case=='valid' else original['text'],case)
            self.assertEqual(rows[0]['provenance'][0]['text'],original['text'])
            if case=='valid':self.assertEqual(len(rows[0]['provenance']),5)

    def test_original_ad140_uses_four_actual_readings(self):
        p=Path('runs/attempt-012/screens/ui-0001828.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        o=observe.recognize(p);row=next(r for r in o['lines'] if r['text']=='A.D. 140')
        self.assertEqual([v['text'] for v in row['provenance']],['B.D. 140']+['A.D. 140']*4)
        self.assertEqual({v['preprocessing'] for v in row['provenance'][1:]},
            {'status_year_rgb3','status_year_gray3','status_year_rgb2','status_year_gray2'})


if __name__=='__main__':unittest.main()
