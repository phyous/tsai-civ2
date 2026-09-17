"""Independent white-glyph readings never derive a city name from game state."""
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.dialogs import _rows,classify_dialog


def row(text,*,x=236,y=174,w=60,h=18,confidence=1,source='native'):
    return observe._prepare_rows([dict(text=text,x=x/640,y=y/480,width=w/640,height=h/480,
                                      confidence=confidence)],640,480,source)[0]


class MapLabelCrossScale(unittest.TestCase):
    def fixture(self):
        rows=[row(t,x=8+i*65,y=20,w=45,h=16) for i,t in enumerate(('Game','Kingdom','View','Orders'))]
        rows.append(row('Antumn'))
        image=Image.new('RGB',(640,480),(80,95,40))
        for x in range(240,275):
            for y in range(178,183):image.putpixel((x,y),(255,255,255))
        return image,rows

    def read(self,mode=None):
        def crop(image,old,name,*args,**kwargs):
            text='Antiutn'
            if name.endswith('_white190_2x') or name.endswith('_white230_4x'):text='Antium'
            if name.endswith('_white230_4x') and mode=='disagree':text='Antiuna'
            fresh=row(text,source=name)
            if name.endswith('_white230_4x') and mode=='low':fresh['confidence']=.5
            if name.endswith('_white230_4x') and mode=='outside':fresh.update(bounds=[360,174,60,18],center=[390,183])
            if name.endswith('_white230_4x') and mode=='error':raise ValueError('TEST malformed crop')
            return [fresh]
        return crop

    def test_correct_independent_pair_survives_agreeing_wrong_rgb_pair(self):
        image,rows=self.fixture()
        with patch.object(observe,'_crop_text',side_effect=self.read()) as crop:
            observe._recover_map_labels(image,rows,None,None,{'passes':[]})
        self.assertEqual(crop.call_count,4)
        self.assertEqual(rows[-1]['text'],'Antiutn')  # Earlier actual OCR remains, never replaced from a city table.
        self.assertEqual(rows[-1]['provenance'][0]['text'],'Antumn')
        o=dict(width=640,height=480,sha256='a'*64,lines=rows)
        prepared=next(r for r in _rows(o) if r['normal']=='antiutn')
        self.assertIn('antium',prepared['same_pixel_map_readings'])
        self.assertIn('antumn',prepared['same_pixel_map_readings'])
        self.assertIn('antiutn',prepared['same_pixel_map_readings'])
        self.assertFalse(classify_dialog(o,state={})['supported'])

    def test_unpaired_low_confidence_displaced_or_failed_new_read_is_not_retained(self):
        for mode in ('disagree','low','outside','error'):
            with self.subTest(mode=mode):
                image,rows=self.fixture();evidence={'passes':[]}
                with patch.object(observe,'_crop_text',side_effect=self.read(mode)):
                    observe._recover_map_labels(image,rows,None,None,evidence)
                self.assertFalse(any(p['preprocessing'].endswith(('_white190_2x','_white230_4x'))
                                     for p in rows[-1]['provenance']))
                self.assertEqual(rows[-1]['text'],'Antiutn')

    def test_modal_incomplete_menu_and_absent_white_pixels_limit_work(self):
        for mode in ('modal','menu','no_white'):
            image,rows=self.fixture()
            if mode=='modal':rows.append(row('OK',x=310,y=300,w=22))
            elif mode=='menu':rows.pop(0)
            else:image=Image.new('RGB',(640,480),(70,80,90))
            with patch.object(observe,'_crop_text',side_effect=self.read()) as crop:
                observe._recover_map_labels(image,rows,None,None,{'passes':[]})
            self.assertEqual(crop.call_count,2 if mode=='no_white' else 0)

    def test_original_012782_reads_antium_without_replacing_source_pixels(self):
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-012/screens/ui-0000782.png'
        if not path.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original map unavailable')
        before=path.read_bytes();o=observe.recognize(path)
        label=next(r for r in o['lines'] if r['text']=='Antium')
        readings={p['preprocessing']:p for p in label['provenance']}
        for suffix in ('_white190_2x','_white230_4x'):
            actual=[p for name,p in readings.items() if name.endswith(suffix)]
            self.assertEqual(len(actual),1);self.assertEqual(actual[0]['text'],'Antium')
            self.assertEqual(actual[0]['confidence'],1)
        self.assertEqual(label['provenance'][0]['text'],'Antumn')
        self.assertEqual(o['sha256'],hashlib.sha256(before).hexdigest())
        self.assertEqual(path.read_bytes(),before)
        footer=next(r for r in o['lines'] if r['text']=='End of Turn')
        self.assertEqual(footer['provenance'][0]['preprocessing'],'exact_original_gray_footer_rgb_sha256')
        # The name and the separate exact-pixel gray footer proof together
        # establish this original end-turn frame.
        from civ2.memory import parse_memory
        from civ2.run import game_text,labels_text
        state=parse_memory((root/'runs/attempt-012/observations/d000133.json').read_bytes())
        d=classify_dialog(o,state=state,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d)
        self.assertEqual(d['kind'],'end_turn')


if __name__=='__main__':unittest.main()
