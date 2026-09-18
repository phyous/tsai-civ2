"""Guarded synthetic F12 menus; original static evidence, no live ship claim."""
from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile
from PIL import Image,ImageDraw
from civ2.dialogs import _rows,classify_dialog,dialog_resources
from civ2.evidence import canonical
from civ2.gdi_text import WHITE_RING,BLACK_RING
from civ2.spaceship_report import (SOURCES,SOURCE_HASHES,LABELS,EXE_SHA256,
    classify_spaceship_report,_button_rectangles,space_review_available)

GAME='@SPACESHIPS\n@width=320\n@title=View Which Spaceship\n@options\n\n'+\
    '@SPACESHIP\n@width=480\n@title=Spaceship Report\n@listbox\n^^%STRING0.S.S. %STRING1 (%STRING2)\n'
labels=['']*252
for index,text in LABELS.items():labels[index]=text
LABEL_TEXT='\n'.join(labels)
RULES={'leaders':[dict(tribe='Romans',adjective='Roman'),dict(tribe='Germans',adjective='German')]}
READOUT=['Romans.S.S. Caesar (Roman)','Structural 32','Propulsion 8','Fuel 8','Habitation 1',
    'Life Support 1','Solar Panel 1','Population 10,000','Support 100%','Energy 100%',
    'Mass 5,200 tons','Fuel 100%','Flight Time 22.1 years','Prob. of Success --- 93% ---']


