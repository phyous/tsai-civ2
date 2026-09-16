"""Only the calibrated Civilopedia presentation toggle may change."""
from pathlib import Path
from unittest import TestCase,mock
from civ2.preferences import configure_graphics_preferences,checkbox_state,GRAPHICS_LABELS


class GraphicsPreferenceTests(TestCase):
    def ui(self):
        patch=mock.patch('civ2.preferences.move_cursor',return_value={})
        patch.start();self.addCleanup(patch.stop)
        ui=mock.Mock()
        o={'sha256':'TEST-frame','lines':[{'text':s} for s in (*GRAPHICS_LABELS,'OK','Cancel')]}
        ui.observe.return_value=o;ui.wait.return_value=o;ui.select_text.return_value={}
        ui.game.chord.return_value=[];ui.key.return_value=[]
        return ui

    def test_changes_only_requested_presentation_option_and_checks_all_six(self):
        ui=self.ui();prior=[True]*6;after=[True,True,True,False,True,True]
        with mock.patch('civ2.preferences.checkbox_state',side_effect=prior+after) as read:
            result=configure_graphics_preferences(ui)
        self.assertEqual(read.call_count,12)
        ui.game.chord.assert_called_once_with('ControlLeft','KeyP',hold_ms=120)
        self.assertEqual(ui.select_text.call_args.args[1],'Civilopedia for Advances')
        self.assertEqual(result['checkbox_before'],dict.fromkeys(GRAPHICS_LABELS,True))
        self.assertEqual(result['checkbox_after']['Civilopedia for Advances'],False)
        self.assertTrue(result['other_checkboxes_unchanged'])
        ui.key.assert_called_once_with('Enter',settle=1.2)

    def test_already_disabled_does_not_toggle(self):
        ui=self.ui();states=[True,False,True,False,False,True]
        with mock.patch('civ2.preferences.checkbox_state',side_effect=states*2):
            result=configure_graphics_preferences(ui)
        ui.select_text.assert_not_called();self.assertEqual(result['checkbox_before'],result['checkbox_after'])

    def test_failed_target_readback_or_other_changed_checkbox_prevents_confirmation(self):
        for after in ([True]*6,[False,True,True,False,True,True]):
            ui=self.ui()
            with mock.patch('civ2.preferences.checkbox_state',side_effect=[True]*6+after):
                with self.assertRaises(RuntimeError):configure_graphics_preferences(ui)
            ui.key.assert_not_called()
        ui=self.ui()
        with mock.patch('civ2.preferences.checkbox_state',side_effect=ValueError('TEST ambiguous checkbox')):
            with self.assertRaises(ValueError):configure_graphics_preferences(ui)
        ui.select_text.assert_not_called();ui.key.assert_not_called()

    def test_optional_actual_checkbox_readback_before_and_after(self):
        from civ2.observe import recognize
        root=Path(__file__).resolve().parents[1]
        paths=[root/f'.runtime/city-calibration/ui-{n:07d}.png' for n in (68,70)]
        if not all(p.exists() for p in paths) or not (root/'.runtime/ocr').exists():self.skipTest('private calibration images unavailable')
        values=[]
        for path in paths:
            o=recognize(path);o['path']=str(path)
            values.append({label:checkbox_state(o,label) for label in GRAPHICS_LABELS})
        self.assertEqual(values[0],dict.fromkeys(GRAPHICS_LABELS,True))
        expected=dict(values[0]);expected['Civilopedia for Advances']=False
        self.assertEqual(values[1],expected)
