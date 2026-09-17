"""Synthetic TEST footer reads; private original frame is optional."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_observe import broken_status


class FooterPixelsTests(unittest.TestCase):
    def test_padded_masks_need_both_exact_pairs_at_matching_geometry(self):
        raw=[dict(text='End of Turn',confidence=1,x=10/174,y=11/44,width=64/174,height=10/44),
             dict(text='(Press ENTER)',confidence=1,x=13/174,y=24/44,width=76/174,height=10/44)]
        for case in ('good','different','weak','extra','shifted'):
            rows=observe._prepare_rows(broken_status(),640,480,'native')
            second=copy.deepcopy(raw)
            if case=='different':second[1]['text']='(Press SPACE)'
            if case=='weak':second[1]['confidence']=.4
            if case=='extra':second.append(dict(raw[0],text='TEST extra'))
            if case=='shifted':second[0]['x']=.6
            with tempfile.TemporaryDirectory() as d,patch.object(observe,'_run_ocr',side_effect=[raw,second]):
                observe._recover_expanded_status(Image.new('RGB',(640,480),'white'),rows,None,d,{'passes':[],'conflicts':[]})
            self.assertEqual([r['text'] for r in rows],list(observe.STATUS_PHRASES) if case=='good'
                             else ['Endofhum','(Press KHEERO'],case)
            if case=='good':
                self.assertEqual(rows[0]['bounds'],[476,447,64,10])
                self.assertEqual([p['preprocessing'] for p in rows[0]['provenance']],
                    ['native','status_padded_white230_3x','status_padded_white240_3x'])
                self.assertEqual(rows[0]['provenance'][1]['crop'],[466,436,640,480])

    def test_no_bright_glyphs_means_no_invented_footer(self):
        rows=observe._prepare_rows(broken_status(),640,480,'native')
        with patch.object(observe,'_run_ocr') as ocr:
            observe._recover_expanded_status(Image.new('RGB',(640,480),'gray'),rows,None,None,{'passes':[]})
        ocr.assert_not_called()

    def test_optional_original_viewing_pieces_footer(self):
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-005/screens/ui-0001525.png'
        if not path.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original footer frame unavailable')
        data=path.read_bytes();o=observe.recognize(path)
        rows=[next(r for r in o['lines'] if r['text']==phrase) for phrase in observe.STATUS_PHRASES]
        self.assertEqual(rows[0]['provenance'][0]['text'],'EndofTum')
        self.assertEqual(rows[1]['provenance'][0]['text'],'(Press KHETER))')
        for row in rows:
            self.assertTrue({'status_padded_white230_3x','status_padded_white240_3x'}
                            <={p['preprocessing'] for p in row['provenance']})
        self.assertEqual(path.read_bytes(),data)


if __name__=='__main__':unittest.main()
