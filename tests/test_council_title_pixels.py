from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.dialogs import classify_dialog
from tests.test_herald import prepared


class CouncilTitlePixels(unittest.TestCase):
    def fixture(self):
        return [prepared('The Figh Comcl A.D.1',240,14,160,18),
                prepared('The High Council of the Romans is meeting in',197,37,307,17),
                prepared('Veii. If you wish,you may take this opportunity',198,58,312,16),
                prepared('to consult your advisors and hear their views',197,78,304,16),
                prepared('on the state of your realm.',197,98,177,16),
                prepared('O Consult High Council.',206,122,172,18),
                prepared('• No thanks, too busy.',206,148,168,18),prepared('OK',308,182,24,16)]

    def test_independent_heading_reads_keep_date_and_actual_options(self):
        for case in ('valid','disagree','date','era','weak','displaced','missing_option','missing_body'):
            with self.subTest(case=case):
                rows=self.fixture();original=deepcopy(rows)
                a=prepared('The Fligh Cooncl: A.D. 1',242,14,157,17);b=deepcopy(a)
                if case=='disagree':b['text']='The High Council: A.D. 1'
                if case=='date':a['text']=b['text']='The Fligh Cooncl: A.D. 10'
                if case=='era':a['text']=b['text']='The Fligh Cooncl: 1 B.C.'
                if case=='weak':b['confidence']=.5
                if case=='displaced':b.update(bounds=[100,150,157,17],center=[178,158])
                if case=='missing_option':rows.pop(6)
                if case=='missing_body':rows.pop(4)
                with patch.object(observe,'_crop_text',side_effect=[[a],[b]]) as reader:
                    observe._recover_council_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
                self.assertEqual(rows[0]['text'],a['text'] if case=='valid' else original[0]['text'])
                self.assertEqual(rows[0]['provenance'][0]['text'],original[0]['text'])
                if case=='valid':self.assertEqual([r['text'] for r in rows[5:]], [r['text'] for r in original[5:]])
                if case.startswith('missing'):reader.assert_not_called()

    def test_original_first_ad_council_remains_a_two_option_model_choice(self):
        from civ2.run import game_text,labels_text
        path=Path('runs/attempt-011/screens/ui-0002495.png')
        if not path.exists():self.skipTest('Private original council frame unavailable')
        original=path.read_bytes();o=observe.recognize(path)
        d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual(d['resource_tag'],'COUNCILTIME');self.assertEqual(len(d['options']),2)
        self.assertEqual(d['title'],'The Fligh Cooncl: A.D. 1')
        row=next(r for r in o['lines'] if r['text']==d['title'])
        self.assertEqual(row['provenance'][0]['text'],'The Figh Comcl A.D.1')
        self.assertTrue({'council_title_rgb3','council_title_gray3'}<={p['preprocessing'] for p in row['provenance']})
        self.assertEqual(path.read_bytes(),original)

    def test_original_later_council_missing_colon_needs_its_actual_paired_title(self):
        from civ2.run import game_text,labels_text
        path=Path('runs/attempt-011/screens/ui-0003601.png')
        if not path.exists():self.skipTest('Private original council frame unavailable')
        o=observe.recognize(path);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['resource_tag'],'COUNCILTIME');self.assertIsNone(d['mechanical_action'])
        self.assertEqual(d['title'],'The High Coocil A.D. 1000')
        self.assertEqual([r['text'] for r in d['options']],['Consult High Council.','• No thanks, too busy.'])
        row=next(r for r in o['lines'] if r['text']==d['title'])
        self.assertEqual(row['provenance'][0]['text'],'The Fligh Comcl A D. 1000')
        self.assertEqual(row['council_title_recovery']['date_parts'],['1000','AD'])
        for mode in ('missing_proof','stale_hash','missing_gray','wrong_date','missing_option','missing_body'):
            wrong=deepcopy(o);title=next(r for r in wrong['lines'] if r['text']==d['title'])
            if mode=='missing_proof':title.pop('council_title_recovery')
            elif mode=='stale_hash':title['council_title_recovery']['source_image_sha256']='c'*64
            elif mode=='missing_gray':title['provenance']=[p for p in title['provenance'] if p['preprocessing']!='council_title_gray3']
            elif mode=='wrong_date':title['council_title_recovery']['date_parts']=['1001','AD']
            elif mode=='missing_option':wrong['lines']=[r for r in wrong['lines'] if r['text']!='Consult High Council.']
            else:wrong['lines']=[r for r in wrong['lines'] if r['text']!='their views on the state of your realm.']
            with self.subTest(mode=mode):self.assertFalse(classify_dialog(wrong,game_text=game_text(),labels_text=labels_text())['supported'])


if __name__=='__main__':unittest.main()
