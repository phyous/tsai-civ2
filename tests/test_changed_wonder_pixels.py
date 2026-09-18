from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class ChangedWonderPixels(unittest.TestCase):
    def test_colored_split_requires_four_whole_reads_and_original_prose(self):
        for mode in ('valid','gray','weak','disagree','other_target','question','other_body','extra','overwide'):
            rows=[prepared('Travellers Report',269,196,102,16),
                  prepared('The Zulus have changed projects from Colossus',200,218,320,18),
                  prepared("Bilmto Marco Polo's Emhassyl",156,236,220,22),prepared('OK',308,270,24,16)]
            image=Image.new('RGB',(640,480),(190,)*3)
            if mode!='gray':image.paste((255,0,0),(156,236,200,258))
            if mode=='other_body':rows[1]['text']='The Zulus have destroyed Colossus'
            if mode=='extra':rows.append(prepared('Yes',250,270,24,16))
            if mode=='overwide':rows[2]['bounds'][0]=120;rows[2]['bounds'][2]=256;rows[2]['center'][0]=248
            before=deepcopy(rows)
            def crop(image,row,name,*args,**kwargs):
                r=deepcopy(row);r['text']="to Marco Polo's Embassy!"
                if mode=='weak':r['confidence']=.5
                if mode=='disagree' and kwargs.get('scale')==3:r['text']="to Marco Polo's Emhassy!"
                if mode=='other_target':r['text']='to Pyramids!'
                if mode=='question':r['text']="to Marco Polo's Embassy?"
                return [r]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_changed_wonder_tail(image,rows,None,None,{'source_image_sha256':'a'*64})
            if mode=='valid':
                self.assertEqual(rows[2]['text'],"to Marco Polo's Embassy!")
                self.assertEqual(rows[2]['provenance'][0]['text'],"Bilmto Marco Polo's Emhassyl")
                self.assertEqual(len(rows[2]['provenance']),5)
                self.assertEqual(rows[2]['wonder_art_split']['art_bounds'],[156,236,44,22])
                self.assertEqual(rows[:2],before[:2])
            else:self.assertEqual(rows,before,mode)

    def test_actual_switch_wonder_is_only_a_complete_source_information_notice(self):
        path=Path('runs/attempt-011/screens/ui-0003586.png')
        if not path.exists():self.skipTest('Private original calibration unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(path);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'SWITCHWONDER')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        tail=next(r for r in o['lines'] if r['text']=="to Marco Polo's Embassy!")
        self.assertEqual(tail['provenance'][0]['text'],"Bilmto Marco Polo's Emhassyl")
        self.assertEqual(tail['wonder_art_split']['chromatic_pixels'],569)
        self.assertEqual(tail['wonder_art_split']['source_image_sha256'],o['sha256'])


if __name__=='__main__':unittest.main()
