"""A map-layout marker is recovered only from paired original-pixel readings."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest import mock
from PIL import Image
from civ2 import observe


def row(text,x,y,w=78,h=16):
    return dict(text=text,bounds=[x,y,w,h],center=[x+w/2,y+h/2],confidence=1,
                provenance=[{'preprocessing':'native','text':text}])


def panel():
    return [row('Roman Wap',192,46),row('World',531,46,42),row('Status',531,182,42),
            row('Game Kingdom View Orders Advisors World Cheat Civilopedia',8,20,488)]


class MapHeadingPixelTests(unittest.TestCase):
    def test_requires_two_exact_readings_at_same_original_location(self):
        for mutation in ('none','disagree','wrong_text','low_confidence','moved','extra'):
            rows=panel();a=row('Roman Map',189,45,81);b=deepcopy(a)
            if mutation=='disagree':b['text']='Roman Hap'
            if mutation=='wrong_text':a['text']=b['text']='Roman Hap'
            if mutation=='low_confidence':b['confidence']=.5
            if mutation=='moved':b=row('Roman Map',189,90)
            second=[b,row('Extra',189,65)] if mutation=='extra' else [b]
            with mock.patch('civ2.observe._crop_text',side_effect=[[a],second,[a],second]):
                observe._recover_map_heading(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[0]['text'],'Roman Map' if mutation=='none' else 'Roman Wap')
            self.assertEqual(rows[0]['provenance'][0]['text'],'Roman Wap')
            if mutation=='none':self.assertEqual(len(rows[0]['provenance']),3)

    def test_bounded_second_scale_still_requires_exact_agreeing_full_title(self):
        for mutation in ('none','disagree','wrong','low','moved'):
            rows=panel();rows[0]['text']='Romen Map'
            first=row('Roman Mop',192,45);a=row('Roman Map',192,45);b=deepcopy(a)
            if mutation=='disagree':b['text']='Roman Hap'
            if mutation=='wrong':a['text']=b['text']='Roman Mop'
            if mutation=='low':b['confidence']=.5
            if mutation=='moved':b=row('Roman Map',192,90)
            with mock.patch('civ2.observe._crop_text',side_effect=[[first],[first],[a],[b]]):
                observe._recover_map_heading(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[0]['text'],'Roman Map' if mutation=='none' else 'Romen Map',mutation)
            if mutation=='none':self.assertEqual(len(rows[0]['provenance']),5)

    def test_actual_romen_heading_keeps_all_competing_reads(self):
        path=Path('runs/attempt-011/screens/ui-0003287.png')
        if not path.exists():self.skipTest('Private original calibration image unavailable')
        result=observe.recognize(path)
        heading=next(r for r in result['lines'] if r['text']=='Roman Map')
        self.assertEqual(heading['provenance'][0]['text'],'Romen Map')
        self.assertEqual(sorted(p['text'] for p in heading['provenance'][1:]),
                         ['Roman Map','Roman Map','Roman Mop','Roman Mop'])

    def test_title_and_other_pane_anchors_must_be_observed(self):
        for mutation in ('valid','far_text','other_geometry','missing_world','missing_status','missing_menu','duplicate'):
            rows=panel()
            if mutation=='valid':rows[0]['text']='Roman Map'
            if mutation=='far_text':rows[0]['text']='Roman Military'
            if mutation=='other_geometry':rows[0]=row('Roman Wap',192,100)
            if mutation=='missing_world':rows.pop(1)
            if mutation=='missing_status':rows.pop(2)
            if mutation=='missing_menu':rows.pop(3)
            if mutation=='duplicate':rows.append(deepcopy(rows[0]))
            with mock.patch('civ2.observe._crop_text') as crop:
                observe._recover_map_heading(Image.new('RGB',(640,480)),rows,None,None,{})
            crop.assert_not_called()

    def test_actual_original_map_title_keeps_raw_reading_and_image_hash(self):
        path=Path('runs/attempt-012/screens/ui-0001678.png')
        if not path.exists():self.skipTest('Private original calibration image unavailable')
        result=observe.recognize(path)
        rows=[r for r in result['lines'] if r['text']=='Roman Map']
        self.assertEqual(len(rows),1)
        self.assertEqual([p['text'] for p in rows[0]['provenance']],['Roman Wap','Roman Map','Roman Map'])
        self.assertEqual([p['preprocessing'] for p in rows[0]['provenance'][1:]],['map_heading_rgb3','map_heading_gray3'])


if __name__=='__main__':unittest.main()
