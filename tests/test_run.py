"""Controller transaction regressions. Synthetic screens; no game/model calls."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

from civ2.run import classification_state, controller_context, run_steps


def frame(number, kind, title='', **extra):
    result = dict(kind=kind,title=title,supported=True,mechanical_action=None,
                  requires_model=False,options=[],buttons=[])
    result.update(extra)
    return dict(path=f'/tmp/TEST-run/screens/{number}.png',sha256=str(number)*64,
                text=title,classified=result)


def session(observations):
    s = SimpleNamespace(state={'turn':1,'cities':[]},rules={},decisions=0,recorder=None,
                        game=mock.Mock(),ui=mock.Mock(),journal=mock.Mock(),publish=mock.Mock())
    s.journal.directory=Path('/tmp/TEST-run')
    s.ui.observe.side_effect=observations
    s.choose_dialog=mock.Mock(side_effect=lambda dialog: setattr(s,'decisions',s.decisions+1))
    return s


class ControllerTests(TestCase):
    def run_fake(self,s):
        with mock.patch('civ2.run.game_text',return_value='TEST'), \
             mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kwargs:o['classified']), \
             mock.patch('civ2.run.time.sleep'):
            return run_steps(s,max_decisions=1)

    def test_review_of_one_city_cannot_skip_other_city(self):
        controls=[{'text':'Exit'},{'text':'Change'}]
        a=frame(1,'city_screen','City of TEST Rome, 4000 B.C.',buttons=controls)
        b=frame(2,'city_screen','City of TEST Veii, 4000 B.C.',buttons=controls)
        prod=frame(3,'production_choice',requires_model=True,options=[{},{}])
        s=session([a,b,prod]);ctx=controller_context(s)
        ctx['production_reviewed'].add(('TEST Rome','4000BC'))
        self.run_fake(s)
        self.assertEqual([c.args[1] for c in s.ui.select_text.call_args_list],['Change'])
        s.ui.key.assert_called_once_with('Escape')
        self.assertIn(('TEST Veii','4000BC'),ctx['production_reviewed'])

    def test_pausing_on_unknown_preserves_target_city_transaction(self):
        unknown=frame(1,'unknown',supported=False)
        s=session([unknown]*11)
        ctx=controller_context(s);ctx['pending_city']={'name':'TEST Rome'}
        ctx['pending_empire']={'id':'inspect_city_0'}
        self.assertEqual(self.run_fake(s)['status'],'paused')
        self.assertIs(controller_context(s),ctx)
        wrong=frame(2,'city_screen','City of TEST Veii, 4000 B.C.',buttons=[{'text':'Change'}])
        s.ui.observe.side_effect=[wrong]
        self.assertIn('does not match',self.run_fake(s)['reason'])
        s.ui.select_text.assert_not_called()
        self.assertFalse(ctx['pending_empire_confirmed'])

    def test_visible_pending_city_name_does_not_modify_native_state(self):
        s=session([]);ctx=controller_context(s)
        ctx['observed_city_names'].add('TEST Rome')
        result=classification_state(s)
        self.assertEqual(result['cities'],[{'name':'TEST Rome'}])
        self.assertEqual(s.state['cities'],[])
        self.assertNotIn('units',result)

    def test_return_to_end_turn_without_menu_does_not_count_as_review(self):
        end=frame(1,'end_turn')
        s=session([end]);s.checkpoint=mock.Mock()
        ctx=controller_context(s);ctx['pending_empire']={'id':'open_tax'}
        self.assertIn('did not have an observed',self.run_fake(s)['reason'])
        self.assertEqual(ctx['reviewed']['actions'],[])

    def test_gray_blink_after_checkpoint_waits_for_observed_cue_before_choice(self):
        end=frame(1,'end_turn')
        gray=frame(2,'unknown',supported=False)
        s=session([end,gray,end]);s.checkpoint=mock.Mock()
        def choose(dialog,reviewed):
            self.assertEqual(dialog['kind'],'end_turn')
            s.decisions += 1
            return {'id':'finish_turn'},frame(3,'normal_map')
        s.choose_empire=mock.Mock(side_effect=choose)
        self.run_fake(s)
        s.choose_empire.assert_called_once()
        s.ui.key.assert_not_called()
        s.ui.select_text.assert_not_called()
        self.assertEqual(s.game.rpc.call_args_list,
                         [mock.call('pause'),mock.call('resume'),mock.call('pause')])
