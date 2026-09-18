from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import promotion_notice as p
from civ2.dialogs import classify_dialog, dialog_resources
from civ2.native_events import classify_information, COMBAT_NOTICE_RESOURCES
from civ2.gdi_text import _canonical
from tests.test_herald import prepared

SOURCE = dict(tag='PROMOTED', title='Defense Minister', width=300,
    body='For valor in combat, our %STRING0 unit has been promoted to Veteran status.',
    options=[],buttons=[],listbox=False)
GAME = '@PROMOTED\n@width=300\n@title=Defense Minister\n'+SOURCE['body']+'\n'
BODY = ['For valor in combat, our TEST unit has', 'been promoted to Veteran status.']


def fixture():
    rows = [prepared('Detense Mfinister',268,192,106,16),
            prepared(BODY[0],206,214,282,18), prepared(BODY[1],206,236,226,16),
            prepared('OK',309,274,24,13)]
    image = Image.new('RGB',(640,480),(190,190,190))
    black = [sum(1<<x for x in range(100) if (x+y)%5==0) for y in range(12)]
    gray = [sum(1<<x for x in range(100) if (x+y)%5==1) for y in range(12)]
    for y in range(12):
        for x in range(100):
            if black[y] & 1<<x: image.putpixel((270+x,194+y),(0,0,0))
            elif gray[y] & 1<<x: image.putpixel((270+x,194+y),(134,134,134))
    return image,rows,(100,12,black,gray)


class PromotionNoticeTests(unittest.TestCase):
    def test_exact_source_promotes_only_an_informational_acknowledgement(self):
        image,rows,rendered=fixture(); rows[0]['text']='Defense Minister'
        o=dict(width=640,height=480,sha256='a'*64,lines=rows);before=deepcopy(o)
        result=classify_dialog(o,game_text=GAME)
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['resource_tag'],'PROMOTED')
        self.assertEqual(result['mechanical_action'],'acknowledge_information')
        self.assertFalse(result['requires_model']);self.assertIsNone(result['outcome'])
        self.assertEqual([v['text'] for v in result['options']],['OK'])
        self.assertEqual(result['evidence']['observed_body'],'\n'.join(BODY))
        self.assertEqual(o,before)

    def test_gdi_title_preserves_all_observed_body_words_and_raw_heading(self):
        image,rows,rendered=fixture();before=deepcopy(rows)
        with patch.object(p,'_render',return_value=rendered):
            self.assertTrue(p.recover_promotion_title(image,rows,game_text=GAME))
        self.assertEqual(rows[0]['text'],'Defense Minister')
        self.assertEqual(rows[0]['provenance'][0],before[0]['provenance'][0])
        self.assertEqual(rows[1:],before[1:])
        self.assertEqual(rows[0]['provenance'][-1]['extra_black_pixels'],0)

    def test_wrong_pixels_terms_controls_and_source_abstain(self):
        for mode in ('extra_black','missing_black','missing_gray','colored','changed_body','partial_body','extra_body','cancel','extra_ok','source','missing_atlas','conflict'):
            with self.subTest(mode=mode):
                image,rows,rendered=fixture();text=GAME;e={}
                if mode=='extra_black':image.putpixel((480,196),(0,0,0))
                elif mode=='missing_black':image.putpixel((270,194),(190,190,190))
                elif mode=='missing_gray':image.putpixel((271,194),(190,190,190))
                elif mode=='colored':image.putpixel((480,196),(255,0,0))
                elif mode=='changed_body':rows[2]['text']='been defeated in combat.'
                elif mode=='partial_body':rows.pop(2)
                elif mode=='extra_body':rows.insert(2,prepared('Choose a reward.',206,230,120,12))
                elif mode=='cancel':rows[-1]['text']='Cancel'
                elif mode=='extra_ok':rows.append(deepcopy(rows[-1]))
                elif mode=='source':text=text.replace('Veteran','Elite')
                elif mode=='conflict':e['conflicts']=['TEST conflict']
                before=deepcopy(rows)
                with patch.object(p,'_render',return_value=rendered,side_effect=ValueError('TEST missing atlas') if mode=='missing_atlas' else None):
                    self.assertFalse(p.recover_promotion_title(image,rows,evidence=e,game_text=text))
                self.assertEqual(rows,before)

    def test_title_alias_is_not_admitted_without_pixel_recovery_and_source_is_pinned(self):
        from civ2.verify import PUBLIC_NOTICE_RESOURCES
        _,rows,_=fixture();o=dict(width=640,height=480,sha256='a'*64,lines=rows)
        self.assertFalse(classify_information(o,[SOURCE])['supported'])
        digest=hashlib.sha256(_canonical(SOURCE)).hexdigest()
        self.assertEqual(COMBAT_NOTICE_RESOURCES['PROMOTED'],digest)
        self.assertEqual(PUBLIC_NOTICE_RESOURCES['PROMOTED'],digest)
        self.assertEqual(dialog_resources(GAME),[SOURCE])
        rows[0]['text']='Defense Minister'
        for change in ({'options':['Promote','Refuse']},{'width':320},{'buttons':['OK','Cancel']},{'body':SOURCE['body']+' Choose a reward.'}):
            self.assertFalse(classify_information(o,[{**SOURCE,**change}])['supported'])

    def test_actual_012_complete_promotion_and_gdi_heading(self):
        path=Path('runs/attempt-012/screens/ui-0002712.png')
        if not path.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private frame/OCR absent')
        from civ2.gdi_text import load_atlas,_sources
        if load_atlas(style='regular') is None:self.skipTest('Private original regular atlas absent')
        from civ2.observe import recognize
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'3cb0eed577aee9fba4bee13be51a8b8036946f07efbee7864ed951fe25a6314e')
        original=path.read_bytes();o=recognize(path);result=classify_dialog(o,game_text=_sources()[0])
        self.assertTrue(result['supported'],result);self.assertEqual(result['resource_tag'],'PROMOTED')
        self.assertEqual(result['evidence']['observed_body'],'For valor in combat, our Warriors unit has\nbeen promoted to Veteran status.')
        title=next(r for r in o['lines'] if r['text']=='Defense Minister')
        self.assertEqual(title['provenance'][0]['text'],'Detense Mfinister')
        self.assertEqual(title['provenance'][-1]['preprocessing'],'original_gdi_promotion_title')
        self.assertEqual(title['provenance'][-1]['extra_black_pixels'],0)
        self.assertEqual([v['text'] for v in result['options']],['OK'])
        self.assertFalse(result['requires_model']);self.assertIsNone(result['outcome'])
        self.assertEqual(path.read_bytes(),original)


