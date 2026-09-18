"""Source and synthetic native-frame tests; no live caravan calibration claim."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from PIL import Image,ImageDraw
from civ2.caravan import (SOURCES,SOURCE_HASHES,COMMODITY_SHA256,ARRIVAL_OPTIONS,
    _commodities,_pixel_layout,classify_caravan)
from civ2.evidence import canonical
from civ2.dialogs import _rows
from civ2.gdi_text import WHITE_RING,BLACK_RING

COMMODITIES=['Hides','Wool','Beads','Cloth','Salt','Coal','Copper','Dye','Wine','Silk','Silver','Spice','Gems','Gold','Oil','Uranium']
RULE_TEXT='@CARAVAN\n'+'\n'.join(name+',' for name in COMMODITIES)+'\n@ORDERS\n'


def fixture(directory,tag='CARAVANMENU',arrival_count=3):
    source=SOURCES[tag];width=source['width'];left=320-(width+22)//2;right=left+width+21
    def row(text,x,y,w=160,h=16):return dict(text=text,bounds=[x,y,w,h],center=[x+w//2,y+h//2],confidence=1.)
    rows=[row('TEST Caravan Options' if tag=='CARAVANMENU' else 'Caravan',270,140,100)]
    if tag=='CARAVANMENU':names=ARRIVAL_OPTIONS[:arrival_count];ys=[184+25*i for i in range(len(names))]
    elif tag=='CARACONFIRM':
        rows.append(row('Confirm Silk caravan?',left+12,169,180));names=['Confirmed.','Reconsider.'];ys=[210,235]
    else:
        rows.extend([row('TEST City builds TEST Caravan.',left+12,167,300),
                     row('What trade goods shall it carry?',left+12,188,300)])
        names=['Hides','Silk','Gold','Food'];ys=[230+25*i for i in range(4)]
    choices=[row(name,left+44,y-8,190) for name,y in zip(names,ys)];rows.extend(choices)
    by=ys[-1]+37
    if source['buttons']:
        rows.extend([row(source['buttons'][0],left+20,by,160),row('OK',right-54,by,24)])
    else:rows.append(row('OK',308,by,24))
    bottom=by+27;image=Image.new('RGB',(640,480),(130,130,130));draw=ImageDraw.Draw(image)
    draw.rectangle((left,132,right,bottom),fill=(160,160,160),outline=(0,0,0))
    draw.line((left+1,133,right-2,133),fill=(223,223,223))
    draw.line((right-1,134,right-1,bottom-1),fill=(65,65,65))
    for y in ys:
        for dx,dy in WHITE_RING:image.putpixel((left+24+dx,y+dy),(255,255,255))
        for dx,dy in BLACK_RING:image.putpixel((left+24+dx,y+dy),(0,0,0))
    path=Path(directory)/'frame.png';image.save(path)
    o=dict(width=640,height=480,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),path=str(path),lines=rows)
    labels=['']*180;labels[80]='Food';labels[177:180]=ARRIVAL_OPTIONS
    rules={'units':[dict(name='TEST Caravan',id=48,domain=0,role=7)]}
    return o,deepcopy(list(SOURCES.values())),rules,'\n'.join(labels)


class CaravanChoicesTests(TestCase):
    def classify(self,o,s,r,l,text=RULE_TEXT):
        return classify_caravan(o,_rows(o),s,r,l,caravan_rules_text=text)

    def test_source_pins_and_production_cargo_confirmation_arrival_choices(self):
        self.assertEqual(hashlib.sha256(canonical(COMMODITIES)).hexdigest(),COMMODITY_SHA256)
        for tag,source in SOURCES.items():self.assertEqual(hashlib.sha256(canonical(source)).hexdigest(),SOURCE_HASHES[tag])
        for tag,count in [('CARAVANBUILT',5),('CARACONFIRM',3),('CARAVANMENU',3)]:
            with self.subTest(tag=tag),TemporaryDirectory() as directory:
                o,s,r,l=fixture(directory,tag);result=self.classify(o,s,r,l)
                self.assertIsNotNone(result);self.assertTrue(result['requires_model'])
                self.assertIsNone(result['mechanical_action']);self.assertEqual(len(result['options']),count)
                self.assertEqual(result['resource_tag'],tag)
                radios=[x for x in result['options'] if x['control']=='option']
                self.assertEqual(len(radios),result['evidence']['caravan_choice']['pixels']['complete_observed_radio_count'])
                self.assertNotIn('OK',[x['text'] for x in result['options']])
                self.assertIn('not live calibrated',result['evidence']['caravan_choice']['pixels']['calibration'])
                if tag=='CARACONFIRM':
                    self.assertEqual(result['options'][-1]['text'],'Confirm and Zoom')
                    self.assertEqual(result['options'][-1]['control'],'button')

    def test_two_arrival_choices_remain_actual_model_choices(self):
        with TemporaryDirectory() as directory:
            o,s,r,l=fixture(directory,arrival_count=2);result=self.classify(o,s,r,l)
            self.assertEqual([x['text'] for x in result['options']],ARRIVAL_OPTIONS[:2])
            self.assertTrue(result['requires_model'])

    def test_ocr_missing_radio_choice_or_hidden_radio_refuses_incomplete_menu(self):
        for tag in SOURCES:
            with self.subTest(tag=tag),TemporaryDirectory() as directory:
                o,s,r,l=fixture(directory,tag)
                choices={'CARAVANMENU':'Establish trade route.','CARAVANBUILT':'Silk','CARACONFIRM':'Reconsider.'}
                o['lines']=[x for x in o['lines'] if x['text']!=choices[tag]]
                self.assertIsNone(self.classify(o,s,r,l))

    def test_geometry_pixel_frame_and_hash_damage_refuse(self):
        for mode in ('hash','radio','frame','extra_radio','button','extra_control','low_confidence'):
            with self.subTest(mode=mode),TemporaryDirectory() as directory:
                o,s,r,l=fixture(directory);p=Path(o['path'])
                if mode=='hash':o['sha256']='f'*64
                elif mode=='button':o['lines'][-1]['text']='Cancel'
                elif mode=='extra_control':o['lines'].append(dict(o['lines'][-1],text='Yes'))
                elif mode=='low_confidence':o['lines'][2]['confidence']=.7
                else:
                    im=Image.open(p).convert('RGB')
                    if mode=='radio':im.putpixel((173,176),(120,120,120))
                    elif mode=='frame':im.putpixel((149,132),(120,120,120))
                    else:
                        for dx,dy in WHITE_RING:im.putpixel((225+dx,180+dy),(255,255,255))
                        for dx,dy in BLACK_RING:im.putpixel((225+dx,180+dy),(0,0,0))
                    im.save(p);o['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
                self.assertIsNone(self.classify(o,s,r,l))

    def test_unknown_cargo_or_unit_partial_prompt_source_and_label_tamper_refuse(self):
        for mode in ('cargo','unit','body','source','labels','catalog','food'):
            with self.subTest(mode=mode),TemporaryDirectory() as directory:
                o,s,r,l=fixture(directory,'CARAVANBUILT');text=RULE_TEXT
                if mode=='cargo':o['lines'][3]['text']='Unknown commodity'
                elif mode=='unit':r['units'][0]['role']=5
                elif mode=='body':o['lines'][2]['text']='What shall we do?'
                elif mode=='source':s[1]['buttons']=[]
                elif mode=='labels':l=l.replace('Help build WONDER.','Help construct.')
                elif mode=='catalog':text=text.replace('Silk,','Unknown,')
                else:o['lines']=[x for x in o['lines'] if x['text']!='Food']
                self.assertIsNone(self.classify(o,s,r,l,text))

    def test_confirm_and_zoom_remains_available_without_automatic_confirmation(self):
        with TemporaryDirectory() as directory:
            o,s,r,l=fixture(directory,'CARACONFIRM');result=self.classify(o,s,r,l)
            self.assertEqual([x['text'] for x in result['options']],['Confirmed.','Reconsider.','Confirm and Zoom'])
            self.assertFalse(result['evidence']['caravan_choice']['details']['confirmation_executed'])
            o['lines'][1]['text']='Confirm Imagined caravan?'
            self.assertIsNone(self.classify(o,s,r,l))

    def test_dialog_hook_preserves_every_native_choice_in_canonical_model_request(self):
        from civ2.dialogs import classify_dialog
        from civ2.policy import dialog_request_for,validate_action
        source_text='\n'.join('@'+s['tag']+'\n@width='+str(s['width'])+'\n@title='+s['title']+'\n'+
            '\n'.join('@button='+b for b in s['buttons'])+'\n'+s['body']+'\n\n'+
            '\n'.join(s['options'])+'\n' for s in SOURCES.values())
        for tag in SOURCES:
            with self.subTest(tag=tag),TemporaryDirectory() as directory,patch(
                    'civ2.caravan._original_commodities',return_value=COMMODITIES):
                o,s,r,l=fixture(directory,tag)
                dialog=classify_dialog(o,game_text=source_text,rules=r,labels_text=l)
                self.assertTrue(dialog['supported'],dialog);self.assertTrue(dialog['requires_model'])
                request,actions=dialog_request_for({},dialog,rules=r)
                expected=[x['text'] for x in dialog['options']]
                self.assertEqual(list(request['questions']['dialog_action']['criteria'].values()),expected)
                for index,action in enumerate(actions.values()):
                    self.assertEqual(action['parameters']['option_index'],index)
                    self.assertEqual(action['preconditions']['image_sha256'],o['sha256'])
                    validate_action(action,{},r,dialog=dialog)

    def test_actual_original_radio_and_frame_primitives_not_caravan_claim(self):
        path=Path('.runtime/foreign-minister-calibration-01/reportforeign-observation.json')
        if not path.exists():self.skipTest('Private generic native frame calibration unavailable')
        o=json.loads(path.read_text());rows=_rows(o)
        title=next(r for r in rows if r['text']=='Foreign Winister')
        buttons=[r for r in rows if r['text'] in ('Check Intelligence','Send Emissary','Cancel')]
        choices=[r for r in rows if r['text'].startswith('Warlord')]
        proof=_pixel_layout(o,title,buttons,choices,580)
        self.assertEqual(proof['frame_bounds'],[20,182,622,299])
        self.assertEqual(proof['complete_observed_radio_count'],1)
        self.assertIn('not live calibrated',proof['calibration'])
