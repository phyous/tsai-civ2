"""Synthetic radio layout cases plus an optional retained original capture."""
from copy import deepcopy
from pathlib import Path
import unittest
from test_dialogs import row,observation
from civ2.dialogs import classify_dialog

SOURCE='@BUILT\n@title=Domestic Advisor\n%STRING0 %STRING3 %STRING1.\n'
STATE={'cities':[{'name':'TEST Cumae'}]}
RULES={'units':[{'name':'TEST Settlers'}]}


class CompletionRadioArtTests(unittest.TestCase):
    def test_two_tight_pixel_reads_resolve_a_disagreeing_wider_pair(self):
        from unittest.mock import patch
        from PIL import Image
        from civ2 import observe
        from tests.test_herald import prepared
        for case in ('valid','tight_disagree','weak','distant'):
            values=[prepared('Domestic Advisor',255,166,135,16),prepared('Loom to City',206,216,87,19),prepared('OK',310,298,24,16)]
            good=prepared('Zoom to City',205,218,88,15);other=deepcopy(good)
            if case=='tight_disagree':other['text']='Loom to City'
            if case=='weak':other['confidence']=.5
            if case=='distant':other['bounds'][1]+=12;other['center'][1]+=12
            with patch.object(observe,'_crop_text',side_effect=[[deepcopy(values[1])],[deepcopy(good)],[deepcopy(good)],[other]]):
                observe._recover_completion_zoom(Image.new('RGB',(640,480)),values,None,None,{'passes':[]})
            self.assertEqual(values[1]['text'],'Zoom to City' if case=='valid' else 'Loom to City',case)

    def test_actual_3393_keeps_both_strategic_choices(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        path=Path('runs/attempt-010/screens/ui-0003393.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        o=recognize(path);d=classify_dialog(o,game_text=game_text(),state={'cities':[{'name':'Rome'}]},rules={'units':[{'name':'Settlers'}]})
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual([r['text']for r in d['options']],['Zoom to City','Continue'])
        zoom=next(r for r in o['lines']if r['text']=='Zoom to City')
        self.assertEqual(zoom['provenance'][0]['text'],'Loom to City')
        self.assertTrue(all('tight' in r['preprocessing'] for r in zoom['provenance'][-2:]))

    def fixture(self):
        return observation(row('Domestic Advisor',x=320,y=174,w=112),
            row('TEST Cumae builds TEST Settlers.',x=320,y=199,w=300),
            row('Zoom to City',x=249,y=226,w=86),
            row('O',x=186,y=251,w=16,h=18),
            row('Continue',x=236,y=249,w=60),row('OK',x=320,y=306,w=24))

    def classify(self,o):
        return classify_dialog(o,game_text=SOURCE,state=STATE,rules=RULES)

    def test_complete_labels_remain_two_actual_model_choices(self):
        o=self.fixture();d=self.classify(o)
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['kind'],'production_notice');self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text'] for r in d['options']],['Zoom to City','Continue'])
        self.assertEqual(d['options'][1]['center'],o['lines'][4]['center'])
        self.assertEqual(d['evidence']['completion_notice']['separate_radio_artwork'][0]['text'],'O')

    def test_wrong_glyph_geometry_duplicate_or_missing_label_refuses(self):
        for case in ('word','vertical','horizontal','large','duplicate','missing','extra'):
            o=deepcopy(self.fixture())
            if case=='word':o['lines'][3]['text']='Do'
            elif case=='vertical':o['lines'][3]=row('O',x=186,y=270,w=16,h=18)
            elif case=='horizontal':o['lines'][3]=row('O',x=160,y=251,w=16,h=18)
            elif case=='large':o['lines'][3]=row('O',x=186,y=251,w=24,h=18)
            elif case=='duplicate':o['lines'].append(deepcopy(o['lines'][3]))
            elif case=='missing':o['lines'][4]['text']='Pay gold'
            elif case=='extra':o['lines'].insert(4,row('Pay gold',x=236,y=275,w=70))
            with self.subTest(case=case):self.assertFalse(self.classify(o)['supported'])

    def test_original_separate_radio_circle(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        path=Path(__file__).resolve().parents[1]/'runs/attempt-010/screens/ui-0001304.png'
        if not path.exists():self.skipTest('Private original capture unavailable')
        d=classify_dialog(recognize(path),game_text=game_text(),
                         state={'cities':[{'name':'Cumae'}]},rules={'units':[{'name':'Settlers'}]})
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual([o['text'] for o in d['options']],['Zoom to City','Continue'])


if __name__=='__main__':unittest.main()
