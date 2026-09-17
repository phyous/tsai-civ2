"""Whole-row proof must resolve the word without altering treaty terms."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import gdi_treaty as g
from tests.test_gdi_text import TestAtlas
from tests.test_herald import prepared
from tests.test_treaty_herald import SOURCE


def fixture():
    atlas=TestAtlas();text='goodwill between the people of the TEST and'
    mask=atlas.render(text);mask=mask.crop(mask.getbbox())
    image=Image.new('RGB',(640,480),(195,195,195));image.paste((48,48,48),(314,385),mask)
    rows=[prepared('TEST Emissary',365,340,140,18),
        prepared('"We affirm this treaty of eternal friendship and',312,362,316,18),
        prepared(text.replace('between','hetween'),314,385,mask.width,mask.height),
        prepared('TEST civilizations. We shall withdraw our',314,404,284,16),
        prepared('forces from your territory at once."',312,424,238,16),prepared('OK',425,454,24,13)]
    return image,rows,atlas


class TreatyGdiTests(unittest.TestCase):
    def test_exact_test_mask_preserves_words_and_full_original_acknowledgement(self):
        image,rows,atlas=fixture();before=deepcopy(rows);e={'passes':[]}
        self.assertTrue(g.recover_treaty_between(image,rows,e,atlas=atlas,game_text=SOURCE))
        for i in (0,1,3,4,5):self.assertEqual(rows[i],before[i])
        self.assertEqual(rows[2]['text'],before[2]['text'].replace('hetween','between'))
        self.assertEqual(rows[2]['provenance'][:-1],before[2]['provenance'])
        self.assertEqual(rows[2]['provenance'][-1]['extra_pixels'],0)
        from civ2.dialogs import classify_dialog
        d=classify_dialog({'width':640,'height':480,'sha256':'a'*64,'lines':rows},game_text=SOURCE)
        self.assertTrue(d['supported']);self.assertFalse(d['requires_model'])
        self.assertEqual(d['mechanical_action'],'acknowledge_information')

    def test_pixel_damage_or_altered_other_words_never_recover(self):
        for mode in ('extra','missing','colored','black','country','terms','extra_row','extra_choice','source','atlas'):
            image,rows,atlas=fixture();source=SOURCE
            if mode=='extra':image.putpixel((633,386),(48,48,48))
            elif mode=='missing':
                p=next((x,y) for y in range(380,403) for x in range(302,637) if image.getpixel((x,y))==(48,48,48))
                image.putpixel(p,(195,195,195))
            elif mode=='colored':image.putpixel((633,386),(255,0,0))
            elif mode=='black':image.putpixel((633,386),(0,0,0))
            elif mode=='country':rows[2]['text']=rows[2]['text'].replace('TEST','OTHER')
            elif mode=='terms':rows[3]['text']='TEST civilizations. We shall attack your'
            elif mode=='extra_row':rows.insert(3,prepared('Pay 100 TEST gold',314,398,160,10))
            elif mode=='extra_choice':rows.append(prepared('No',500,454,24,13))
            elif mode=='source':source=source.replace('withdraw','attack')
            before=deepcopy(rows)
            with self.subTest(mode=mode),patch.object(g,'load_atlas',return_value=None):
                self.assertFalse(g.recover_treaty_between(image,rows,atlas=None if mode=='atlas' else atlas,game_text=source))
                self.assertEqual(rows,before)

    def test_optional_actual_011_whole_row_matches_original_atlas(self):
        path=Path('runs/attempt-011/screens/ui-0001218.png')
        if not path.exists() or g.load_atlas() is None:self.skipTest('Private treaty or atlas absent')
        from civ2.observe import recognize
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        original=path.read_bytes();o=recognize(path)
        self.assertEqual(o['sha256'],hashlib.sha256(original).hexdigest())
        row=next(r for r in o['lines'] if r['text'].startswith('goodwill'))
        self.assertEqual(row['text'],'goodwill between the people of the Spanish and')
        self.assertTrue(any('hetween' in p['text'] for p in row['provenance']))
        p=row['provenance'][-1];self.assertEqual(p['preprocessing'],'original_gdi_treaty_exact')
        self.assertEqual(p['foreground_rgb'],[48,48,48]);self.assertEqual(p['extra_pixels'],0)
        self.assertEqual(p['missing_pixels'],0);self.assertEqual(row['bounds'],[314,385,311,14])
        d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'TREATY')
        self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertEqual(path.read_bytes(),original)


if __name__=='__main__':unittest.main()
