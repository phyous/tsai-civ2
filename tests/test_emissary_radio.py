"""TEST detached radio geometry; exact original option text remains mandatory."""
from copy import deepcopy
from pathlib import Path
import unittest
from civ2.dialogs import classify_dialog
from tests.test_dialogs import row,observation

SOURCE='''@EMISSARY
@width=320
@title=%STRING0 Emissary
An emissary from %STRING1 %STRING2 of the %STRING3 wishes to speak with you. Will you receive %STRING4?

"Yes. I will grant an audience."
"No. Send %STRING4 away."
'''

def audience():
    return observation(row('Neutral TEST Emissary',y=165,w=150),
        row('An emissary from TEST Leader of the',x=303,y=190,w=286),
        row('TEST people wishes to speak with you. Will you',x=308,y=210,w=296),
        row('receive her?',x=201,y=231,w=88),
        row('"Yes. I will grant an audience."',x=301,y=256,w=214,h=20),
        row('O',x=177,y=257,w=18,h=18),
        row('• "No. Send her away."',x=258,y=282,w=176,h=20),row('OK',y=315,w=24))

class EmissaryRadio(unittest.TestCase):
    def test_detached_radio_does_not_change_actual_choice_or_hitpoint(self):
        d=classify_dialog(audience(),game_text=SOURCE)
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual([o['text'] for o in d['options']],['"Yes. I will grant an audience."','• "No. Send her away."'])
        self.assertEqual(d['options'][0]['center'],[301,256])
        marker=d['evidence']['detached_radio_markers'][0]
        self.assertEqual(marker['marker_source_line'],5);self.assertEqual(marker['label_source_line'],4)

    def test_stray_ambiguous_marker_or_non_source_alternative_stays_unknown(self):
        for case in ('far_y','right','overlap','large','low_confidence','duplicate','wrong_choice','missing_choice','body'):
            with self.subTest(case=case):
                o=audience();r=o['lines'][5]
                if case=='far_y':r.update(center=[177,242],bounds=[168,233,18,18])
                elif case=='right':r.update(center=[423,257],bounds=[414,248,18,18])
                elif case=='overlap':r.update(center=[195,257],bounds=[186,248,18,18])
                elif case=='large':r['bounds'][2]=28
                elif case=='low_confidence':r['confidence']=.5
                elif case=='duplicate':o['lines'].append(deepcopy(r))
                elif case=='wrong_choice':o['lines'][4]['text']='"Yes. Pay 100 TEST gold."'
                elif case=='missing_choice':o['lines'].pop(6)
                elif case=='body':o['lines'][3]['text']='receive her? Give all your TEST gold.'
                self.assertFalse(classify_dialog(o,game_text=SOURCE)['supported'])

    def test_optional_original_009_first_american_audience(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-009/screens/ui-0000515.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original audience frame unavailable')
        d=classify_dialog(recognize(p),game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EMISSARY')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([o['text'] for o in d['options']],['"Yes. I will grant an audience."','• "No. Send him away."'])
        self.assertEqual(d['options'][0]['center'],[301,256])

    def test_measured_question_mark_suffix_requires_matching_refusal(self):
        o=audience();o['lines'][3]['text']='receive hert'
        d=classify_dialog(o,game_text=SOURCE)
        self.assertTrue(d['supported'],d)
        self.assertEqual(d['evidence']['audience_pronoun_reading']['observed_suffix'],'hert')
        o['lines'][6]['text']='• "No. Send him away."'
        self.assertFalse(classify_dialog(o,game_text=SOURCE)['supported'])
        o['lines'][6]['text']='• "No. Send her away."';o['lines'][3]['text']='receive hert extra TEST terms'
        self.assertFalse(classify_dialog(o,game_text=SOURCE)['supported'])

if __name__=='__main__':unittest.main()
