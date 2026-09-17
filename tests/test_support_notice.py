from copy import deepcopy
from pathlib import Path
import unittest
from test_dialogs import row, observation
from civ2.dialogs import classify_dialog

SOURCE="@SUPPORT\n@title=Military Advisor\n%STRING0 can't support %STRING1. Unit disbanded.\n"
STATE={'cities':[{'name':'TEST Rome'}]}
RULES={'units':[{'name':'TEST Settlers'}]}

class SupportNoticeTests(unittest.TestCase):
    def fixture(self):
        return observation(row('Military Advisor',x=320,y=174,w=110),
            row("TEST Rome can't support TEST Settlers. Unit disbanded.",x=320,y=199,w=390),
            row('Zoom to City',x=250,y=225,w=90),row('Continue',x=235,y=250,w=65),
            row('OK',x=320,y=305,w=24))

    def test_support_loss_keeps_both_real_choices(self):
        d=classify_dialog(self.fixture(),game_text=SOURCE,state=STATE,rules=RULES)
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['kind'],'support_loss_notice');self.assertEqual(d['resource_tag'],'SUPPORT')
        self.assertEqual([o['text'] for o in d['options']],['Zoom to City','Continue'])

    def test_changed_body_city_unit_or_controls_refuse(self):
        for index,text in ((1,"TEST Rome can't support TEST Palace. Unit disbanded."),
                           (1,"TEST Enemy can't support TEST Settlers. Unit disbanded."),
                           (1,"TEST Rome can't support TEST Settlers. Pay 50 gold."),
                           (3,'Pay gold'),(0,'Domestic Advisor')):
            o=deepcopy(self.fixture());o['lines'][index]['text']=text
            self.assertFalse(classify_dialog(o,game_text=SOURCE,state=STATE,rules=RULES)['supported'])
        self.assertFalse(classify_dialog(self.fixture(),state=STATE,rules=RULES)['supported'])

    def test_actual_original_support_notice(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        path=Path('runs/attempt-009/screens/ui-0000357.png')
        if not path.exists():self.skipTest('Private original capture unavailable')
        d=classify_dialog(recognize(path),game_text=game_text(),
            state={'cities':[{'name':'Rome'}]},rules={'units':[{'name':'Settlers'}]})
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'SUPPORT')
        self.assertTrue(d['requires_model']);self.assertEqual(len(d['options']),2)