def fixture(directory,tag='SPACESHIP',launch=True,one=False):
    def row(text,x,y,w=220,h=12):return dict(text=text,bounds=[x,y,w,h],center=[x+w//2,y+h//2],confidence=1.)
    width=SOURCES[tag]['width'];left=320-(width+22)//2;right=left+width+21
    top=132 if tag=='SPACESHIPS' else 32
    rows=[row(SOURCES[tag]['title'],220,top+8,200,16)]
    image=Image.new('RGB',(640,480),(130,130,130));draw=ImageDraw.Draw(image)
    if tag=='SPACESHIPS':
        names=['Romans'] if one else ['Romans','Germans'];ys=[184+25*i for i in range(len(names))]
        rows.extend(row(name,left+44,y-8,190,16) for name,y in zip(names,ys));by=ys[-1]+37
        button_names=['OK','Cancel']
    else:
        rows.extend(row(text,left+12,65+16*i,450 if i==0 else 330) for i,text in enumerate(READOUT))
        by=65+16*len(READOUT)+25;button_names=['Launch','OK'] if launch else ['OK'];ys=[]
    bottom=by+27
    draw.rectangle((left,top,right,bottom),fill=(160,160,160),outline=(0,0,0))
    draw.line((left+1,top+1,right-2,top+1),fill=(223,223,223))
    draw.line((right-1,top+2,right-1,bottom-1),fill=(65,65,65))
    for y in ys:
        for dx,dy in WHITE_RING:image.putpixel((left+24+dx,y+dy),(255,255,255))
        for dx,dy in BLACK_RING:image.putpixel((left+24+dx,y+dy),(0,0,0))
    button_width=(width+10)//len(button_names)
    for i,name in enumerate(button_names):
        a=left+7+i*button_width;b=a+button_width-5;u=by-7;v=by+20
        draw.rectangle((a,u,b,v),fill=(195,195,195),outline=(0,0,0))
        draw.line((a+1,u+1,b-1,u+1),fill=(255,255,255))
        draw.line((b-1,u+3,b-1,v-1),fill=(130,130,130))
        tw=24 if name=='OK' else 48;rows.append(row(name,(a+b)//2-tw//2,by,tw,14))
    path=Path(directory)/'ship-report.png';image.save(path)
    return dict(width=640,height=480,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),lines=rows)


class SpaceshipReports(unittest.TestCase):
    def classify(self,o,text=GAME,labels=LABEL_TEXT):
        return classify_spaceship_report(o,_rows(o),dialog_resources(text),RULES,labels,text)

    def test_selector_keeps_every_observed_civilization_and_actual_cancel(self):
        for one in (False,True):
            with TemporaryDirectory() as directory:
                o=fixture(directory,'SPACESHIPS',one=one);d=self.classify(o)
                self.assertIsNotNone(d);self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
                self.assertEqual([r['text'] for r in d['options']],['Romans','Cancel'] if one else ['Romans','Germans','Cancel'])
                self.assertEqual(d['options'][-1]['control'],'button')

    def test_complete_report_launch_and_ok_are_separate_model_choices(self):
        with TemporaryDirectory() as directory:
            o=fixture(directory);before=deepcopy(o);d=self.classify(o)
            self.assertIsNotNone(d);self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
            self.assertEqual([r['text'] for r in d['options']],['Launch','OK'])
            self.assertTrue(all(r['control']=='button' for r in d['options']))
            detail=d['evidence']['spaceship_report']['details']
            self.assertEqual(detail['observed_statistics']['Prob. of Success'],'--- 93% ---')
            self.assertEqual(detail['observed_part_counts'][0]['count'],32)
            self.assertNotIn('launched',detail);self.assertEqual(o,before)

    def test_sole_ok_dismisses_only_complete_report_without_fabricated_choice(self):
        with TemporaryDirectory() as directory:
            d=self.classify(fixture(directory,launch=False))
            self.assertIsNotNone(d);self.assertFalse(d['requires_model'])
            self.assertEqual(d['mechanical_action'],'acknowledge_information')
            self.assertEqual([r['text'] for r in d['options']],['OK'])

    def test_missing_launch_ocr_cannot_be_mistaken_for_single_ok(self):
        with TemporaryDirectory() as directory:
            o=fixture(directory);o['lines']=[r for r in o['lines'] if r['text']!='Launch']
            self.assertIsNone(self.classify(o))

    def test_source_and_report_labels_are_pinned(self):
        self.assertEqual(dialog_resources(GAME),list(SOURCES.values()))
        for tag in SOURCES:
            self.assertEqual(hashlib.sha256(canonical(SOURCES[tag])).hexdigest(),SOURCE_HASHES[tag])
            with TemporaryDirectory() as directory:
                o=fixture(directory,tag)
                self.assertIsNone(self.classify(o,GAME.replace('@width=','@width=1')))
                self.assertIsNone(self.classify(o,labels=LABEL_TEXT.replace('Launch','Depart')))
                if tag=='SPACESHIPS':self.assertIsNone(self.classify(o,GAME.replace('@options\n','')))

    def test_complete_counts_units_rows_and_observed_controls_are_required(self):
        for mode in ('part','stat','extra','control','probability','weak','hash','launch_word','frame','button_border'):
            with self.subTest(mode=mode),TemporaryDirectory() as directory:
                o=fixture(directory)
                if mode=='part':o['lines'].pop(3)
                elif mode=='stat':o['lines'].pop(10)
                elif mode=='extra':o['lines'].insert(-1,dict(o['lines'][-3],text='Pay 100 gold.'))
                elif mode=='control':o['lines'].append(dict(o['lines'][-1],text='Cancel'))
                elif mode=='probability':o['lines'][-3]['text']='Prob. of Success --- ??% ---'
                elif mode=='weak':o['lines'][5]['confidence']=.7
                elif mode=='hash':o['sha256']='f'*64
                elif mode=='launch_word':o['lines'][-2]['bounds'][1]=120;o['lines'][-2]['center'][1]=127
                else:
                    p=Path(o['path']);im=Image.open(p).convert('RGB')
                    im.putpixel((69,32) if mode=='frame' else (76,307),(160,160,160))
                    im.save(p);o['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
                self.assertIsNone(self.classify(o))

    def test_selector_missing_radio_or_unknown_tribe_refuses(self):
        for mode in ('missing','unknown','duplicate','cancel'):
            with self.subTest(mode=mode),TemporaryDirectory() as directory:
                o=fixture(directory,'SPACESHIPS')
                if mode=='missing':o['lines'].pop(1)
                elif mode=='unknown':o['lines'][1]['text']='Unobserved Nation'
                elif mode=='duplicate':o['lines'][2]['text']='Romans'
                else:o['lines'].pop()
                self.assertIsNone(self.classify(o))

    def test_dialog_actions_bind_report_buttons_without_automatic_enter_or_launch(self):
        from civ2.policy import dialog_request_for,validate_action
        for tag in SOURCES:
            with TemporaryDirectory() as directory:
                o=fixture(directory,tag);d=classify_dialog(o,game_text=GAME,labels_text=LABEL_TEXT,rules=RULES)
                self.assertTrue(d['supported'],d);self.assertIsNone(d['outcome'])
                request,actions=dialog_request_for({},d)
                self.assertEqual(list(request['questions']['dialog_action']['criteria'].values()),[r['text'] for r in d['options']])
                for action in actions.values():validate_action(action,{},dialog=d)

    def test_actual_generic_f3_buttons_validate_but_are_not_spaceship_calibration(self):
        import json
        p=Path('.runtime/foreign-minister-calibration-01/reportforeign-observation.json')
        if not p.exists():self.skipTest('Private original generic control calibration unavailable')
        o=json.loads(p.read_text());buttons=[r for r in _rows(o) if r['text'] in ('Check Intelligence','Send Emissary','Cancel')]
        image=Image.open(o['path']).convert('RGB')
        self.assertEqual(_button_rectangles(image,[20,182,622,299],buttons),[[27,267,221,295],[224,267,418,295],[421,267,615,295]])

    def test_original_source_and_static_executable_anchors(self):
        import struct
        p=Path('engine/game/civ2-win31.zip')
        if not p.exists():self.skipTest('Private original sources unavailable')
        with ZipFile(p) as z:
            text=z.read('civ2/GAME.TXT').decode('cp1252');labels=z.read('civ2/LABELS.TXT').decode('cp1252')
            exe=z.read('civ2/CIV2.EXE');menu=z.read('civ2/MENU.TXT').decode('cp1252')
        self.assertEqual(hashlib.sha256(exe).hexdigest(),EXE_SHA256);self.assertIn('&Spaceships|F12',menu)
        ne=struct.unpack_from('<I',exe,0x3c)[0];table=ne+struct.unpack_from('<H',exe,ne+0x22)[0];shift=struct.unpack_from('<H',exe,ne+0x32)[0]
        sector,length,_,_=struct.unpack_from('<HHHH',exe,table+156*8);data=exe[sector<<shift:(sector<<shift)+length]
        self.assertEqual(data[0xa75:0xa7f],b'SPACESHIP\0');self.assertEqual(data[0xaa2:0xaa9],b'LAUNCH\0')
        self.assertEqual(data[0xac4:0xacf],b'SPACESHIPS\0')
        for tag in SOURCES:
            with TemporaryDirectory() as directory:self.assertIsNotNone(self.classify(fixture(directory,tag),text,labels))


if __name__=='__main__':unittest.main()
