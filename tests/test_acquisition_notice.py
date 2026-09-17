from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from civ2.acquisition_notice import classify_acquisition_notice
from civ2.dialogs import _rows,classify_dialog
from civ2.observe import recognize


def fixture(folder):
    image=Image.new('RGB',(640,480),(170,170,170));p=image.load()
    for y in range(40):
        for x in range(72):p[125+x,217+y]=(0,0,0) if x<2 or y<2 or x>=70 or y>=38 else ((190,150,44) if x<4 or y<4 or x>=68 or y>=36 else (0,80,0))
    path=Path(folder)/'test.png';image.save(path)
    def row(text,x,y,w,h):return dict(text=text,bounds=[x,y,w,h],center=[x+w//2,y+h//2],confidence=1.)
    o=dict(width=640,height=480,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
           lines=[row('TEST Romans acquire TEST Currency!',202,220,270,16),row('OK',308,268,24,16)])
    labels='\n'.join(['TEST']*111+['acquire']);rules={'advances':[{'id':20,'name':'TEST Currency'}]};state={'player':{'tribe':'TEST Romans'}}
    return o,labels,rules,state


class AcquisitionTests(unittest.TestCase):
    def test_complete_known_notice_permits_only_information_acknowledgement(self):
        with tempfile.TemporaryDirectory() as d:
            o,l,r,s=fixture(d);out=classify_acquisition_notice(o,_rows(o),l,r,s)
            self.assertEqual(out['button']['text'],'OK');self.assertEqual(out['evidence']['original_advance']['id'],20)
            self.assertIn('not inferred',out['evidence']['effect_scope'])

    def test_unknown_name_wrong_source_extra_control_or_missing_pixels_refuse(self):
        for mode in ('advance','tribe','label','extra','glyph','hash','frame'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                o,l,r,s=fixture(d)
                if mode=='advance':r['advances'][0]['name']='Different'
                elif mode=='tribe':s['player']['tribe']='Other'
                elif mode=='label':l=l.replace('acquire','give')
                elif mode=='extra':o['lines'].append(dict(text='Cancel',bounds=[350,268,40,16],center=[370,276],confidence=1.))
                elif mode=='glyph':o['lines'][0]['text']='TEST Romans acquire TEST Currencyl'
                elif mode=='hash':o['sha256']='0'*64
                else:
                    p=Path(o['path']);im=Image.open(p).convert('RGB');im.putpixel((125,217),(255,255,255));im.save(p)
                    o['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
                self.assertIsNone(classify_acquisition_notice(o,_rows(o),l,r,s))

    def test_actual_acquisition_recovers_punctuation_without_fabricating_technology(self):
        p=Path('runs/attempt-004/screens/ui-0000943.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private native capture unavailable')
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        original=p.read_bytes();o=recognize(p);o['path']=str(p)
        out=classify_dialog(o,game_text=game_text(),labels_text=labels_text(),rules=parse_rules(original_rules()),state={'player':{'tribe':'Romans'}})
        self.assertTrue(out['supported'],out);self.assertEqual(out['resource_tag'],'LABELS_ACQUIRE_ADVANCE')
        self.assertEqual(out['mechanical_action'],'acknowledge_information');self.assertFalse(out['requires_model'])
        line=next(x for x in o['lines'] if x['text']=='Romans acquire Currency!')
        self.assertIn('Romans acquire Currencyl',[x['text'] for x in line['provenance']])
        self.assertEqual(original,p.read_bytes())

    def test_actual_pottery_notice_preserves_corresponding_ascii_control_confidence(self):
        p=Path('runs/attempt-011/screens/ui-0000379.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private native capture unavailable')
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        o=recognize(p);o['path']=str(p)
        out=classify_dialog(o,game_text=game_text(),labels_text=labels_text(),rules=parse_rules(original_rules()),state={'player':{'tribe':'Romans'}})
        self.assertTrue(out['supported'],out)
        self.assertEqual(out['resource_tag'],'LABELS_ACQUIRE_ADVANCE')
        self.assertEqual(out['title'],'Romans acquire Pottery!')
        control=next(r for r in o['lines'] if r['text']=='OK')
        self.assertEqual(control['confidence'],1.)
        self.assertEqual(control['provenance'][0]['text'],'OК')
        self.assertEqual(control['provenance'][0]['confidence'],.5)


if __name__=='__main__':unittest.main()
