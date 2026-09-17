"""Independent synthetic mask rejection tests and optional original calibration."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import gdi_titles as g
from civ2.dialogs import _rows,classify_dialog,dialog_resources
from tests.test_dialogs import row,observation,RULES

SOURCE='''@PRODUCTION
@title=What shall we build in %STRING0?
@width=440
@listbox=16
@button=Auto
@button=Help
'''
# TEST stencil, deliberately unrelated to a real font. Black and gray have
# different asymmetric shapes, so subset/translation mistakes are detectable.
BLACK=[(1<<i)|(1<<(119-i)) for i in range(12)]
GRAY=[(1<<(25+i))|(1<<(75-i)) for i in range(12)]
STENCIL=(120,12,BLACK,GRAY)


def fixture():
    image=Image.new('RGB',(640,480),(199,199,199))
    for y in range(12):
        for x in range(120):
            if BLACK[y]&(1<<x):image.putpixel((260+x,146+y),(0,0,0))
            if GRAY[y]&(1<<x):image.putpixel((260+x,146+y),(134,134,134))
    o=observation(row('Unreadable TEST caption',y=152,w=160,h=16),
        row('TEST Warriors',x=210,y=180,w=130),row('(3 Turns)',x=440,y=180,w=70),
        row('TEST Granary',x=210,y=205,w=130),row('(8 Turns)',x=440,y=205,w=70),
        row('Auto',x=160,y=260,w=30),row('Help',x=320,y=260,w=30),row('OK',x=480,y=260,w=24))
    s={'evidence':{'save_sha256':'b'*64},'player':{'id':1},
       'cities':[{'id':2,'owner':1,'name':'TEST Rome','x':7,'y':9}]}
    return image,o,s


def match(image,o,s,resources=None):
    g.annotate_production_titles(image,o['lines'],o['sha256'])
    return g.exact_production_title(o,_rows(o),s,resources or [g.TITLE_TEMPLATE])


class ExactTitleTests(unittest.TestCase):
    def test_source_resource_is_exact_and_pinned(self):
        self.assertEqual(dialog_resources(SOURCE),[g.TITLE_TEMPLATE])
        self.assertEqual(hashlib.sha256(g._canonical(g.TITLE_TEMPLATE)).hexdigest(),g.TEMPLATE_SHA256)

    def test_canonical_title_keeps_raw_observation_and_model_choices(self):
        image,o,s=fixture();raw=deepcopy(o)
        with patch.object(g,'load_atlas',return_value=object()),patch.object(g,'_render',return_value=STENCIL):
            p=match(image,o,s)
            self.assertIsNotNone(p);self.assertEqual(p[1]['text'],'What shall we build in TEST Rome?')
            self.assertEqual(p[3]['name_source']['save_sha256'],'b'*64)
            self.assertNotIn('observation_sha256',p[3]['name_source'])
            self.assertEqual(o['lines'][0]['text'],raw['lines'][0]['text'])
            before=deepcopy(o)
            result=classify_dialog(o,state=s,rules=RULES,game_text=SOURCE)
            self.assertTrue(result['supported'],result);self.assertTrue(result['requires_model'])
            self.assertIsNone(result['mechanical_action']);self.assertEqual(len(result['options']),2)
            self.assertEqual(result['title'],p[1]['text']);self.assertEqual(o,before)
            self.assertIn(raw['lines'][0]['text'],result['visible_text'])
            self.assertEqual(result['evidence']['exact_production_title']['black_extra'],0)

    def test_all_black_and_predicted_gray_and_palette_are_required(self):
        for mode in ('missing_black','extra_black','missing_gray','colored','off_palette','shifted'):
            image,o,s=fixture()
            if mode=='missing_black':image.putpixel((260,146),(199,199,199))
            elif mode=='extra_black':image.putpixel((535,146),(0,0,0))
            elif mode=='missing_gray':image.putpixel((285,146),(199,199,199))
            elif mode=='colored':image.putpixel((535,146),(199,198,199))
            elif mode=='off_palette':image.putpixel((535,146),(48,48,48))
            else:image=image.transform(image.size,Image.Transform.AFFINE,(1,0,-10,0,1,0))
            with self.subTest(mode=mode),patch.object(g,'load_atlas',return_value=object()),patch.object(g,'_render',return_value=STENCIL):
                self.assertIsNone(match(image,o,s))

    def test_identity_source_and_ambiguity_fail_closed(self):
        for mode in ('foreign','unhashed','dual_hash','duplicate_name','same_pixels_two_names','untrusted_name','wrong_source','duplicate_source'):
            image,o,s=fixture();resources=[deepcopy(g.TITLE_TEMPLATE)]
            if mode=='foreign':s['cities'][0]['owner']=2
            elif mode=='unhashed':s['evidence']={}
            elif mode=='dual_hash':s['evidence']['observation_sha256']='c'*64
            elif mode=='duplicate_name':s['cities'].append({**s['cities'][0],'id':3})
            elif mode=='same_pixels_two_names':s['cities'].append({**s['cities'][0],'id':3,'name':'TEST Veii'})
            elif mode=='untrusted_name':s['cities']=[];s['observed_city_names']=['TEST Rome']
            elif mode=='wrong_source':resources[0]['title']='What shall we sell in %STRING0?'
            else:resources*=2
            with self.subTest(mode=mode),patch.object(g,'load_atlas',return_value=object()),patch.object(g,'_render',return_value=STENCIL):
                self.assertIsNone(match(image,o,s,resources))

    def test_founding_candidate_requires_exact_current_header_year_and_source(self):
        for mode in ('valid','year','source','hash','header'):
            image,o,s=fixture();s['cities']=[]
            o['lines'].append(row('City of TEST Rorne, 2150 B.C., Population TEST',y=44,w=420))
            notice={'name':'TEST Rome','year_text':'2150 B.C.','source_tag':'FOUNDED','image_sha256':'c'*64}
            s['recent_founding_notices']=[notice]
            if mode=='year':notice['year_text']='2100 B.C.'
            elif mode=='source':notice['source_tag']='UNKNOWN'
            elif mode=='hash':notice['image_sha256']='invalid'
            elif mode=='header':o['lines'].pop()
            with self.subTest(mode=mode),patch.object(g,'load_atlas',return_value=object()),patch.object(g,'_render',return_value=STENCIL):
                p=match(image,o,s);self.assertEqual(p is not None,mode=='valid')
                if p:self.assertEqual(p[3]['name_source']['kind'],'same_year_founding_notice')

    def test_pixel_proof_cannot_be_rebound_or_malformed(self):
        for mode in ('image','row','crop','mask','palette','rgb_digest','overlap'):
            image,o,s=fixture();g.annotate_production_titles(image,o['lines'],o['sha256'])
            p=o['lines'][0]['gdi_title_pixels']
            if mode=='image':p['source_sha256']='c'*64
            elif mode=='row':p['row_bounds'][0]+=1
            elif mode=='crop':p['crop'][0]+=1
            elif mode=='mask':p['black'][0]='not hex'
            elif mode=='palette':p['palette']=[0,134,255]
            elif mode=='rgb_digest':p['region_rgb_sha256']='invalid'
            else:p['gray134']=p['black'][:]
            with self.subTest(mode=mode),patch.object(g,'load_atlas',return_value=object()),patch.object(g,'_render',return_value=STENCIL):
                self.assertIsNone(g.exact_production_title(o,_rows(o),s,[g.TITLE_TEMPLATE]))

    def test_caption_proof_does_not_authorize_incomplete_choices(self):
        for mode in ('missing_button','unknown_option','duplicate_button','atlas_missing'):
            image,o,s=fixture();g.annotate_production_titles(image,o['lines'],o['sha256'])
            if mode=='missing_button':o['lines'].pop()
            elif mode=='unknown_option':o['lines'][1]['text']='Unrecognized strategic TEST option'
            elif mode=='duplicate_button':o['lines'].append(row('OK',x=510,y=260,w=24))
            with self.subTest(mode=mode),patch.object(g,'load_atlas',return_value=None if mode=='atlas_missing' else object()),patch.object(g,'_render',return_value=STENCIL):
                d=classify_dialog(o,state=s,rules=RULES,game_text=SOURCE)
                self.assertFalse(d['supported'],d)

    def test_optional_four_original_captions_use_one_fixed_composition(self):
        root=Path(__file__).resolve().parents[1]
        if g.load_atlas(style='regular') is None:self.skipTest('Private original regular atlas absent')
        for attempt,number,name,count in [(10,786,'Cumae',16),(5,112,'Rome',6),(3,136,'Veii',5),(6,653,'Antium',8)]:
            with self.subTest(attempt=attempt):
                path=root/f'runs/attempt-{attempt:03}/screens/ui-{number:07}.png'
                recorded=root/f'.runtime/font-caption-probe/observation-{attempt}-{number}.json'
                if not path.exists() or not recorded.exists():self.skipTest('Private original calibration absent')
                o=json.loads(recorded.read_text());self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),o['sha256'])
                image=Image.open(path);state={'evidence':{'kind':'live_memory','observation_sha256':'c'*64},
                    'player':{'id':1},'cities':[{'id':0,'owner':1,'name':name,'x':1,'y':1}]}
                g._render.cache_clear();p=match(image,o,state)
                self.assertIsNotNone(p);self.assertEqual(p[1]['text'],f'What shall we build in {name}?')
                self.assertEqual(p[3]['gray134_overpaint_offsets'],[[-1,-1],[-2,-1]])
                self.assertEqual(p[3]['predicted_gray_missing'],0)
                self.assertEqual(p[3]['name_source']['observation_sha256'],'c'*64)
                from civ2.run import game_text
                from civ2.boot import original_rules
                from civ2.save import parse_rules
                state['recent_founding_notices']=[{'name':name,'source_tag':'FOUNDED',
                    'image_sha256':'b'*64,'year_text':'2150 B.C.'}]
                d=classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text())
                self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_choice')
                self.assertTrue(d['requires_model']);self.assertEqual(len(d['options']),count)
                self.assertEqual(d['title'],p[1]['text'])
                image.putpixel((535,p[1]['bounds'][1]),(0,0,0))
                self.assertIsNone(match(image,o,state))


if __name__=='__main__':unittest.main()
