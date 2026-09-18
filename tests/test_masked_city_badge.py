from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def setup_rows():
    return [prepared('Роmpеї па',264,188,110,32,confidence=.3),
            *[prepared(t,8+i*60,22,40,12) for i,t in enumerate(('Game','Kingdom','View','Orders'))]]


def readings():
    return [prepared('Pompeii',266,188,64,18),prepared('1',338,202,11,15)]


class MaskedCityBadgeTests(unittest.TestCase):
    def test_partial_first_mask_only_permits_second_complete_pair(self):
        for case in ('valid','name_disagrees','third_partial','third_disagrees'):
            rows=setup_rows();a=readings()[:1];b=readings();c=readings()
            if case=='name_disagrees':a[0]['text']='Pompen'
            if case=='third_partial':c=c[:1]
            if case=='third_disagrees':c[1]['text']='2'
            with patch.object(observe,'_crop_text',side_effect=[a,b,c]) as crop,patch.object(observe,'annotate_badges'),\
                 patch('civ2.map_badges.proven_badge',return_value=True):
                observe._recover_masked_city_badge(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[0]['text'],'Pompeii' if case=='valid' else 'Роmpеї па',case)
            self.assertEqual(crop.call_count,2 if case=='name_disagrees' else 3)

    def test_both_components_retained_only_after_agreement_and_full_badge_proof(self):
        for case in ('valid','disagree','missing_digit','extra_text','low_confidence','shift','no_badge','overlap'):
            rows=setup_rows();a=readings();b=deepcopy(a)
            if case=='disagree':b[0]['text']='Pompen'
            if case=='missing_digit':b.pop()
            if case=='extra_text':b.append(prepared('No',350,195,15,12))
            if case=='low_confidence':b[0]['confidence']=.5
            if case=='shift':b[0]['bounds'][1]+=10;b[0]['center'][1]+=10
            if case=='overlap':rows.append(prepared('Other',270,190,40,15))
            with patch.object(observe,'_crop_text',side_effect=[a,b]),patch.object(observe,'annotate_badges'),\
                 patch('civ2.map_badges.proven_badge',return_value=case!='no_badge'):
                observe._recover_masked_city_badge(Image.new('RGB',(640,480)),rows,None,None,{})
            if case=='valid':
                self.assertEqual([r['text'] for r in rows[:2]],['Pompeii','1'])
                self.assertTrue(all(r['provenance'][0].get('text')=='Роmpеї па' for r in rows[:2]))
            else:self.assertEqual(rows[0]['text'],'Роmpеї па',case)

    def test_actual_mixed_script_components_match_pixels_and_keep_native_raw_text(self):
        path=Path('runs/attempt-010/screens/ui-0002304.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        from civ2.map_badges import proven_badge
        before=path.read_bytes();result=observe.recognize(path)
        found=[r for r in result['lines'] if r['provenance'][0].get('text')=='Роmpеї па']
        self.assertEqual(len(found),2)
        self.assertEqual(found[1]['text'],'1')
        self.assertTrue(any(p['text']=='Pompeii' and p['preprocessing']=='masked_city_badge_white160' for p in found[0]['provenance']))
        self.assertTrue(proven_badge(found[1],result['sha256']))
        for row in found:
            self.assertEqual(row['provenance'][0]['text'],'Роmpеї па')
            self.assertTrue({'masked_city_badge_white160','masked_city_badge_white230'} <= {p['preprocessing'] for p in row['provenance']})
        self.assertEqual(path.read_bytes(),before)

    def test_actual_ravenna_third_mask_retains_both_components(self):
        path=Path('runs/attempt-010/screens/ui-0002419.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        from civ2.map_badges import proven_badge
        result=observe.recognize(path)
        found=[r for r in result['lines'] if r['provenance'][0]['text']=='Ravemna a F']
        self.assertEqual(len(found),2);self.assertEqual(found[1]['text'],'1')
        self.assertTrue(proven_badge(found[1],result['sha256']))
        for r in found:
            self.assertTrue({'masked_city_badge_white220','masked_city_badge_white230'} <= {p['preprocessing'] for p in r['provenance']})


if __name__=='__main__':unittest.main()
