"""Synthetic TEST event artwork; actual private discovery image optional."""
import copy
from pathlib import Path
import unittest
from PIL import Image
from civ2.notice_icons import annotate_notice_icons
from civ2.dialogs import classify_dialog
from tests.test_dialogs import row,observation

SOURCE='''@CIVADVANCE
@title=Civilization Advance
@width=320
%STRING0 wise men discover the secret of %STRING2.
'''


def fixture():
    im=Image.new('RGB',(640,480),(90,90,90));left,top=125,177
    for yy in range(40):
        for xx in range(72):
            if xx<2 or yy<2 or xx>=70 or yy>=38:color=(0,0,0)
            elif xx<4 or yy<4 or xx>=68 or yy>=36:color=(190,150,44)
            else:color=(200,0,0)
            im.putpixel((left+xx,top+yy),color)
    rows=[row('Civilization Advance',x=320,y=160,w=160),row('TEST wise men discover the secret of TEST Writing.',x=350,y=188,w=300),
          row('TƯ',x=164,y=198,w=28,h=24),row('OK',x=320,y=245,w=24)]
    annotate_notice_icons(im,rows,'a'*64)
    return im,rows

class NoticeIconTests(unittest.TestCase):
    def test_reviewed_discovery_title_variant_still_requires_complete_body(self):
        _,rows=fixture();rows[0]['text']='Cinlization Adsance'
        r=classify_dialog(observation(*rows),game_text=SOURCE)
        self.assertTrue(r['supported'],r)
        self.assertEqual(r['title'],'Cinlization Adsance')
        self.assertEqual(r['evidence']['observed_title'],'Cinlization Adsance')
        self.assertEqual(r['evidence']['title_match'],'reviewed OCR alias')
        rows[1]['text']='TEST unknown news.'
        self.assertFalse(classify_dialog(observation(*rows),game_text=SOURCE)['supported'])

    def test_optional_original_ceremonial_burial_discovery(self):
        p=Path('runs/attempt-011/screens/ui-0000735.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private discovery frame unavailable')
        from civ2.observe import recognize
        from civ2.run import game_text
        r=classify_dialog(recognize(p),game_text=game_text())
        self.assertTrue(r['supported'],r)
        self.assertEqual(r['resource_tag'],'CIVADVANCE')
        self.assertEqual(r['evidence']['observed_body'],'Roman wise men discover the secret of\nCeremonial Burial.')
        self.assertEqual([o['text'] for o in r['options']],['OK'])

    def test_exact_border_artwork_cannot_become_a_control_or_game_fact(self):
        _,rows=fixture();r=classify_dialog(observation(*rows),game_text=SOURCE)
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'CIVADVANCE')
        self.assertEqual(r['mechanical_action'],'acknowledge_information')
        self.assertEqual([o['text'] for o in r['options']],['OK'])
        self.assertEqual(r['evidence']['decorative_icon']['ignored_raw_ocr'],'TƯ')
    def test_modified_border_hash_incomplete_body_or_added_choice_reject(self):
        for case in ('border','hash','body','choice','tag'):
            im,rows=fixture()
            if case=='border':
                im.putpixel((125,177),(1,0,0));rows[2].pop('native_notice_icon');annotate_notice_icons(im,rows,'a'*64)
            elif case=='hash':rows[2]['native_notice_icon']['source_sha256']='b'*64
            elif case=='body':rows[1]['text']='TEST incomplete notice.'
            elif case=='choice':rows.append(row('Pay TEST gold.',x=300,y=218,w=100))
            source=SOURCE.replace('CIVADVANCE','TESTUNKNOWN') if case=='tag' else SOURCE
            self.assertFalse(classify_dialog(observation(*rows),game_text=source)['supported'],case)
    def test_optional_original_discovery_icon(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-004/screens/ui-0000877.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private discovery frame unavailable')
        from civ2.observe import recognize
        from civ2.run import game_text
        o=recognize(p);r=classify_dialog(o,game_text=game_text())
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'CIVADVANCE')
        icon=next(x for x in o['lines'] if x.get('native_notice_icon'))
        self.assertEqual(icon['text'],'TƯ');self.assertEqual(icon['native_notice_icon']['frame'],[125,217,72,40])

if __name__=='__main__':unittest.main()
