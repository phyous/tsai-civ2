from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
from civ2 import founding_frame as f
from civ2.dialogs import classify_dialog,dialog_resources
from tests.test_herald import prepared

GAME='@FOUNDED\n@title=Found New City\n@width=280\n%STRING0 Founded: %STRING1\n'


def fixture():
    image=Image.new('RGB',(640,480),(190,)*3);draw=ImageDraw.Draw(image)
    draw.rectangle((25,119,616,362),outline=(0,)*3,width=3)
    draw.line((26,120,615,120),fill=(223,)*3)
    draw.line((26,120,26,361),fill=(223,)*3)
    draw.rectangle((32,331,609,358),outline=(0,)*3,width=2)
    draw.text((309,338),'OK',fill=(0,)*3)
    rows=[prepared('Foond New City',266,128,108,16),
          prepared('TEST Founded: A.D. 840',330,152,206,14),
          prepared('2',18,236,6,12),prepared('OK',309,338,24,13)]
    observation=dict(width=640,height=480,sha256='a'*64,lines=rows)
    return image,observation


def annotate(image,o):
    border=f._sha(b''.join(image.crop(b).tobytes() for b in f.BORDER_REGIONS))
    button=f._sha(image.crop(f.BUTTON).tobytes())
    return patch.multiple(f,BORDER_SHA256=border,BUTTON_SHA256=button)


class IllustratedFoundingTests(unittest.TestCase):
    def test_whole_exterior_row_is_preserved_but_not_a_modal_choice(self):
        image,o=fixture();before=deepcopy(o)
        with annotate(image,o):
            self.assertTrue(f.annotate_founding_frame(image,o['lines'],o['sha256']))
            annotated=deepcopy(o);d=classify_dialog(o,game_text=GAME)
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'FOUNDED')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertEqual([r['text'] for r in d['options']],['OK'])
        self.assertEqual(d['founded_city']['name'],'TEST');self.assertEqual(d['founded_city']['year_text'],'A.D. 840')
        self.assertIn('\n2\n',d['visible_text'])
        self.assertEqual(o['lines'][1:],before['lines'][1:]);self.assertEqual(o,annotated)
        proof=d['evidence']['illustrated_founding_frame']
        self.assertEqual(proof['excluded_exterior_rows'][0]['text'],'2')
        self.assertEqual(proof['source_image_sha256'],'a'*64)
        self.assertEqual(proof['source_sha256'],f.SOURCE_SHA256)

    def test_interior_crossing_touching_rows_controls_and_partial_source_stay_unknown(self):
        for mode in ('interior','crossing','touching','inside_extra','cancel','missing_body','bad_date','missing_ok','source','no_source','two_sources','hash','border_hash','frame','title_bounds','extra_proof','low_confidence'):
            with self.subTest(mode=mode):
                image,o=fixture();game=GAME
                with annotate(image,o):
                    f.annotate_founding_frame(image,o['lines'],o['sha256'])
                    if mode in ('interior','crossing','touching'):
                        x={'interior':35,'crossing':21,'touching':19}[mode]
                        o['lines'][2]=prepared('2',x,236,6,12)
                    elif mode=='inside_extra':o['lines'].append(prepared('Abandon city?',340,220,110,14))
                    elif mode=='cancel':o['lines'].append(prepared('Cancel',390,338,45,13))
                    elif mode=='missing_body':o['lines'].pop(1)
                    elif mode=='bad_date':o['lines'][1]['text']='TEST Founded: A.D. many'
                    elif mode=='missing_ok':o['lines'].pop()
                    elif mode=='source':game=GAME.replace('280','300')
                    elif mode=='no_source':game=None
                    elif mode=='two_sources':
                        title=o['lines'][0];title['source_line']=0
                        self.assertIsNone(f.exterior_body(o,title,o['lines'][1:3],[o['lines'][3]],dialog_resources(GAME)*2))
                        continue
                    elif mode=='hash':o['sha256']='b'*64
                    elif mode=='border_hash':o['lines'][0]['illustrated_founding_frame']['border_rgb_sha256']='c'*64
                    elif mode=='frame':o['lines'][0]['illustrated_founding_frame']['frame'][0]+=1
                    elif mode=='title_bounds':o['lines'][0]['bounds'][0]+=1
                    elif mode=='extra_proof':o['lines'][0]['illustrated_founding_frame']['extra']='TEST'
                    else:o['lines'][1]['confidence']=.4
                    self.assertFalse(classify_dialog(o,game_text=game)['supported'],mode)

    def test_annotation_needs_the_entire_original_frame_and_button(self):
        for mode in ('border','button','title','extra_ok','source_hash','shift'):
            image,o=fixture()
            with annotate(image,o):
                if mode=='border':image.putpixel((25,240),(190,)*3)
                elif mode=='button':image.putpixel((400,332),(255,0,0))
                elif mode=='title':o['lines'][0]['bounds'][1]+=5
                elif mode=='extra_ok':o['lines'].append(deepcopy(o['lines'][-1]))
                elif mode=='source_hash':o['sha256']='not a PNG hash'
                else:image=image.transform(image.size,Image.Transform.AFFINE,(1,0,1,0,1,0))
                before=deepcopy(o)
                self.assertFalse(f.annotate_founding_frame(image,o['lines'],o['sha256']),mode)
                self.assertEqual(o,before)

    def test_standard_centered_path_still_requires_its_entire_body(self):
        from tests.test_dialogs import row,observation
        o=observation(row('Found New City',y=90),row('TEST Founded: 4000 B.C.',y=140),row('OK',y=210,w=25))
        self.assertTrue(classify_dialog(o)['supported'])
        o['lines'].append(row('Extra text',y=165))
        self.assertFalse(classify_dialog(o)['supported'])

    def test_actual_3523_keeps_map_label_and_source_name_date(self):
        path=Path('runs/attempt-010/screens/ui-0003523.png')
        if not path.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame/OCR absent')
        from civ2.observe import recognize
        from civ2.run import game_text
        original=path.read_bytes();o=recognize(path);before=deepcopy(o);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'FOUNDED')
        self.assertEqual(d['founded_city']['name'],'Brundisium')
        self.assertEqual(d['founded_city']['year_text'],'A.D. 840')
        self.assertEqual(d['mechanical_action'],'acknowledge_information')
        proof=d['evidence']['illustrated_founding_frame']
        self.assertEqual(proof['source_image_sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(proof['excluded_exterior_rows'][0]['bounds'],[18,236,6,12])
        self.assertEqual(proof['excluded_exterior_rows'][0]['text'],'2')
        self.assertEqual(o,before);self.assertEqual(path.read_bytes(),original)


if __name__=='__main__':unittest.main()
