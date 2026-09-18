"""Per-classification source reuse never shares catalogs across observations."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from civ2.dialogs import classify_dialog, dialog_resources, DialogObservationError
from tests.test_dialogs import list_dialog, native_map, RULES, ROMAN_STATE
from tests.test_native_events import notice
from tests.test_space_notices import GAME, DATA
from tests.test_tax_controls import image_and_rows, LABELS
from tests.test_dialogs import observation


class DialogSourceReuse(unittest.TestCase):
    def test_complete_notices_preserve_all_source_records_and_independent_results(self):
        for tag, (title, _, body) in DATA.items():
            with self.subTest(tag=tag):
                screen = notice(*body, title=title)
                source_records = dialog_resources(GAME)
                before = deepcopy(source_records)
                with patch('civ2.dialogs.dialog_resources', return_value=source_records) as parser:
                    result = classify_dialog(screen, game_text=GAME)
                parser.assert_called_once_with(GAME)
                self.assertEqual(source_records, before)
                self.assertTrue(result['supported'], result)
                self.assertEqual(result['resource_tag'], tag)
                self.assertEqual([o['text'] for o in result['options']], ['OK'])
                self.assertEqual(result['evidence']['observed_body'], '\n'.join(body))
                self.assertEqual(result['mechanical_action'], 'acknowledge_information')
                self.assertFalse(result['requires_model'])

    def test_map_and_strategic_choice_outputs_keep_existing_fixture_semantics(self):
        for screen, kwargs, kind, choices in (
            (native_map(), {'state': ROMAN_STATE}, 'normal_map', []),
            (list_dialog(), {'rules': RULES}, 'research_choice', ['TEST Alphabet', 'TEST Bronze Working']),
        ):
            with self.subTest(kind=kind), patch('civ2.dialogs.dialog_resources', wraps=dialog_resources) as parser:
                result = classify_dialog(screen, game_text=GAME, **kwargs)
                parser.assert_called_once_with(GAME)
                self.assertTrue(result['supported'], result)
                self.assertEqual(result['kind'], kind)
                self.assertEqual([r['text'] for r in result['options']], choices)
                self.assertEqual(result['requires_model'], bool(choices))

    def test_source_independent_early_branch_and_invalid_observation_do_not_parse(self):
        _, rows = image_and_rows()
        with patch('civ2.dialogs.dialog_resources', side_effect=AssertionError('Unneeded source parse')) as parser:
            result = classify_dialog(observation(*rows), labels_text=LABELS)
            self.assertEqual(result['kind'], 'tax_allocation')
            self.assertEqual(len(result['options']), 7)
            malformed = native_map(); malformed['lines'][0]['bounds'][2] = -1
            with self.assertRaises(DialogObservationError):
                classify_dialog(malformed, game_text=GAME)
            parser.assert_not_called()

    def test_new_call_reparses_changed_source_and_parser_objects_remain_independent(self):
        screen = notice('The space race has not yet begun!', title='Space ships')
        changed = GAME.replace('The space race has not yet begun!', 'The space race has begun!')
        with patch('civ2.dialogs.dialog_resources', wraps=dialog_resources) as parser:
            results = [classify_dialog(screen, game_text=text) for text in (GAME, changed, GAME)]
            self.assertEqual([call.args[0] for call in parser.call_args_list], [GAME, changed, GAME])
        self.assertEqual([r['supported'] for r in results], [True, False, True])
        self.assertEqual(results[0], results[2])
        first, second = dialog_resources(GAME), dialog_resources(GAME)
        first[0]['body'] = 'Changed by caller'
        first[0]['options'].append('Extra choice')
        self.assertNotEqual(first, second)
        self.assertEqual(second, dialog_resources(GAME))


if __name__ == '__main__':
    unittest.main()
