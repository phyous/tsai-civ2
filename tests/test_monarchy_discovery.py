"""A discovery acknowledgement cannot select a government or political action."""
from copy import deepcopy
from pathlib import Path
import unittest
from civ2.dialogs import classify_dialog
from tests.test_dialogs import observation,row

SOURCE='''@CIVADVANCE
@title=Civilization Advance
@width=320
%STRING0 %STRING1 discover the secret of %STRING2.
'''


class MonarchyDiscovery(unittest.TestCase):
    def fixture(self):
        return observation(row('Cinlization Advance',x=322,y=203,w=124,h=14),
                           row('Roman wise men discover the secret of',x=333,y=226,w=262,h=16),
                           row('Monarchy.',x=237,y=249,w=78,h=18),
                           row('OK',x=320,y=277,w=24,h=14))

    def test_measured_title_preserves_body_and_only_acknowledges(self):
        d=classify_dialog(self.fixture(),game_text=SOURCE)
        self.assertTrue(d['supported'],d)
        self.assertEqual(d['resource_tag'],'CIVADVANCE')
        self.assertEqual(d['kind'],'information')
        self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertFalse(d['requires_model'])
        self.assertEqual(d['title'],'Cinlization Advance')
        self.assertEqual(d['evidence']['observed_body'],'Roman wise men discover the secret of\nMonarchy.')
        self.assertEqual([o['text'] for o in d['options']],['OK'])

    def test_incomplete_body_added_choice_or_political_text_cannot_acknowledge(self):
        for mode in ('missing_advance','missing_discovery','political','extra_choice','duplicate_ok'):
            o=deepcopy(self.fixture())
            if mode=='missing_advance':o['lines'].pop(2)
            elif mode=='missing_discovery':o['lines'].pop(1)
            elif mode=='political':o['lines'][1]['text']='What form of government shall we adopt?'
            elif mode=='extra_choice':o['lines'].append(row('Revolution',x=430,y=254,w=65))
            else:o['lines'].append(row('OK',x=480,y=277,w=24))
            d=classify_dialog(o,game_text=SOURCE)
            self.assertFalse(d['supported'],(mode,d))
            self.assertIsNone(d['mechanical_action'])

    def test_original_012663_full_source_resource_and_two_lines(self):
        path=Path(__file__).resolve().parents[1]/'runs/attempt-012/screens/ui-0000663.png'
        if not path.exists():self.skipTest('Private original discovery frame unavailable')
        from civ2.observe import recognize
        from civ2.run import game_text
        d=classify_dialog(recognize(path),game_text=game_text())
        self.assertTrue(d['supported'],d)
        self.assertEqual(d['resource_tag'],'CIVADVANCE')
        self.assertEqual(d['evidence']['observed_body'],'Roman wise men discover the secret of\nMonarchy.')
        self.assertEqual(d['title'],'Cinlization Advance')
        self.assertFalse(d['requires_model'])
        self.assertEqual([o['text'] for o in d['options']],['OK'])


if __name__=='__main__':unittest.main()
