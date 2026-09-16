"""Preference transactions must be idempotent and verify native readback."""
from unittest import TestCase, mock
from civ2.preferences import configure_preferences


class PreferencesTests(TestCase):
    def ui(self):
        parking=mock.patch('civ2.preferences.move_cursor',return_value={})
        parking.start();self.addCleanup(parking.stop)
        ui=mock.Mock()
        ui.observe.return_value={'sha256':'TEST-frame','lines':[{'text':'Always wait at end of turn'},{'text':'Instant advice'}]}
        ui.wait.return_value={'sha256':'TEST-dialog','lines':[{'text':'Always wait at end of turn'},{'text':'Instant advice'}]}
        ui.select_text.return_value={}
        ui.game.chord.return_value=[];ui.key.return_value=[]
        return ui

    def test_already_configured_preferences_are_not_toggled(self):
        ui=self.ui()
        with mock.patch('civ2.preferences.checkbox_state',side_effect=[True,False]):
            r=configure_preferences(ui)
        ui.select_text.assert_not_called()
        self.assertEqual([(c['before'],c['after']) for c in r['changes']],[(True,True),(False,False)])

    def test_changes_only_mismatched_preference_and_reads_back(self):
        ui=self.ui()
        with mock.patch('civ2.preferences.checkbox_state',side_effect=[False,True,False]) as read:
            configure_preferences(ui)
        self.assertEqual(read.call_count,3)
        self.assertEqual(ui.select_text.call_args.args[1],'Always wait at end of turn')
        ui.key.assert_called_once_with('Enter',settle=1.2)

    def test_ambiguous_or_failed_checkbox_does_not_confirm_preferences(self):
        for results,error in (([ValueError('TEST unreadable')],ValueError),([False,False],RuntimeError)):
            ui=self.ui()
            with mock.patch('civ2.preferences.checkbox_state',side_effect=results):
                with self.assertRaises(error):configure_preferences(ui)
            ui.key.assert_not_called()
