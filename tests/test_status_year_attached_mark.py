from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2.observe import _recover_status_year,recognize
from tests.test_status_year import row


class AttachedStatusMark(unittest.TestCase):
    def test_attached_marker_only_locates_crops_and_never_supplies_date(self):
        for left,right in (('A.D. 40','A.D. 40'),('A.D. 40','A.D. 41'),('A.D. 41','A.D. 41'),
                           ('40 B.C.','40 B.C.'),('A.D. 400','A.D. 400')):
            rows=[row('A.D. 40(')]
            with patch('civ2.observe._crop_text',side_effect=[[row(left)],[row(right)]]):
                _recover_status_year(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[0]['text'],'A.D. 40' if left==right=='A.D. 40' else 'A.D. 40(')
            self.assertEqual(rows[0]['provenance'][0]['text'],'A.D. 40(')

    def test_original_status_preserves_both_digits_and_era(self):
        path=Path('runs/attempt-011/screens/ui-0002576.png')
        if not path.exists():self.skipTest('Private original status frame unavailable')
        original=path.read_bytes();o=recognize(path)
        date=next(r for r in o['lines'] if r['text']=='A.D. 40')
        self.assertEqual([p['text'] for p in date['provenance']],['A.D. 40(','A.D. 40','A.D. 40'])
        self.assertEqual(path.read_bytes(),original)


if __name__=='__main__':unittest.main()
