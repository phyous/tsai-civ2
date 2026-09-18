from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import gdi_dates as d
from tests.test_herald import prepared


def rendered(text):
    # Independent finite fake font makes public guard tests asset-free.
    w,h=(44,15) if text=='City of' else (70,14)
    seed=int.from_bytes(hashlib.sha256(text.encode()).digest(),'big')
    black=[1|(1<<(w-1))]+[sum(1<<x for x in range(1,w-1) if (seed>>(x%251))&1 and (x+y)%3==0) for y in range(1,h)]
    gray=[sum(1<<x for x in range(1,w-1) if not black[y]&(1<<x) and (x+y)%5==0) for y in range(h)]
    return w,h,black,gray


def paint(image,text,x,y):
    w,h,black,gray=rendered(text)
    for dy in range(h):
        for dx in range(w):
            value=0 if black[dy]&(1<<dx) else 134 if gray[dy]&(1<<dx) else 190
            image.putpixel((x+dx,y+dy),(value,)*3)


def fixture(raw='340',actual='840',era='AD'):
    text=f'City of Fispalis, A.D. {raw}, Population 10,000 (Treasury: 887 Gold)' if era=='AD' else f'City of Fispalis, {raw} B.C., Population 10,000 (Treasury: 887 Gold)'
    rows=[prepared(text,113,40,414,19),prepared('Auto',148,397,28,14),
          prepared('Help',307,397,28,14),prepared('OK',456,397,28,14)]
    image=Image.new('RGB',(640,480),(190,)*3)
    paint(image,'City of',115,41)
    paint(image,f', A.D. {actual},' if era=='AD' else f', {actual} B.C.,',207,41)
    return image,rows


def recover(image,rows,evidence=None):
    with patch.object(d,'_render',side_effect=rendered),patch.object(d,'_sources',return_value=('', 'City of\n')):
        return d.recover_caption_date(image,rows,evidence=evidence)


