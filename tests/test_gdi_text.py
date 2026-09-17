"""Private original assets are optional; synthetic TEST pixels are independent."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from zipfile import BadZipFile
from PIL import Image,ImageDraw,ImageFont
from civ2 import gdi_text as g
from civ2.observe import _prepare_rows
from tests.test_herald import prepared

SOURCE='''@EXCHANGE0
@width=320
@title=%STRING0 Emissary
"We note that your primitive civilization has not even discovered %STRING1.  We desire the secret of %STRING3.  Do you care to exchange knowledge with us?"

"No. We do not need %STRING1."
"Okay, let's exchange knowledge."
'''
LABELS='"Will you accept %STRING4 instead?"'
OPTIONS=['"No. We do not need TEST Masonry."','"Okay, let\'s exchange knowledge."','"Will you accept TEST Writing instead?"']


class TestAtlas:
    """Pillow's synthetic font, not original private glyphs or copied output."""
    def render(self,text):
        image=Image.new('L',(min(640,len(text)*9+8),40))
        ImageDraw.Draw(image).text((5,8),text,font=ImageFont.load_default(size=10),fill=255,anchor='lt')
        return image.point(lambda value:255 if value>=128 else 0)


def fixture():
    image=Image.new('RGB',(640,480),(195,195,195));atlas=TestAtlas()
    for y in range(360,442):
        image.putpixel((637,y),(65,65,65));image.putpixel((638,y),(65,65,65));image.putpixel((639,y),(0,0,0))
    rows=[prepared('TEST Emissary',394,260,150,16),
      prepared('"We note that your primitive civilization has not',308,284,322,20),
      prepared('even discovered TEST Masonry. We desire the',308,306,300,16),
      prepared('secret of TEST Burial. Do you care to',308,326,292,16),
      prepared('exchange knowledge with us?"',308,344,208,16)]
    for i,text in enumerate(OPTIONS):
        cx,cy=302,377+i*25
        for dx,dy in g.WHITE_RING:image.putpixel((cx+dx,cy+dy),(255,255,255))
        for dx,dy in g.BLACK_RING:image.putpixel((cx+dx,cy+dy),(0,0,0))
        image.paste((0,0,0),(cx+17,cy-13),atlas.render(text))
        raw='O "\''+text[1:] if i==1 else 'O '+text
        rows.append(prepared(raw,294,cy-9,290,18))
    # Independently create a native dotted focus rectangle, larger than text.
    for x in range(318,629):
        for y in (368,387):
            if (x+y)%2:image.putpixel((x,y),(0,0,0))
    for y in range(369,387):
        for x in (318,628):
            if (x+y)%2:image.putpixel((x,y),(0,0,0))
    rows.append(prepared('OK',456,454,26,16))
    return image,rows,atlas


def recover(image,rows,atlas,source=SOURCE,labels=LABELS,evidence=None):
    return g.recover_quoted_herald(image,rows,evidence=evidence,atlas=atlas,game_text=source,labels_text=labels)


