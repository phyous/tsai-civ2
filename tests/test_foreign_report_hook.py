"""Full classifier integration for the separate source-bound F3 helper."""
from pathlib import Path
import unittest
from unittest.mock import patch
from civ2.dialogs import classify_dialog
from test_foreign_report import fixture


class ForeignReportHookTests(unittest.TestCase):
    def test_three_real_button_choices_survive_dispatch(self):
        observation,resources,rules,labels=fixture()
        source='@REPORTFOREIGN\n@width=580\n@title=Foreign Minister\n@button=Check Intelligence\n@button=Send Emissary\n'+resources[0]['body']+'\n'
        with patch('civ2.foreign_report._pixels',return_value=[]):
            result=classify_dialog(observation,rules=rules,game_text=source,labels_text=labels)
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['kind'],'foreign_minister')
        self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
        self.assertEqual([x['text'] for x in result['options']],['Check Intelligence','Send Emissary','Cancel'])
        self.assertTrue(all(x['control']=='button' for x in result['options']))

    def test_actual_german_report_keeps_raw_title_and_three_button_centers(self):
        path=Path('runs/attempt-010/screens/ui-0001942.png')
        if not path.exists():self.skipTest('Private original capture unavailable')
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.observe import recognize
        before=path.read_bytes();observation=recognize(path);observation['path']=str(path)
        result=classify_dialog(observation,rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['title'],'Foreign Minisber')
        self.assertEqual([x['center'] for x in result['options']],[[126,282],[321,282],[519,281]])
        self.assertEqual(result['evidence']['foreign_report']['selected_contact'],{'leader':'Frederick','tribe':'Germans'})
        self.assertEqual(path.read_bytes(),before)