class CaptionDateTests(unittest.TestCase):
    def test_only_digit_replaced_with_original_text_and_prior_readings_preserved(self):
        image,rows=fixture();before=deepcopy(rows);e={}
        rows[0]['caption_year_consensus']={'digits':'340'}
        self.assertTrue(recover(image,rows,e))
        self.assertEqual(rows[0]['text'],before[0]['text'].replace('340','840'))
        self.assertEqual(rows[0]['bounds'],before[0]['bounds'])
        self.assertEqual(rows[0]['provenance'][:-1],before[0]['provenance'])
        self.assertEqual(rows[0]['caption_year_consensus'],{'digits':'340'})
        self.assertEqual(rows[1:],before[1:])
        self.assertEqual(rows[0]['caption_year_gdi']['date']['bounds'],[207,41,70,14])
        self.assertEqual(e['passes'],['original_gdi_caption_date'])

    def test_bc_uses_observed_era_and_same_length(self):
        image,rows=fixture('340','840','BC')
        self.assertTrue(recover(image,rows));self.assertIn('840 B.C.',rows[0]['text'])
        for raw,actual in [('340','940'),('340','34'),('340','1340'),('340','851')]:
            image,rows=fixture(raw,actual);before=deepcopy(rows)
            self.assertEqual(recover(image,rows),actual=='940')
            if actual!='940':self.assertEqual(rows,before)

    def test_missing_extra_colored_or_uncertain_field_abstains_without_mutation(self):
        modes=['left_comma','right_comma','above','below','right','gray','colored','prefix','two_fields','two_headers','controls','low_confidence','conflict','malformed_era','no_comma','wrong_era','shift_baseline']
        for mode in modes:
            with self.subTest(mode=mode):
                image,rows=fixture();e={}
                if mode=='left_comma':image.putpixel((207,41),(190,)*3)
                elif mode=='right_comma':image.putpixel((276,41),(190,)*3)
                elif mode=='above':image.putpixel((220,39),(0,)*3)
                elif mode=='below':image.putpixel((220,55),(0,)*3)
                elif mode=='right':image.putpixel((277,44),(0,)*3)
                elif mode=='gray':image.putpixel((212,41),(190,)*3)
                elif mode=='colored':image.putpixel((220,39),(255,0,0))
                elif mode=='prefix':image.putpixel((115,41),(190,)*3)
                elif mode=='two_fields':paint(image,', A.D. 840,',350,41)
                elif mode=='two_headers':rows.insert(1,deepcopy(rows[0]))
                elif mode=='controls':rows.pop()
                elif mode=='low_confidence':rows[0]['confidence']=.4
                elif mode=='conflict':e['conflicts']=['TEST']
                elif mode=='malformed_era':rows[0]['text']=rows[0]['text'].replace('A.D.','B.D.')
                elif mode=='no_comma':rows[0]['text']=rows[0]['text'].replace('340,','340 ')
                elif mode=='wrong_era':rows[0]['text']=rows[0]['text'].replace('A.D. 340','340 B.C.')
                elif mode=='shift_baseline':
                    image.paste((190,)*3,(207,38,280,58));paint(image,', A.D. 840,',207,42)
                before=deepcopy(rows)
                self.assertFalse(recover(image,rows,e),mode);self.assertEqual(rows,before)

    def test_source_and_optional_atlas_are_required_and_exact_read_is_noop(self):
        image,rows=fixture();before=deepcopy(rows)
        with patch.object(d,'_sources',return_value=('', 'City of\nCity of\n')):
            self.assertFalse(d.recover_caption_date(image,rows))
        with patch.object(d,'_sources',return_value=('', 'City of\n')),patch.object(d,'_render',side_effect=ValueError('absent')):
            self.assertFalse(d.recover_caption_date(image,rows))
        self.assertEqual(rows,before)
        image,rows=fixture('840','840');before=deepcopy(rows)
        self.assertFalse(recover(image,rows));self.assertEqual(rows,before)

    def test_actual_hispalis_date_with_no_city_or_native_state_supplied(self):
        path=Path('runs/attempt-012/screens/ui-0002872.png')
        from civ2.gdi_text import load_atlas
        if not path.exists() or load_atlas(style='regular') is None:self.skipTest('Private frame/atlas absent')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'349f6fe1f127644b3de1ef053d5c4052a49af225850061731eb3ce6203ccc119')
        image=Image.open(path)
        _,rows=fixture();before=deepcopy(rows)
        self.assertTrue(d.recover_caption_date(image,rows))
        self.assertEqual(rows[0]['text'],before[0]['text'].replace('340','840'))
        self.assertIn('Fispalis',rows[0]['text'])
        self.assertEqual(rows[0]['caption_year_gdi']['date']['bounds'],[207,41,70,14])
        self.assertEqual(rows[1:],before[1:])

    def test_actual_pipeline_keeps_all_production_choices_and_raw_city(self):
        path=Path('runs/attempt-012/screens/ui-0002872.png')
        from civ2.gdi_text import load_atlas
        if not path.exists() or not Path('.runtime/ocr').exists() or load_atlas(style='regular') is None:
            self.skipTest('Private frame/atlas/OCR absent')
        from civ2.observe import recognize
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        o=recognize(path)
        row=next(r for r in o['lines'] if 'caption_year_gdi' in r)
        self.assertIn('City of Fispalis, A.D. 840,',row['text'])
        self.assertEqual(row['caption_year_gdi']['previous_digits'],'340')
        state={'recent_founding_notices':[{'name':'Hispalis','source_tag':'FOUNDED',
                 'image_sha256':'b'*64,'year_text':'A.D. 840'}]}
        result=classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text())
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['kind'],'production_choice')
        self.assertEqual(result['title'],'What shall we build in Hispalis?')
        self.assertEqual(len(result['options']),16)
        self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
        state['recent_founding_notices'][0]['year_text']='A.D. 340'
        self.assertFalse(classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text())['supported'])


if __name__=='__main__':unittest.main()
