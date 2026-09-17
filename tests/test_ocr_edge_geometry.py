"""Subpixel OCR origins retain raw geometry; invalid rectangles still reject."""
from pathlib import Path
import unittest
from civ2.observe import _prepare_rows


class OCREdgeGeometry(unittest.TestCase):
    def raw(self,**changes):
        return dict(text='TEST edge',confidence=1,x=.1,y=.1,width=.1,height=.05,**changes)

    def test_subpixel_negative_origin_is_intersected_and_preserved(self):
        for key,size in (('x',640),('y',480)):
            original=self.raw();original[key]=-.2/size
            r=_prepare_rows([original],640,480,'TEST native')[0]
            self.assertEqual(r['bounds'][0 if key=='x' else 1],0)
            proof=r['provenance'][0]
            self.assertEqual(proof['edge_clamp']['raw_normalized_bounds'],
                             [original[k] for k in ('x','y','width','height')])
            self.assertAlmostEqual(proof['normalized_bounds'][2 if key=='x' else 3],
                                   original['width' if key=='x' else 'height']+original[key])

    def test_substantive_negative_or_other_invalid_geometry_rejects(self):
        cases=[{'x':-1.01/640},{'y':-1.01/480},{'width':float('nan')},
               {'width':-0.1},{'width':1.1},{'x':.99,'width':.1},
               {'y':.99,'height':.1},{'x':-0.0001,'width':0.00005}]
        for changes in cases:
            r=self.raw();r.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                _prepare_rows([r],640,480,'TEST native')

    def test_original_research_capture_retains_five_actual_options(self):
        from civ2.observe import recognize
        from civ2.dialogs import classify_dialog
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        path=Path(__file__).resolve().parents[1]/'runs/attempt-012/screens/ui-0000128.png'
        if not path.exists():self.skipTest('Private original capture unavailable')
        o=recognize(path);d=classify_dialog(o,rules=parse_rules(original_rules()))
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'research_choice')
        self.assertEqual(len(d['options']),5)
        clamped=[r for r in o['lines'] if r['text']=='Leame']
        self.assertEqual(len(clamped),1)
        self.assertLess(clamped[0]['provenance'][0]['edge_clamp']['raw_normalized_bounds'][0],0)


if __name__=='__main__':unittest.main()
