"""Synthetic TEST native arrow pixels and optional original panel fixtures."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2.tax_controls import COLORS,PATTERNS,annotate_tax_controls,proven_tax_arrows
from civ2.dialogs import classify_dialog
from tests.test_dialogs import row,observation

LABELS='\n'.join(['How Shall We Distribute The Wealth','Government','Maximum Rate','Taxes','Science','Luxuries','Lock'])

def image_and_rows():
    image=Image.new('RGB',(640,480),(90,60,70))
    rows=[row('How Shall We Distribute The Wealth',x=320,y=110,w=240),
          row('Government: Monarchy Maximum Rate: 70%',x=300,y=140,w=290),
          row('Total Income: 5 Total Cost: 0',x=300,y=177,w=188),
          row('Discoveries: 6 Turns',x=300,y=198,w=128)]
    for text,y in [('Taxes: 40%',234),('Science: 60%',276),('Luxuries: 0%',318)]:
        rows.extend([row('0%',x=140,y=y,w=24,h=12),row(text,x=300,y=y,w=90,h=12),row('100%',x=450,y=y,w=40,h=12)])
        for direction,x in [('left',131),('right',452)]:
            for yy,line in enumerate(PATTERNS[direction]):
                for xx,c in enumerate(line):image.putpixel((x+xx,y+9+yy),COLORS[c])
    rows.append(row('OK',x=320,y=364,w=26))
    annotate_tax_controls(image,rows,'a'*64)
    return image,rows

class TaxControlsTests(unittest.TestCase):
    def test_title_recovery_requires_paired_pixels_and_preserves_rates(self):
        from civ2 import observe
        from tests.test_herald import prepared
        original=prepared('Fow Shall We Dictmbote The Wealth',208,102,226,16)
        good=prepared('How Shall We Distribote The Wealth',208,102,226,16)
        for case in ('good','different','weak','extra','missing_rate','wrong_geometry'):
            rows=[copy.deepcopy(original),prepared('Taxes: 40%',264,228,70,16),
                  prepared('Science: 60%',250,270,85,16),prepared('Luxuries: 0%',250,312,85,16),
                  prepared('OK',308,355,24,16)]
            b=copy.deepcopy(good)
            if case=='different':b['text']='How Shall We Destroy The Wealth'
            if case=='weak':b['confidence']=.5
            if case=='extra':rows.append(prepared('Cancel',400,355,50,16))
            if case=='missing_rate':rows.pop(2)
            if case=='wrong_geometry':b=prepared(good['text'],208,150,226,16)
            with patch.object(observe,'_crop_text',side_effect=[[good],[b]]):
                observe._recover_tax_context(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],good['text'] if case=='good' else original['text'],case)
            self.assertIn('Taxes: 40%',[r['text'] for r in rows])
            if case=='good':self.assertEqual(rows[0]['provenance'][0]['text'],original['text'])

    def test_split_rate_joins_only_unique_adjacent_actual_number(self):
        from civ2 import observe
        from tests.test_herald import prepared
        for case in ('good','distant','ambiguous','weak'):
            label=prepared('Taxes:',264,228,42,12)
            value=prepared('50%',304,226,34,16)
            if case=='distant':value=prepared('50%',350,226,34,16)
            if case=='weak':value['confidence']=.5
            rows=[label,value]
            if case=='ambiguous':rows.append(prepared('60%',309,226,34,16))
            with patch.object(observe,'_crop_text',return_value=[]):
                observe._recover_tax_context(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            joined=[r for r in rows if r['text']=='Taxes: 50%']
            self.assertEqual(len(joined),int(case=='good'))
            if joined:self.assertEqual([p['text'] for p in joined[0]['provenance']],['Taxes:','50%'])
    def test_exact_six_patterns_and_seven_actual_controls(self):
        _,rows=image_and_rows();o=observation(*rows)
        r=classify_dialog(o,labels_text=LABELS)
        self.assertEqual(r['kind'],'tax_allocation',r);self.assertTrue(r['requires_model'])
        self.assertEqual(len(r['options']),7);self.assertTrue(all(x['control']=='button' for x in r['options']))
        self.assertEqual(r['options'][2]['center'],[139,293])
        self.assertEqual(r['options'][-1]['text'],'OK')
        self.assertEqual(r['tax_allocation']['rates'],{'taxes':40,'science':60,'luxuries':0})
        self.assertFalse(classify_dialog(o)['supported'])
    def test_altered_arrow_pixel_rejects_and_duplicate_location_is_ambiguous(self):
        for case in ('pixel','duplicate'):
            image,rows=image_and_rows()
            for r in rows:r.pop('native_tax_arrows',None)
            if case=='pixel':image.putpixel((139,251),(255,0,0))
            else:
                for yy,line in enumerate(PATTERNS['left']):
                    for xx,c in enumerate(line):image.putpixel((170+xx,243+yy),COLORS[c])
            annotate_tax_controls(image,rows,'a'*64)
            self.assertFalse(classify_dialog(observation(*rows),labels_text=LABELS)['supported'])
    def test_hash_geometry_missing_row_and_inconsistent_rates_fail_closed(self):
        for case in ('hash','geometry','pattern','missing','total','limit','unknown','extra'):
            _,rows=image_and_rows();o=observation(*rows)
            rate=next(r for r in rows if r['text']=='Taxes: 40%')
            if case=='hash':rate['native_tax_arrows']['source_sha256']='b'*64
            elif case=='geometry':rate['native_tax_arrows']['controls'][0]['bounds'][0]+=1
            elif case=='pattern':rate['native_tax_arrows']['controls'][0]['pattern'][0]='W'*17
            elif case=='missing':rows.remove(rate);o['lines']=rows
            elif case=='total':rate['text']='Taxes: 50%'
            elif case=='limit':rows[1]['text']='Government: Monarchy Maximum Rate: 30%'
            elif case=='unknown':rows[0]['text']='TEST unknown allocation warning'
            else:rows.append(row('Pay TEST gold',x=300,y=210,w=90));o['lines']=rows
            # Row geometry is part of the source evidence, not a movable hint.
            if case=='geometry':
                rate['native_tax_arrows']['row_bounds'][0]+=1
            self.assertFalse(classify_dialog(o,labels_text=LABELS)['supported'],case)
    def test_optional_actual_two_original_panels(self):
        root=Path(__file__).resolve().parents[1]
        paths=[root/'runs/attempt-004/screens/ui-0000789.png',root/'runs/attempt-005/screens/ui-0001240.png',
               root/'runs/attempt-006/screens/ui-0001133.png']
        if not all(p.exists() for p in paths) or not(root/'.runtime/ocr').exists():self.skipTest('Private original panels unavailable')
        from civ2.observe import recognize
        from civ2.run import labels_text
        for path in paths:
            o=recognize(path);r=classify_dialog(o,labels_text=labels_text())
            self.assertTrue(r['supported'],r);self.assertEqual(len(r['options']),7)
            self.assertEqual([x['center'] for x in r['options'][:6]],[[139,251],[460,251],[139,293],[460,293],[139,335],[460,335]])

    def test_optional_calibrated_native_adjustment_and_pointer_occlusion(self):
        root=Path(__file__).resolve().parents[1]
        paths=[root/f'.runtime/tax-slider-calibration/ui-{n:07}.png' for n in (5,7,8)]
        if not all(p.exists() for p in paths) or not(root/'.runtime/ocr').exists():self.skipTest('Private calibration frames unavailable')
        from civ2.observe import recognize
        from civ2.run import labels_text
        occluded,adjusted,restored=[classify_dialog(recognize(p),labels_text=labels_text()) for p in paths]
        self.assertFalse(occluded['supported'])
        self.assertEqual(adjusted['tax_allocation']['rates'],{'taxes':50,'science':50,'luxuries':0})
        self.assertEqual(restored['tax_allocation']['rates'],{'taxes':40,'science':60,'luxuries':0})

if __name__=='__main__':unittest.main()
