"""A blank native caption requires the rest of the complete city layout."""
from copy import deepcopy
from pathlib import Path
import unittest
from civ2.dialogs import classify_dialog
from tests.test_dialogs import observation,row


def complete_city():
    locations=[('Food Storage',539,67),('Citizens',103,112),('City Resources',321,112),
        ('Resource Map',104,254),('Units Present',317,284),('City Improvements',100,356),
        ('Buy',478,252),('Change',595,252),('Info',490,434),('Map',548,435),
        ('Rename',607,434),('Happy',490,461),('View',548,459),('Exit',607,459)]
    return observation(row('City of TEST Rome, 2600 B.C., Population 30,000',x=320,y=48,w=410),
        *[row(text,x=x,y=y,w=min(100,len(text)*6),h=12) for text,x,y in locations])


class CityLayoutTests(unittest.TestCase):
    def test_blank_caption_does_not_invent_heading_or_city_values(self):
        o=complete_city();result=classify_dialog(o)
        self.assertTrue(result['supported'],result);self.assertEqual(result['kind'],'city_screen')
        self.assertEqual(result['title'],o['lines'][0]['text'])
        self.assertNotIn('Units Supported',result['visible_text'])
        proof=result['evidence']['city_layout'];self.assertEqual(proof['missing_caption'],'Units Supported')
        self.assertEqual(proof['source_sha256'],o['sha256']);self.assertEqual(len(proof['observed_anchors']),14)
        self.assertEqual(len(result['buttons']),8);self.assertTrue(result['requires_model'])
        self.assertNotIn('population',result)

    def test_missing_or_shifted_anchor_and_partial_caption_fail_closed(self):
        for case in ('second_missing','button_missing','button_shifted','low_confidence','partial','title_missing','title_duplicate'):
            o=complete_city()
            if case=='second_missing':o['lines']=[r for r in o['lines'] if r['text']!='Food Storage']
            elif case=='button_missing':o['lines']=[r for r in o['lines'] if r['text']!='Rename']
            elif case=='button_shifted':
                r=next(r for r in o['lines'] if r['text']=='View');r['center'][1]-=100;r['bounds'][1]-=100
            elif case=='low_confidence':next(r for r in o['lines'] if r['text']=='Info')['confidence']=.4
            elif case=='partial':o['lines'].append(row('Units Sup',x=90,y=284,w=70))
            elif case=='title_missing':o['lines']=o['lines'][1:]
            elif case=='title_duplicate':o['lines'].append(deepcopy(o['lines'][0]))
            with self.subTest(case=case):self.assertFalse(classify_dialog(o)['supported'])

    def test_modal_guards_still_reject_complete_background_layout(self):
        for text in ('OK','Cancel','Please choose an improvement','Are you sure?','Warning'):
            o=complete_city();o['lines'].append(row(text,x=320,y=190,w=180))
            with self.subTest(text=text):self.assertFalse(classify_dialog(o)['supported'])

    def test_actual_blank_caption_city_keeps_raw_observed_title(self):
        from civ2.observe import recognize
        path=Path(__file__).resolve().parents[1]/'runs/attempt-008/screens/ui-0000279.png'
        if not path.exists():self.skipTest('Private original calibration image unavailable')
        o=recognize(path);r=classify_dialog(o)
        self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],'city_screen')
        self.assertEqual(len(r['buttons']),8)
        self.assertEqual(r['title'],next(x['text'] for x in o['lines'] if x['text'].startswith('City of Rome')))
        self.assertEqual(r['evidence']['city_layout']['source_sha256'],o['sha256'])

if __name__=='__main__':unittest.main()
