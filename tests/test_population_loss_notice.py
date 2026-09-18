from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.dialogs import classify_dialog
from test_dialogs import row,observation
from test_herald import prepared

SOURCE='@DECREASE\n@title=Domestic Advisor\nPopulation decrease in %STRING0.\n\n@BUILT\n@title=Domestic Advisor\n%STRING0 %STRING3 %STRING1\n'
STATE={'cities':[{'name':'TEST Neapolis'}]}

class PopulationLossNotice(unittest.TestCase):
    def fixture(self):
        return observation(row('Domestic Advisor',x=320,y=186,w=114),
            row('Population decrease in TEST Neapolis.',x=260,y=210,w=320),
            row('Zoom to City',x=180,y=238,w=90),row('Continue',x=169,y=261,w=61),
            row('OK',x=320,y=295,w=26))

    def test_actual_both_options_require_jev_and_complete_known_city(self):
        for case in ('valid','body','city','missing','extra','source','title'):
            o=self.fixture();game=SOURCE
            if case=='body':o['lines'][1]['text']='Population increase in TEST Neapolis.'
            if case=='city':o['lines'][1]['text']='Population decrease in Enemy.'
            if case=='missing':o['lines'].pop(2)
            if case=='extra':o['lines'].append(row('Pay 20 gold',x=250,y=280,w=90))
            if case=='source':game=SOURCE.replace('Population decrease','Population increase')
            if case=='title':o['lines'][0]['text']='Military Advisor'
            d=classify_dialog(o,game_text=game,state=STATE,rules={})
            self.assertEqual(d['supported'],case=='valid',(case,d))
            if case=='valid':
                self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
                self.assertEqual(d['kind'],'population_loss_notice');self.assertEqual(d['resource_tag'],'DECREASE')
                self.assertEqual([v['text'] for v in d['options']],['Zoom to City','Continue'])

    def test_accented_radio_recovery_needs_both_complete_readings(self):
        for case in ('valid','disagree','weak','body'):
            rows=[prepared('Domestic Advisor',263,180,114,13),prepared('Population decrease in Neapolis.',100,202,220,16),
                prepared('• Zoom to City',110,229,115,17),prepared('O Contínue',110,252,90,19),prepared('OK',308,288,26,14)]
            a=prepared('Continue',138,254,61,14);b=deepcopy(a)
            if case=='disagree':b['text']='Cancel'
            if case=='weak':b['confidence']=.5
            if case=='body':rows[1]['text']='Population increase in Neapolis.'
            with patch.object(observe,'_crop_text',side_effect=[[a],[b]]):
                observe._recover_population_decrease_option(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[3]['text'],'Continue' if case=='valid' else 'O Contínue')
            self.assertEqual(rows[3]['provenance'][0]['text'],'O Contínue')

    def test_original_population_loss_keeps_both_strategic_choices(self):
        p=Path('runs/attempt-012/screens/ui-0002263.png')
        if not p.exists():self.skipTest('Private original unavailable')
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text(),state={'cities':[{'name':'Neapolis'}]},rules={})
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual([v['text'] for v in d['options']],['Zoom to City','Continue'])
        self.assertEqual(d['resource_tag'],'DECREASE')

if __name__=='__main__':unittest.main()
