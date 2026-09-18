from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class SplitStatusDate(unittest.TestCase):
    def test_double_damaged_joined_date_needs_matching_second_scale(self):
        for case in ('valid','second_disagrees','other_digit','changed_era'):
            original=prepared('8.D.180' if case!='other_digit' else '8.D.280',474,218,48,10)
            rows=[deepcopy(original)]
            readings=[prepared('A.D. 780',476,218,45,10) for _ in range(4)]
            if case=='second_disagrees':readings[-1]['text']='A.D. 180'
            if case=='changed_era':
                for row in readings:row['text']='B.C. 780'
            with patch.object(observe,'_crop_text',side_effect=[[r] for r in readings]):
                observe._recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'A.D. 780' if case=='valid' else original['text'])

    def test_original_double_damaged_ad780(self):
        path=Path('runs/attempt-012/screens/ui-0002794.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        observed=observe.recognize(path)
        row=next(r for r in observed['lines'] if r['text']=='A.D. 780')
        self.assertEqual([p['text'] for p in row['provenance']],['8.D.180']+['A.D. 780']*4)

    def test_joined_ambiguous_era_requires_four_consistent_pixel_reads(self):
        for case in ('valid','digits','era_disagreement'):
            original=prepared('B.D.700',474,218,48,10);rows=[deepcopy(original)]
            readings=[prepared('A.D. 700',476,218,45,10) for _ in range(4)]
            if case=='digits':
                for row in readings:row['text']='A.D. 710'
            if case=='era_disagreement':
                for row in readings[2:]:row['text']='B.C. 700'
            with patch.object(observe,'_crop_text',side_effect=[[r] for r in readings]):
                observe._recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'A.D. 700' if case=='valid' else original['text'])

    def test_original_joined_ad700(self):
        path=Path('runs/attempt-012/screens/ui-0002741.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        observed=observe.recognize(path)
        row=next(r for r in observed['lines'] if r['text']=='A.D. 700')
        self.assertEqual([p['text'] for p in row['provenance']],['B.D.700']+['A.D. 700']*4)

    def test_split_pair_only_permits_complete_second_scale_reads(self):
        for case in ('valid','disagree','digits','era','gap','second_disagrees'):
            original=prepared('ALD. 80',472,218,44,10);rows=[deepcopy(original)]
            a=[prepared('A.D.',476,218,23,10),prepared('80',498,218,17,9)];b=deepcopy(a)
            if case=='disagree':b[1]['text']='90'
            if case=='digits':a[1]['text']=b[1]['text']='90'
            if case=='era':a[0]['text']=b[0]['text']='B.C.'
            if case=='gap':a[1]['bounds'][0]+=20;b[1]['bounds'][0]+=20
            c=prepared('A.D. 80',476,216,39,14);d=deepcopy(c)
            if case=='second_disagrees':d['text']='A.D. 90'
            with patch.object(observe,'_crop_text',side_effect=[a,b,[c],[d]]) as crop:
                observe._recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'A.D. 80' if case=='valid' else original['text'],case)
            self.assertEqual(crop.call_count,4 if case in ('valid','second_disagrees') else 2)
            self.assertEqual(rows[0]['provenance'][0]['text'],original['text'])

    def test_original_ad80_uses_actual_complete_second_scale(self):
        p=Path('runs/attempt-012/screens/ui-0001727.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        before=p.read_bytes();o=observe.recognize(p)
        date=next(r for r in o['lines'] if r['text']=='A.D. 80')
        self.assertEqual([r['text'] for r in date['provenance']],['ALD. 80','A.D. 80','A.D. 80'])
        self.assertEqual({r['preprocessing'] for r in date['provenance'][1:]},{'status_year_rgb2','status_year_gray2'})
        self.assertEqual(p.read_bytes(),before)


if __name__=='__main__':unittest.main()
