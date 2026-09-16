"""Synthetic badge pixels are layout proof only; no population is decoded."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image,ImageDraw
from civ2.map_badges import annotate_badges,proven_badge
from civ2 import observe


class MapBadgeTests(unittest.TestCase):
    def test_unique_monochrome_border_glyph_is_bound_to_source_hash_and_position(self):
        image=Image.new('RGB',(640,480),'green');draw=ImageDraw.Draw(image)
        draw.rectangle((210,201,220,213),fill='white');draw.line((210,201,220,201),fill='black')
        draw.line((210,201,210,213),fill='black');draw.line((220,201,220,213),fill='black')
        draw.rectangle((215,205,216,212),fill='black')
        row={'text':'1','bounds':[210,202,10,12],'center':[215,208],'confidence':1}
        annotate_badges(image,[row],'a'*64)
        self.assertTrue(proven_badge(row,'a'*64));self.assertFalse(proven_badge(row,'b'*64))
        self.assertEqual(row['map_badge_pixels']['bounds'],[210,201,11,13])
        self.assertNotIn('population',row['map_badge_pixels']);self.assertNotIn('value',row['map_badge_pixels'])
        for changed in ('border','gray','text','position'):
            original=image.copy();candidate={k:deepcopy(v)for k,v in row.items()if k!='map_badge_pixels'}
            if changed=='border':original.putpixel((210,201),(255,255,255))
            elif changed=='gray':original.putpixel((216,205),(128,128,128))
            elif changed=='text':candidate['text']='OK'
            else:candidate.update(bounds=[320,120,10,12],center=[325,126])
            annotate_badges(original,[candidate],'a'*64)
            self.assertNotIn('map_badge_pixels',candidate,changed)

    def test_low_confidence_city_word_needs_two_actual_agreeing_crop_readings(self):
        def row(text,x=220,y=222,width=30,height=16,confidence=1):
            return observe._prepare_rows([{'text':text,'x':x/640,'y':y/480,'width':width/640,'height':height/480,'confidence':confidence}],640,480,'TEST')[0]
        menu=[row(s,x=10+i*60,y=22,width=40) for i,s in enumerate(('Game','Kingdom','View','Orders'))]
        original=row('Veu',confidence=.5);first=row('Vei');gray=row('Veu')
        for peer,accepted in (([first],True),([],False)):
            rows=deepcopy(menu+[original]);readings=[[first],[gray],peer]
            if not accepted:readings.extend([[],[],[]])
            with patch.object(observe,'_crop_text',side_effect=deepcopy(readings)):
                observe._recover_map_labels(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[-1]['confidence'],1 if accepted else .5)
            self.assertEqual(rows[-1]['text'],'Vei' if accepted else 'Veu')

    def test_map_mask_consensus_handles_bad_crop_without_semantic_alias(self):
        def row(text,x=204,y=153,width=71,height=22,confidence=1):
            return observe._prepare_rows([{'text':text,'x':x/640,'y':y/480,'width':width/640,'height':height/480,'confidence':confidence}],640,480,'TEST')[0]
        menu=[row(t,x=10+i*60,y=22,width=40,height=16) for i,t in enumerate(('Game','Kingdom','View','Orders'))]
        original=row('Antium™');good=row('Antium',x=205,y=156,width=57,height=16)
        for changed,expected in ((None,'Antium'),('disagree','Antium™'),('outside','Antium™'),('control','Antium™')):
            rows=deepcopy(menu+[original]);evidence={}
            peer=deepcopy(good)
            if changed=='disagree':peer['text']='Antiuma'
            elif changed=='outside':peer.update(bounds=[350,150,57,16],center=[378,158])
            elif changed=='control':rows.append(row('OK',y=300))
            # The original RGB readings disagree; a malformed threshold190 box
            # does not suppress the two independently agreeing later passes.
            readings=[[row('Antiumnal')],[row('Antium™')],ValueError('bad geometry'),[good],[peer]]
            with patch.object(observe,'_crop_text',side_effect=deepcopy(readings)) as crop:
                observe._recover_map_labels(Image.new('RGB',(640,480)),rows,None,None,evidence)
            self.assertEqual(rows[4]['text'],expected)
            if changed=='control':crop.assert_not_called()
            else:self.assertEqual(evidence['fallback_errors'][0]['error'],'ValueError')
            if changed is None:self.assertEqual(rows[4]['provenance'][0]['text'],'Antium™')

    def test_optional_original_masked_labels_preserve_original_pixels(self):
        root=Path(__file__).resolve().parents[1]
        for relative,raw,expected in (('runs/attempt-004/screens/ui-0000633.png','Antium™','Antium'),
                                      ('runs/attempt-005/screens/ui-0000850.png','Veu','Veii')):
            p=root/relative
            if not p.exists()or not(root/'.runtime/ocr').exists():self.skipTest('Private original label frame unavailable')
            before=p.read_bytes();o=observe.recognize(p)
            candidates=[r for r in o['lines']if r['text']==expected]
            self.assertEqual(len(candidates),1,relative)
            self.assertEqual(candidates[0]['provenance'][0]['text'],raw)
            self.assertGreaterEqual(len(candidates[0]['provenance']),3)
            self.assertEqual(p.read_bytes(),before)

    def test_optional_original_badge_and_low_confidence_city_label(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-006/screens/ui-0000792.png'
        if not p.exists()or not(root/'.runtime/ocr').exists():self.skipTest('Private original badge frame unavailable')
        before=p.read_bytes();o=observe.recognize(p)
        one=next(r for r in o['lines']if r['text']=='1');self.assertTrue(proven_badge(one,o['sha256']))
        name=next(r for r in o['lines']if r['text']=='Vei');self.assertGreaterEqual(name['confidence'],.8)
        self.assertEqual(name['provenance'][0]['text'],'Veu');self.assertEqual(name['provenance'][0]['confidence'],.5)
        self.assertEqual(p.read_bytes(),before)