class SchismNoticeTests(unittest.TestCase):
    SOURCE=dict(tag='SCHISM',title='Defense Minister',width=400,
        body='The %STRING0 empire is swept by Civil War triggered by the fall of their capital! When the dust settles the empire has been split into loyal (%STRING0) and rebel (%STRING1) factions.',
        options=[],buttons=[],listbox=False)

    def test_complete_schism_repeats_observed_loyal_nation_without_inferred_effects(self):
        from tests.test_native_events import notice
        from civ2.verify import PUBLIC_NOTICE_RESOURCES
        body=['The TEST empire is swept by Civil War triggered',
              'by the fall of their capital! When the dust settles the empire has been',
              'split into loyal (TEST) and rebel (OTHER) factions.']
        o=notice(*body,title='Defense Bfinister')
        result=classify_information(o,[self.SOURCE])
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['resource_tag'],'SCHISM')
        self.assertEqual(result['mechanical_action'],'acknowledge_information')
        self.assertEqual([v['text'] for v in result['options']],['OK'])
        self.assertFalse(result['requires_model'])
        digest=hashlib.sha256(_canonical(self.SOURCE)).hexdigest()
        self.assertEqual(COMBAT_NOTICE_RESOURCES['SCHISM'],digest)
        self.assertEqual(PUBLIC_NOTICE_RESOURCES['SCHISM'],digest)
        for mode in ('loyal','partial','period','option','source'):
            screen=deepcopy(o);source=deepcopy(self.SOURCE)
            if mode=='loyal':screen['lines'][3]['text']=screen['lines'][3]['text'].replace('(TEST)','(DIFFERENT)')
            elif mode=='partial':screen['lines'].pop(2)
            elif mode=='period':screen['lines'][3]['text']=screen['lines'][3]['text'].rstrip('.')
            elif mode=='option':source['options']=['Intervene','Refuse']
            else:source['body']=source['body'].replace('capital','king')
            self.assertFalse(classify_information(screen,[source])['supported'],mode)


if __name__=='__main__':unittest.main()
