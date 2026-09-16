"""Native autosave disabling must be observed and preserve all other options."""
from pathlib import Path
from unittest import TestCase, mock
from civ2.preferences import configure_preferences, checkbox_state, GAME_LABELS


class PreferencesTests(TestCase):
    def ui(self):
        ui=mock.Mock()
        observation={'sha256':'TEST-frame','lines':[{'text':label} for label in (*GAME_LABELS,'OK','Cancel')]}
        ui.observe.return_value=observation;ui.wait.return_value=observation
        ui.select_text.return_value={};ui.game.chord.return_value=[];ui.key.return_value=[]
        return ui

    def states(self, **changes):
        result=dict.fromkeys(GAME_LABELS,True)
        result.update({'Always wait at end of turn':True,'Instant advice':False,'Autosave each turn':False})
        result.update(changes);return result

    def test_already_configured_preferences_are_not_toggled(self):
        ui=self.ui();states=self.states()
        with mock.patch('civ2.preferences.checkbox_state',side_effect=list(states.values())*2):
            result=configure_preferences(ui)
        ui.select_text.assert_not_called()
        self.assertEqual(result['checkbox_before'],result['checkbox_after'])
        self.assertTrue(result['autosave_disabled'])
        self.assertEqual({c['label']:c['after'] for c in result['changes']},
                         {'Always wait at end of turn':True,'Instant advice':False,'Autosave each turn':False})

    def test_default_autosave_is_toggled_once_and_observed_off(self):
        ui=self.ui();before=self.states(**{'Autosave each turn':True});after=self.states()
        with mock.patch('civ2.preferences.checkbox_state',side_effect=[*before.values(),False,*after.values()]) as read:
            result=configure_preferences(ui)
        self.assertEqual(read.call_count,23)
        ui.select_text.assert_called_once_with(ui.wait.return_value,'Autosave each turn',exact=True)
        ui.game.chord.assert_called_once_with('ControlLeft','KeyO',hold_ms=120)
        ui.key.assert_called_once_with('Enter',settle=1.2)
        self.assertTrue(result['checkbox_before']['Autosave each turn'])
        self.assertFalse(result['checkbox_after']['Autosave each turn'])
        self.assertTrue(result['other_checkboxes_unchanged'])

    def test_all_requested_changes_checked_again_after_last_click(self):
        ui=self.ui();before=self.states(**{'Always wait at end of turn':False,'Instant advice':True,'Autosave each turn':True})
        with mock.patch('civ2.preferences.checkbox_state',side_effect=[*before.values(),True,False,False,*self.states().values()]):
            configure_preferences(ui)
        self.assertEqual([call.args[1] for call in ui.select_text.call_args_list],
                         ['Always wait at end of turn','Instant advice','Autosave each turn'])

    def test_failed_autosave_or_unrelated_option_change_prevents_confirmation(self):
        before=self.states(**{'Autosave each turn':True})
        sequences=([*before.values(),True],
                   [*before.values(),False,*self.states(**{'Sound Effects':False}).values()])
        for values in sequences:
            ui=self.ui()
            with mock.patch('civ2.preferences.checkbox_state',side_effect=values):
                with self.assertRaises(RuntimeError):configure_preferences(ui)
            ui.key.assert_not_called()
        ui=self.ui()
        with mock.patch('civ2.preferences.checkbox_state',side_effect=ValueError('TEST ambiguous checkbox')):
            with self.assertRaises(ValueError):configure_preferences(ui)
        ui.select_text.assert_not_called();ui.key.assert_not_called()

    def test_incomplete_menu_does_not_satisfy_original_dialog_guard(self):
        ui=self.ui()
        with mock.patch('civ2.preferences.checkbox_state',side_effect=list(self.states().values())*2):
            configure_preferences(ui)
        guard=ui.wait.call_args.args[0]
        self.assertTrue(guard(ui.wait.return_value))
        for missing in ('Autosave each turn','Cancel','Music'):
            bad={'lines':[row for row in ui.wait.return_value['lines'] if row['text']!=missing]}
            self.assertFalse(guard(bad))

    def test_optional_original_default_autosave_is_visibly_checked(self):
        from civ2.observe import recognize
        path=Path('.runtime/attempt-006-setup/ui-0000045.png')
        if not path.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original setup frame unavailable')
        observation=recognize(path);observation['path']=str(path)
        self.assertTrue(checkbox_state(observation,'Autosave each turn'))
        self.assertFalse(checkbox_state(observation,'Always wait at end of turn'))
        self.assertTrue(checkbox_state(observation,'Instant advice'))
