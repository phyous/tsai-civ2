"""TEST-only native restore transaction tests; no browser or game calls."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from civ2.restore import _load_confirmation, _startup, restore_start
from tests.test_verify import initial_save


RULES = '@LEADERS\nCaesar,Livia,0,1,1,Romans,Roman\n'


def observation(*lines):
    return {'sha256':'a'*64,'width':640,'height':480,'text':'\n'.join(lines),
            'lines':[{'text':line} for line in lines]}


def setup(directory):
    ui=mock.Mock();ui.directory=Path(directory)/'screens';ui.directory.mkdir()
    ui.game.rpc.side_effect=lambda cmd,*args:{'started':False,'height':480} if cmd=='status' else {'ok':True}
    ui.game.import_save.return_value={'loaded':False,'verified':True}
    ui.key.side_effect=lambda key,**kwargs:[{'type':'key','code':key}]
    ui.game.chord.side_effect=lambda *keys,**kwargs:[{'type':'chord','keys':list(keys)}]
    ui.game.type_text.side_effect=lambda text:[{'type':'text','text':text}]
    ui.select_text.return_value={'target':'Load a Game','inputs':[]}
    startup=observation('Start a New Game','Load a Game','OK')
    load=observation('Select Game To Load','File Name:')
    confirmed=observation('Dilliculty Level Prince','Dictator Caesar of the Romans','4000 B.C.','OK')
    ui.observe.side_effect=[startup,startup,load]
    ui.wait_text.return_value=load
    def wait(predicate,**kwargs):
        if predicate(confirmed):return confirmed
        if predicate(startup):return startup
        raise RuntimeError('TEST no matching observed screen')
    ui.wait.side_effect=wait
    ui.save_native.return_value=(initial_save(),{'name':'initial.sav'})
    ui.game.capture.side_effect=lambda path:Path(path).write_bytes(b'TEST capture')
    source=Path(directory)/'source.sav';source.write_bytes(initial_save())
    return ui,source


class RestoreTests(unittest.TestCase):
    def test_exact_load_then_preferences_then_save_without_strategy(self):
        with tempfile.TemporaryDirectory() as d:
            ui,source=setup(d)
            with mock.patch('civ2.restore.configure_preferences',return_value={'TEST':'verified'}) as prefs:
                state,report=restore_start(ui,source,profile='TEST-parallel',rules_text=RULES)
            self.assertTrue(report['ready']);self.assertTrue(all(report['checks'].values()))
            self.assertTrue(all(report['unchanged_gameplay_fields'].values()))
            self.assertEqual(state['turn'],1);self.assertEqual(state['cities'],[])
            self.assertFalse(report['strategic_inputs']);self.assertEqual(report['model_calls'],0)
            ui.game.import_save.assert_called_once_with('restore.sav',initial_save())
            ui.select_text.assert_called_once_with(mock.ANY,'Load a Game',exact=True,confirm=True)
            ui.game.chord.assert_any_call('ControlLeft','F4',hold_ms=120)
            self.assertTrue(all(call.args[0] in ('Home','Enter') for call in ui.key.call_args_list))
            prefs.assert_called_once_with(ui)
            self.assertEqual((ui.directory/'initial.sav').read_bytes(),source.read_bytes())
            self.assertTrue((ui.directory/'setup.json').exists())
            self.assertTrue((ui.directory/'ready.png').exists())

    def test_already_started_instance_refused_before_any_load(self):
        with tempfile.TemporaryDirectory() as d:
            ui,source=setup(d);ui.game.rpc.side_effect=lambda *args:{'started':True}
            with self.assertRaisesRegex(RuntimeError,'Reload'):restore_start(ui,source,profile='TEST',rules_text=RULES)
            ui.game.import_save.assert_not_called();ui.key.assert_not_called()

    def test_previous_artifacts_and_ambiguous_filenames_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            ui,source=setup(d);prior=ui.directory/'kept.txt';prior.write_text('TEST original')
            with self.assertRaisesRegex(ValueError,'empty'):restore_start(ui,source,profile='TEST',rules_text=RULES)
            self.assertEqual(prior.read_text(),'TEST original');ui.game.rpc.assert_not_called()
        with tempfile.TemporaryDirectory() as d:
            ui,source=setup(d)
            for name in ('../bad.sav','longfilename.sav','bad.exe'):
                with self.subTest(name=name),self.assertRaises(ValueError):
                    restore_start(ui,source,profile='TEST',guest_name=name,rules_text=RULES)
            with self.assertRaisesRegex(ValueError,'distinct'):
                restore_start(ui,source,profile='TEST',guest_name='INITIAL.SAV',rules_text=RULES)
            ui.game.rpc.assert_not_called()

    def test_preferences_failure_pauses_and_preserves_failure_without_continuing(self):
        with tempfile.TemporaryDirectory() as d:
            ui,source=setup(d)
            with mock.patch('civ2.restore.configure_preferences',side_effect=ValueError('TEST unreadable checkbox')):
                with self.assertRaisesRegex(ValueError,'checkbox'):restore_start(ui,source,profile='TEST',rules_text=RULES)
            ui.save_native.assert_not_called();ui.game.rpc.assert_any_call('pause')
            self.assertTrue((ui.directory/'restore-failed.png').exists())
            self.assertTrue((ui.directory/'setup-failed.json').exists())
            self.assertFalse((ui.directory/'setup.json').exists())

    def test_changed_native_gameplay_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ui,source=setup(d);modified=bytearray(initial_save());modified[2264+1396+2]=51
            ui.save_native.return_value=(bytes(modified),{})
            with mock.patch('civ2.restore.configure_preferences',return_value={}):
                with self.assertRaisesRegex(RuntimeError,'Gameplay state changed'):
                    restore_start(ui,source,profile='TEST',rules_text=RULES)
            self.assertFalse((ui.directory/'initial.sav').exists())

    def test_confirmation_requires_known_leader_prince_date_and_observed_ok(self):
        self.assertTrue(_load_confirmation(observation('Dilliculty Level Prince',
            'Dictator Caesar of the Romans','4000 B.C.','OK'),'Caesar'))
        for lines in [('Prince','Caesar of the Romans','4000 B.C.'),
                      ('Chieftain','Caesar of the Romans','4000 B.C.','OK'),
                      ('Prince','Caesar of the Romans','3950 B.C.','OK'),
                      ('Prince','Someone of the Romans','4000 B.C.','OK')]:
            self.assertFalse(_load_confirmation(observation(*lines),'Caesar'))
        self.assertFalse(_startup(observation('Load a Game','Unknown confirmation')))


if __name__=='__main__':
    unittest.main()
