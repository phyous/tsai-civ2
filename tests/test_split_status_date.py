from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class SplitStatusDate(unittest.TestCase):
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
