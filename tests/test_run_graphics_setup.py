"""One-time native presentation setup at safe boundaries; no real UI calls."""
from unittest import mock
import unittest
from civ2.run import controller_context, run_steps
from test_run import frame, session


def run(s, helper, throne=None):
    with mock.patch('civ2.run.game_text',return_value='TEST'), \
         mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kw:o['classified']), \
         mock.patch('civ2.run.time.sleep'), \
         mock.patch('civ2.run.configure_graphics_preferences',helper), \
         mock.patch('civ2.run.configure_throne_presentation',throne or mock.Mock()):
        return run_steps(s,max_decisions=1)


class GraphicsSetupTests(unittest.TestCase):
    def test_fresh_setup_verifies_each_option_separately_before_gameplay(self):
        normal=frame(1,'normal_map');s=session([normal]*3);ctx=controller_context(s)
        s.state.update(player={'id':1},selected_unit_id=1,units=[{'id':1,'owner':1,'hp':10}])
        ctx['graphics_configured']=False;ctx['throne_presentation_disabled']=False
        s.checkpoint=mock.Mock();s.choose_unit=mock.Mock(side_effect=lambda:setattr(s,'decisions',1))
        civilopedia=mock.Mock(return_value={'scope':'TEST Civilopedia only'})
        throne=mock.Mock(return_value={'scope':'TEST cosmetic Throne Room only'})
        run(s,civilopedia,throne)
        civilopedia.assert_called_once_with(s.ui);throne.assert_called_once_with(s.ui)
        self.assertEqual(s.ui.observe.call_count,3)
        s.checkpoint.assert_called_once();s.choose_unit.assert_called_once()
        self.assertTrue(ctx['graphics_configured']);self.assertTrue(ctx['throne_presentation_disabled'])
        records=[c.kwargs['receipt'] for c in s.journal.append.call_args_list
                 if c.args[0]=='graphics_preferences_configured']
        self.assertEqual(records,[civilopedia.return_value,throne.return_value])

    def test_failed_throne_readback_prevents_gameplay_and_does_not_claim_setup(self):
        s=session([frame(1,'end_turn')]);ctx=controller_context(s)
        ctx['throne_presentation_disabled']=False;s.choose_empire=mock.Mock()
        throne=mock.Mock(side_effect=RuntimeError('TEST throne readback failure'))
        with self.assertRaisesRegex(RuntimeError,'TEST throne readback failure'):
            run(s,mock.Mock(),throne)
        self.assertFalse(ctx['throne_presentation_disabled']);s.choose_empire.assert_not_called()
        self.assertFalse(any(c.args[0]=='graphics_preferences_configured' for c in s.journal.append.call_args_list))

    def test_unconfigured_normal_map_configures_once_then_reobserves_before_command(self):
        normal=frame(1,'normal_map');s=session([normal,normal]);ctx=controller_context(s)
        s.state.update(player={'id':1},selected_unit_id=1,units=[{'id':1,'owner':1,'hp':10}])
        del ctx['graphics_configured'];s.checkpoint=mock.Mock()
        s.choose_unit=mock.Mock(side_effect=lambda:setattr(s,'decisions',1))
        receipt={'scope':'TEST presentation only','other_checkboxes_unchanged':True}
        helper=mock.Mock(return_value=receipt)
        run(s,helper)
        helper.assert_called_once_with(s.ui);s.checkpoint.assert_called_once()
        s.choose_unit.assert_called_once()
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
        controller_context(s)['throne_presentation_disabled']=False
        helper=mock.Mock();throne=mock.Mock()
        run(s,helper,throne)
        helper.assert_not_called();throne.assert_not_called();s.choose_dialog.assert_called_once()

    def test_failed_setup_does_not_claim_configuration_or_continue_game_orders(self):
        s=session([frame(1,'normal_map')]);ctx=controller_context(s);ctx['graphics_configured']=False
        s.choose_unit=mock.Mock();helper=mock.Mock(side_effect=RuntimeError('TEST readback failure'))
        with self.assertRaisesRegex(RuntimeError,'TEST readback failure'):run(s,helper)
        self.assertFalse(ctx['graphics_configured']);s.choose_unit.assert_not_called()
        self.assertFalse(any(c.args[0]=='graphics_preferences_configured' for c in s.journal.append.call_args_list))


if __name__=='__main__':unittest.main()
