"""Synthetic OCR evidence and optional original image for a clipped menu glyph."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest import mock
from PIL import Image
from civ2.observe import _recover_map_menu_label


def row(text,x=16,y=24,w=30,h=10):
    return dict(text=text,bounds=[x,y,w,h],center=[x+w/2,y+h/2],confidence=1,
                provenance=[{'preprocessing':'native','text':text}])


def menu():
    return [row('ame')]+[row(text,60+i*75) for i,text in enumerate(
        ('Kingdom','View','Orders','Advisors','Civilopedia'))]


class MenuLabelPixelsTests(unittest.TestCase):
    def test_two_complete_same_location_reads_preserve_raw_text(self):
        rows=menu(); a=row('Game',10,21,36,14);b=deepcopy(a)
        with mock.patch('civ2.observe._crop_text',side_effect=[[a],[b]]):
            _recover_map_menu_label(Image.new('RGB',(640,480)),rows,None,None,{})
        self.assertEqual(rows[0]['text'],'Game')
        self.assertEqual([p['text'] for p in rows[0]['provenance']],['ame','Game','Game'])

    def test_disagreement_low_confidence_or_different_location_reject(self):
        for case in ('disagree','confidence','location','multiple'):
            rows=menu();a=row('Game');b=deepcopy(a)
            if case=='disagree':b['text']='Gane'
            if case=='confidence':b['confidence']=.4
            if case=='location':b=row('Game',100,150)
            reads=[[a],[b,b] if case=='multiple' else [b]]
            with mock.patch('civ2.observe._crop_text',side_effect=reads):
                _recover_map_menu_label(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[0]['text'],'ame')

    def test_other_pane_missing_peer_and_duplicate_do_not_trigger(self):
        for case in ('pane','peer','duplicate'):
            rows=menu()
            if case=='pane':rows[0]=row('ame',16,150)
            if case=='peer':rows.pop()
            if case=='duplicate':rows.append(deepcopy(rows[0]))
            with mock.patch('civ2.observe._crop_text') as crop:
                _recover_map_menu_label(Image.new('RGB',(640,480)),rows,None,None,{})
            crop.assert_not_called()

    def test_actual_original_menu_glyph(self):
        from civ2.observe import recognize
        p=Path(__file__).resolve().parents[1]/'runs/attempt-010/screens/ui-0001574.png'
        if not p.exists():self.skipTest('Private original calibration image unavailable')
        result=recognize(p)
        r=next(r for r in result['lines'] if r['text']=='Game')
        self.assertEqual([p['text'] for p in r['provenance']],['ame','Game','Game'])


if __name__=='__main__':unittest.main()