class ExactGdiTests(unittest.TestCase):
    def test_all_choices_remain_model_required_and_raw_readings_survive(self):
        image,rows,atlas=fixture();before=deepcopy(rows);e={'passes':[]}
        self.assertTrue(recover(image,rows,atlas,evidence=e))
        self.assertEqual([r['text'] for r in rows[-4:-1]],OPTIONS)
        self.assertEqual(rows[-3]['provenance'][0],before[-3]['provenance'][0])
        from civ2.dialogs import classify_dialog
        d=classify_dialog({'width':640,'height':480,'sha256':'a'*64,'lines':rows},game_text=SOURCE,labels_text=LABELS)
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action']);self.assertEqual(len(d['options']),3)
        self.assertEqual(e['gdi_exact'][0]['complete_options'],3)

    def test_any_single_pixel_difference_rejects_atomically(self):
        for mode in ('missing','extra','different_color','focus','radio','frame','colored_extra','gray_extra'):
            with self.subTest(mode=mode):
                image,rows,atlas=fixture();before=deepcopy(rows)
                if mode=='missing':
                    mask=atlas.render(OPTIONS[1]);p=next((x,y) for y in range(8,25) for x in range(mask.width) if mask.getpixel((x,y))==255)
                    image.putpixel((319+p[0],389+p[1]),(195,195,195))
                elif mode=='extra':image.putpixel((620,403),(0,0,0))
                elif mode=='different_color':
                    mask=atlas.render(OPTIONS[1]);p=next((x,y) for y in range(8,25) for x in range(mask.width) if mask.getpixel((x,y))==255)
                    image.putpixel((319+p[0],389+p[1]),(48,48,48))
                elif mode=='colored_extra':image.putpixel((620,403),(255,0,0))
                elif mode=='gray_extra':image.putpixel((620,403),(48,48,48))
                elif mode=='focus':image.putpixel((319,368),(195,195,195))
                elif mode=='radio':image.putpixel((300,394),(195,195,195))
                else:image.putpixel((639,400),(195,195,195))
                self.assertFalse(recover(image,rows,atlas));self.assertEqual(rows,before)

    def test_missing_duplicate_extra_or_changed_choice_is_not_recovered(self):
        for mode in ('missing','duplicate','extra_row','word','number','body','source','labels','button','conflict','fourth_radio'):
            with self.subTest(mode=mode):
                image,rows,atlas=fixture();source=SOURCE;labels=LABELS;e={'passes':[]}
                if mode=='missing':rows.pop(-2)
                elif mode=='duplicate':rows.insert(-1,deepcopy(rows[-2]))
                elif mode=='extra_row':rows.insert(-1,prepared('Hidden TEST alternative',330,411,200,14))
                elif mode=='word':rows[-3]['text']=rows[-3]['text'].replace('knowledge','gold')
                elif mode=='number':rows[-2]['text']=rows[-2]['text'].replace('TEST Writing','100 TEST Writing')
                elif mode=='body':rows[1]['text']='Pay 100 TEST gold or face war.'
                elif mode=='source':source=source.replace('primitive civilization','peaceful civilization')
                elif mode=='labels':labels=LABELS+'\n'+LABELS
                elif mode=='button':rows.append(prepared('Cancel',550,450,50,16))
                elif mode=='conflict':e['conflicts']=['uncertain original row']
                else:
                    for dx,dy in g.WHITE_RING:image.putpixel((302+dx,352+dy),(255,255,255))
                    for dx,dy in g.BLACK_RING:image.putpixel((302+dx,352+dy),(0,0,0))
                before=deepcopy(rows);self.assertFalse(recover(image,rows,atlas,source,labels,e));self.assertEqual(rows,before)

    def test_missing_corrupt_private_assets_disable_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(g.load_atlas(directory))
            Path(directory,'times-bold-16.bmp').write_bytes(b'x'*15422)
            Path(directory,'times-bold-16.tsv').write_bytes(b'y'*2298)
            self.assertIsNone(g.load_atlas(directory))
        image,rows,atlas=fixture();before=deepcopy(rows)
        with patch.object(g,'_sources',side_effect=BadZipFile('TEST corruption')):
            self.assertFalse(g.recover_quoted_herald(image,rows,atlas=atlas))
        self.assertEqual(rows,before)

    def test_optional_actual_native_quote_failures_match_all_pixels(self):
        root=Path(__file__).resolve().parents[1]
        atlas=g.load_atlas()
        if atlas is None or not(root/'.runtime/ocr').exists():self.skipTest('Private original atlas/OCR absent')
        from civ2.observe import recognize
        for number,count,tag in [(521,3,'EXCHANGE0'),(547,3,'EXCHANGE0'),(563,2,'PROPOSEPEACE')]:
            with self.subTest(number=number):
                path=root/f'runs/attempt-010/screens/ui-{number:07}.png'
                if not path.exists():self.skipTest('Private original herald screenshot absent')
                observation=recognize(path);raw=[]
                for row in observation['lines']:
                    p=row['provenance'][0];x,y,w,h=p['normalized_bounds']
                    raw.append(dict(text=p['text'],confidence=p['confidence'],x=x,y=y,width=w,height=h))
                rows=_prepare_rows(raw,640,480,'native');e={'passes':[]};image=Image.open(path)
                self.assertTrue(g.recover_quoted_herald(image,rows,evidence=e))
                self.assertEqual(e['gdi_exact'][0]['resource_tag'],tag);self.assertEqual(e['gdi_exact'][0]['complete_options'],count)
                recovered=[r for r in rows if r['provenance'][-1]['preprocessing']=='original_gdi_exact']
                self.assertEqual(len(recovered),count)
                for row in recovered:
                    self.assertEqual(row['provenance'][-1]['extra_pixels'],0);self.assertEqual(row['provenance'][-1]['missing_pixels'],0)
                # Unknown ink after the rendered words must not be cropped away.
                image=image.copy();image.putpixel((633,e['gdi_exact'][0]['radio_centers'][-1][1]),(0,0,0))
                original=_prepare_rows(raw,640,480,'native');before=deepcopy(original)
                self.assertFalse(g.recover_quoted_herald(image,original));self.assertEqual(original,before)


if __name__=='__main__':unittest.main()
