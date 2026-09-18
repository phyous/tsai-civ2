"""Terminal candidates retain their original screenshot without a new input."""
from unittest import TestCase
from unittest.mock import Mock, patch
from civ2.dialogs import classify_dialog
from civ2.run import run_steps
from tests.test_dialogs import observation, row
from tests.test_run import session

SOURCE='''@SLAM
Your civilization has conquered the entire planet!

@EAGLEHASLANDED
@width=320
@title=Science Advisor
%STRING0 spaceship arrives on Alpha Centauri!

@DORETIRE
@width=440
@title=Retirement Announced!
%STRING1 dynasty ends after glorious 6000 year reign!

@KEEPPLAYING
@width=320
@title=Game Over!
Your final score has been computed. Do you want to
keep playing? (No further score will be recorded).

No, I'm done.
Yes, keep playing.

@CENTAURI3
%STRING4, your people have fulfilled the dream of countless generations.
Your name will live forever in the annals of CIVILIZATION!
'''


class TerminalStops(TestCase):
    def test_win_candidates_arrival_retirement_and_score_never_autodismiss(self):
        cases=(
            ('conquest',['Your civilization has conquered the entire planet!'],'victory_candidate_conquest'),
            ('space',['TEST Caesar, your people have fulfilled the dream of countless generations.',
                      'Your name will live forever in the annals of CIVILIZATION!'],'victory_candidate_space'),
            ('rival arrival',['Science Advisor','TEST Greeks spaceship arrives on Alpha Centauri!','OK'],None),
            ('own arrival',['Science Advisor','Romans spaceship arrives on Alpha Centauri!','OK'],None),
            ('retirement',['Retirement Announced!','TEST Roman dynasty ends after glorious 6000 year reign!','OK'],None),
            ('score',['CIVILIZATION SCORE','TEST Caesar of the Romans','Total Score: 1000','OK'],None),
            ('game over',['Game Over!','Your final score has been computed. Do you want to',
                          'keep playing? (No further score will be recorded).',"No, I'm done.",'Yes, keep playing.'],'terminal_unspecified'),
        )
        for label,texts,outcome in cases:
            with self.subTest(label=label):
                o=observation(*(row(t,y=90+30*i,w=min(620,len(t)*6)) for i,t in enumerate(texts)))
                o['path']='/tmp/TEST-run/screens/terminal.png'
                classified=classify_dialog(o,game_text=SOURCE)
                self.assertEqual(classified['outcome'],outcome)
                self.assertIsNone(classified['mechanical_action'])
                s=session([o]);s.mechanical=Mock();s.choose_unit=Mock();s.choose_empire=Mock()
                with patch('civ2.run.game_text',return_value=SOURCE),patch('civ2.run.observe_ready',return_value=(o,classified)):
                    result=run_steps(s,max_decisions=1)
                self.assertEqual(result['status'],'paused');self.assertEqual(result['screen'],o['path'])
                self.assertEqual(s.game.rpc.call_args_list[0].args,('pause',))
                s.game.click.assert_not_called();s.ui.key.assert_not_called();s.mechanical.assert_not_called()
                s.choose_dialog.assert_not_called();s.choose_unit.assert_not_called();s.choose_empire.assert_not_called()
                self.assertEqual(s.journal.append.call_args.kwargs['path'],'screens/terminal.png')
