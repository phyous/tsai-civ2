from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class SplitStatusDate(unittest.TestCase):
    def test_six_read_consensus_is_not_replaced_by_second_crop(self):
        for prefix in ('status_letter_year_','status_colon_year_'):
            row=prepared('A.D. 1110',476,218,52,10)
            row['provenance']=[dict(preprocessing=prefix+'rgb2')]
            with patch.object(observe,'_crop_text') as crop:
                observe._recover_status_year(Image.new('RGB',(640,480)),[row],None,None,{'passes':[]})
            crop.assert_not_called()

    def test_lettered_year_requires_six_complete_agreeing_reads(self):
        for case in ('valid','disagree','era','position','incomplete','raw_numeric'):
            old=prepared('ALD. BED',476,218,52,10);old['confidence']=.3
            if case=='raw_numeric':old['text']='ALD. 100'
            rows=[deepcopy(old)]
            reads=[prepared('A.D. 1110',476,215,51,14) for _ in range(6)]
            if case=='disagree':reads[-1]['text']='A.D. 1100'
            if case=='era':
                for r in reads:r['text']='B.C. 1110'
            if case=='position':reads[-1]['center'][1]+=20
            values=[[r] for r in reads]
            if case=='incomplete':values[-1]=[]
            with patch.object(observe,'_crop_text',side_effect=values):
                observe._recover_lettered_status_year(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'A.D. 1110' if case=='valid' else old['text'])

    def test_original_lettered_ad1110(self):
        p=Path('runs/attempt-012/screens/ui-0003171.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        row=next(r for r in observe.recognize(p)['lines'] if r['text']=='A.D. 1110')
        self.assertEqual([r['text'] for r in row['provenance']],['ALD. BED']+['A.D. 1110']*6)

    def test_punctuated_year_requires_six_matching_complete_reads(self):
        for case in ('valid','last_disagrees','era','trailing_digits','leading_digit','position'):
            old=prepared('A.D. 18:00',476,218,52,10);rows=[deepcopy(old)]
            readings=[prepared('A.D. 1100',476,216,51,13) for _ in range(6)]
            if case=='last_disagrees':readings[-1]['text']='A.D. 1800'
            if case in ('era','trailing_digits','leading_digit'):
                for r in readings:r['text']={'era':'B.C. 1100','trailing_digits':'A.D. 1110','leading_digit':'A.D. 2100'}[case]
            if case=='position':readings[-1]['center'][1]+=20
            with patch.object(observe,'_crop_text',side_effect=[[r] for r in readings]):
                observe._recover_punctuated_status_year(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'A.D. 1100' if case=='valid' else old['text'])

    def test_original_punctuated_ad1100(self):
        p=Path('runs/attempt-012/screens/ui-0003157.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        row=next(r for r in observe.recognize(p)['lines'] if r['text']=='A.D. 1100')
        self.assertEqual([r['text'] for r in row['provenance']],['A.D. 18:00']+['A.D. 1100']*6)

    def test_valid_date_seven_requires_four_identical_complete_reads(self):
        for case in ('valid','other_digit','era','disagree','position','split'):
            original=prepared('A.D. 180',472,218,50,10);rows=[deepcopy(original)]
            reads=[prepared('A.D. 780',476,216,45,13) for _ in range(4)]
            if case=='other_digit':
                for r in reads:r['text']='A.D. 190'
            if case=='era':
                for r in reads:r['text']='B.C. 780'
            if case=='disagree':reads[-1]['text']='A.D. 180'
            if case=='position':reads[-1]['center'][1]+=20
            calls=[[r] for r in reads]
            if case=='split':calls[-1]=[reads[-1],deepcopy(reads[-1])]
            with patch.object(observe,'_crop_text',side_effect=calls):
                observe._recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'A.D. 780' if case=='valid' else original['text'])

    def test_original_valid_looking_ad780(self):
        p=Path('runs/attempt-011/screens/ui-0003403.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        row=next(r for r in observe.recognize(p)['lines'] if r['text']=='A.D. 780')
        self.assertEqual([r['text'] for r in row['provenance']],['A.D. 180']+['A.D. 780']*4)

    def test_ambiguous_split_era_needs_two_complete_agreeing_scales(self):
        for case in ('valid','last_disagrees','era_disagrees','split_era_conflict','digits'):
            old=prepared('B.D. 880',472,218,50,10);rows=[deepcopy(old)]
            split=[prepared('A.D.',476,218,23,10),prepared('880',498,218,23,9)]
            complete=[prepared('A.D. 880',476,216,45,13) for _ in range(4)]
            if case=='last_disagrees':complete[-1]['text']='A.D. 890'
            if case=='era_disagrees':
                for r in complete[2:]:r['text']='B.C. 880'
            if case=='split_era_conflict':
                for r in complete:r['text']='B.C. 880'
            if case=='digits':
                for r in complete:r['text']='A.D. 890'
            with patch.object(observe,'_crop_text',side_effect=[split,deepcopy(split)]+[[r] for r in complete]):
                observe._recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'A.D. 880' if case=='valid' else old['text'])

    def test_original_ambiguous_split_ad880(self):
        p=Path('runs/attempt-012/screens/ui-0002900.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        row=next(r for r in observe.recognize(p)['lines'] if r['text']=='A.D. 880')
        self.assertEqual([r['text'] for r in row['provenance']],['B.D. 880']+['A.D. 880']*4)

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
