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
