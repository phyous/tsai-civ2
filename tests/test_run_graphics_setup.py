"""One-time native presentation setup at safe boundaries; no real UI calls."""
from unittest import mock
import unittest
from civ2.run import controller_context, run_steps
from test_run import frame, session


def run(s, helper):
    with mock.patch('civ2.run.game_text',return_value='TEST'), \
         mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kw:o['classified']), \
         mock.patch('civ2.run.time.sleep'), \
         mock.patch('civ2.run.configure_graphics_preferences',helper):
        return run_steps(s,max_decisions=1)


class GraphicsSetupTests(unittest.TestCase):
    def test_unconfigured_normal_map_configures_once_then_reobserves_before_command(self):
        normal=frame(1,'normal_map');s=session([normal,normal]);ctx=controller_context(s)
        del ctx['graphics_configured'];s.checkpoint=mock.Mock()
        s.choose_unit=mock.Mock(side_effect=lambda:setattr(s,'decisions',1))
        receipt={'scope':'TEST presentation only','other_checkboxes_unchanged':True}
        helper=mock.Mock(return_value=receipt)
        run(s,helper)
        helper.assert_called_once_with(s.ui);s.checkpoint.assert_called_once()
        self.assertEqual(s.ui.observe.call_count,2)
        self.assertTrue(ctx['graphics_configured'])
        records=[c.kwargs for c in s.journal.append.call_args_list if c.args[0]=='graphics_preferences_configured']
        self.assertEqual(records,[{'receipt':receipt}])

    def test_supported_end_turn_is_also_safe_and_reobserved(self):
        end=frame(1,'end_turn');s=session([end,end,end]);ctx=controller_context(s)
        ctx['graphics_configured']=False;s.checkpoint=mock.Mock()
        def choose(*args):s.decisions=1;return {'id':'finish_turn'},frame(2,'normal_map')
        s.choose_empire=mock.Mock(side_effect=choose);helper=mock.Mock(return_value={'scope':'TEST'})
        run(s,helper)
        helper.assert_called_once_with(s.ui);s.choose_empire.assert_called_once()

    def test_mandatory_choice_does_not_open_graphics_preferences(self):
        research=frame(1,'research_choice',requires_model=True,options=[{},{}])
        s=session([research]);controller_context(s)['graphics_configured']=False
        helper=mock.Mock()
        run(s,helper)
        helper.assert_not_called();s.choose_dialog.assert_called_once()

    def test_failed_setup_does_not_claim_configuration_or_continue_game_orders(self):
        s=session([frame(1,'normal_map')]);ctx=controller_context(s);ctx['graphics_configured']=False
        s.choose_unit=mock.Mock();helper=mock.Mock(side_effect=RuntimeError('TEST readback failure'))
        with self.assertRaisesRegex(RuntimeError,'TEST readback failure'):run(s,helper)
        self.assertFalse(ctx['graphics_configured']);s.choose_unit.assert_not_called()
        self.assertFalse(any(c.args[0]=='graphics_preferences_configured' for c in s.journal.append.call_args_list))


if __name__=='__main__':unittest.main()
