"""Source-pixel marker recovery must preserve rather than invent semantic values."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from civ2.observe import recognize,_recover_treasury_marker
from civ2.dialogs import classify_dialog


class MarkerTests(unittest.TestCase):
    def test_city_identity_does_not_require_ocr_treasury_spelling(self):
        from civ2.run import observed_city_identity
        p=Path('runs/attempt-008/screens/ui-0000022.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private native fixture unavailable')
        o=recognize(p);d=classify_dialog(o)
        self.assertEqual(d['kind'],'city_screen')
        self.assertEqual(observed_city_identity(d),('Rome','4000BC'))
        self.assertIn('Treasory',d['title'])

    def test_actual_debug_save_caption_retains_independent_reads(self):
        from civ2.ui import saved_notice
        p=Path('runs/attempt-004/screens/ui-0001027.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private native fixture unavailable')
        o=recognize(p)
        self.assertTrue(saved_notice(o))
        row=next(r for r in o['lines'] if r['text'].startswith('Game sa'))
        self.assertIn('Gaue saved!!',[r['text'] for r in row['provenance']])
        self.assertGreaterEqual(sum(r['text']==row['text'] for r in row['provenance']),2)

    def test_actual_treasury_marker_retains_raw_and_two_agreeing_reads(self):
        p=Path('runs/attempt-005/screens/ui-0001418.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private native fixture unavailable')
        data=p.read_bytes();o=recognize(p)
        r=next(r for r in o['lines'] if r['text']=='I11 Gold 4.0.6')
        texts=[x['text'] for x in r['provenance']]
        self.assertIn('BT Cold 4.0.6',texts);self.assertGreaterEqual(texts.count(r['text']),2)
        self.assertNotIn('gold_value',r);self.assertEqual(data,p.read_bytes())

    def test_actual_diplomacy_intro_is_source_bound_and_leaves_all_choices_to_model(self):
        p=Path('runs/attempt-006/screens/ui-0001007.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private native fixture unavailable')
        from civ2.run import game_text
        data=p.read_bytes();o=recognize(p);r=classify_dialog(o,game_text=game_text())
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'DIPLOMACY')
        self.assertTrue(r['requires_model']);self.assertIsNone(r['mechanical_action'])
        self.assertEqual(len(r['options']),5)
        intro=next(x for x in o['lines'] if x['text']=='You respond: "We..."')
        self.assertEqual(intro['provenance'][0]['text'],'You respond: "We.')
        self.assertEqual(sum(x['text']==intro['text'] for x in intro['provenance']),2)
        self.assertEqual(data,p.read_bytes())

    def test_joined_amount_marker_still_requires_two_actual_agreeing_reads(self):
        original=dict(text='131Cold 4.0.6',bounds=[474,230,80,10],center=[514,235],confidence=1.,
                      provenance=[{'text':'131Cold 4.0.6','preprocessing':'native'}])
        for mode in ('valid','disagree','word'):
            rows=[deepcopy(original)];a={**deepcopy(original),'text':'137 Gold 4.0.6'};b=deepcopy(a)
            if mode=='disagree':b['text']='138 Gold 4.0.6'
            elif mode=='word':rows[0]['text']='Scold 4.0.6'
            before=deepcopy(rows)
            with patch('civ2.observe._crop_text',side_effect=[[a],[b]]) as crop:
                _recover_treasury_marker(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            if mode=='valid':self.assertEqual(rows[0]['text'],'137 Gold 4.0.6')
            else:self.assertEqual(rows,before)
            if mode=='word':crop.assert_not_called()

    def test_actual_joined_treasury_is_only_a_layout_marker(self):
        p=Path('runs/attempt-011/screens/ui-0001689.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame absent')
        o=recognize(p);r=next(r for r in o['lines'] if r['text']=='137 Gold 4.0.6')
        self.assertIn('131Cold 4.0.6',[x['text'] for x in r['provenance']])
        self.assertGreaterEqual(sum(x['text']==r['text'] for x in r['provenance']),2)
        self.assertNotIn('gold_value',r)

    def test_disagreeing_wrong_location_and_non_marker_crops_do_not_replace(self):
        original=dict(text='BT Cold 4.0.6',bounds=[474,230,80,10],center=[514,235],confidence=1.,
                      provenance=[{'text':'BT Cold 4.0.6','preprocessing':'native'}])
        for mode in ('disagree','location','not_marker'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                rows=[deepcopy(original)];a={**deepcopy(original),'text':'I11 Gold 4.0.6'};b=deepcopy(a)
                if mode=='disagree':b['text']='112 Gold 4.0.6'
                elif mode=='location':b['bounds'][0]-=90;b['center'][0]-=90
                else:a['text']=b['text']='Choose Gold'
                with patch('civ2.observe._crop_text',side_effect=[[a],[b]]):
                    _recover_treasury_marker(Image.new('RGB',(640,480)),rows,'unused',directory,{'passes':[]})
                self.assertEqual(rows,[original])


if __name__=='__main__':unittest.main()
