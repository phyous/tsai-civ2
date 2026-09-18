from copy import deepcopy
from pathlib import Path
from unittest import TestCase,mock
from PIL import Image
from civ2.observe import _recover_gape_title,recognize
from tests.test_herald import prepared


def rows():
    return [prepared('Uncooperative TEST Emisoury',380,340,180,16),
            prepared('"You are invited to gape with awe and',308,362,254,18),
            prepared('amazement as the TEST demonstrate the',308,384,274,14),
            prepared('wonders of TEST. Absolutely no scribes',308,402,318,18),
            prepared('will be allowed."',308,422,112,16),prepared('OK',457,454,24,13)]


class GapeTitlePixels(TestCase):
    def test_full_four_reads_agree_without_changing_attitude_or_body(self):
        for case in ('valid','scale_disagreement','attitude','nation','body','choice','geometry'):
            original=rows();a=prepared('Uncooperative TEST Emissary',380,340,180,16)
            reads=[deepcopy(a) for _ in range(4)]
            if case=='scale_disagreement':reads[-1]['text']='Uncooperative TESTS Emissary'
            if case=='attitude':
                for r in reads:r['text']='Friendly TEST Emissary'
            if case=='nation':
                for r in reads:r['text']='Uncooperative OTHER Emissary'
            if case=='body':original[3]['text']='wonders of TEST. We permit all scribes'
            if case=='choice':original.append(prepared('Cancel',500,454,40,13))
            if case=='geometry':reads[-1]['center'][1]+=20
            before=deepcopy(original)
            with mock.patch('civ2.observe._crop_text',side_effect=[[r]for r in reads]):
                _recover_gape_title(Image.new('RGB',(640,480)),original,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(original[0]['text'],a['text']);self.assertEqual(original[1:],before[1:])
                self.assertEqual(len(original[0]['provenance']),5)
            else:self.assertEqual(original,before,case)

    def test_actual_complete_gape_preserves_observed_heading_nation(self):
        p=Path('runs/attempt-011/screens/ui-0003189.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'GAPE')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        row=next(r for r in o['lines'] if r['text'].endswith(' Emissary'))
        self.assertEqual(row['text'],'Uncooperative Zobe Emissary')
        self.assertEqual(row['provenance'][0]['text'],'Uncooperative Zube Emisoury')
        self.assertEqual([r['preprocessing'] for r in row['provenance'][-4:]],['gape_title_rgb2','gape_title_gray2','gape_title_rgb4','gape_title_gray4'])
