"""Real PNG capture and synthetic OCR failure after an ordinary TEST key."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch,call
from civ2.ui import UI
from civ2.session import Session
from civ2.dialogs import classify_dialog
from test_ui_cache import Capture,png
from test_session import session,dialog

GEOMETRY='Invalid normalized OCR geometry'


class Inputs(Capture):
    def __init__(self):
        super().__init__();self.keys=[];self.rpc=Mock()
    def key(self,code,**kwargs):
        self.keys.append((code,kwargs));self.data=png('black')
        return [{'test_input':code,'issued':True,'sequence':1},
                {'test_input':code,'issued':True,'sequence':2}]


class UnreadableAfterTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.game=Inputs();self.ui=UI(self.game,self.directory.name)
    def recognized(self,path):
        return dict(width=640,height=480,sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            lines=[],text='',ocr={'fallback_errors':[]})

    def test_only_explicit_post_input_mode_retains_known_geometry_failure(self):
        with patch('civ2.ui.recognize',side_effect=ValueError(GEOMETRY)) as ocr:
            with self.assertRaisesRegex(ValueError,GEOMETRY):self.ui.observe()
            self.assertIsNone(self.ui.latest)
            result=self.ui.observe(retain_unreadable=True)
            self.assertEqual(result['sha256'],hashlib.sha256(Path(result['path']).read_bytes()).hexdigest())
            self.assertEqual((result['width'],result['height']),(640,480))
            self.assertEqual(result['lines'],[]);self.assertEqual(result['text'],'')
            self.assertTrue(result['ocr']['unreadable_after_input'])
            self.assertEqual(result['ocr']['fallback_errors'][0]['message'],GEOMETRY)
            self.assertNotIn('cursor_hotspot',result);self.assertIs(self.ui.latest,result)
            self.assertFalse(self.ui._recognition_cache)
            classified=classify_dialog(result,state={'player':{'tribe_id':0}})
            self.assertFalse(classified['supported']);self.assertEqual(classified['options'],[])
            self.assertIsNone(classified['mechanical_action'])
            with self.assertRaisesRegex(ValueError,GEOMETRY):self.ui.observe()
            self.assertEqual(ocr.call_count,3)

    def test_previous_cached_text_is_not_attached_to_unreadable_new_pixels(self):
        def ocr(path):
            if self.game.data==png('black'):raise ValueError(GEOMETRY)
            result=self.recognized(path);result.update(text='TEST old OK',lines=[{'text':'TEST old OK'}]);return result
        with patch('civ2.ui.recognize',side_effect=ocr) as reader:
            before=self.ui.observe();self.game.data=png('black')
            after=self.ui.observe(retain_unreadable=True)
            self.assertNotEqual(before['sha256'],after['sha256']);self.assertEqual(after['lines'],[])
            self.assertEqual(len(self.ui._recognition_cache),1)
            self.ui.observe(retain_unreadable=True);self.assertEqual(reader.call_count,3)

    def test_unrelated_error_and_hash_mismatch_still_propagate(self):
        for error in (ValueError('TEST other OCR failure'),RuntimeError(GEOMETRY),OSError('TEST missing OCR')):
            with self.subTest(error=error),patch('civ2.ui.recognize',side_effect=error):
                with self.assertRaises(type(error)):self.ui.observe(retain_unreadable=True)
        with patch('civ2.ui.recognize',return_value={'sha256':'0'*64}):
            with self.assertRaisesRegex(ValueError,'differs'):self.ui.observe(retain_unreadable=True)
        def replaced(path):
            Path(path).write_bytes(png('red'));raise ValueError(GEOMETRY)
        with patch('civ2.ui.recognize',side_effect=replaced):
            with self.assertRaisesRegex(ValueError,'differs'):self.ui.observe(retain_unreadable=True)
        self.assertFalse(self.ui._recognition_cache)

    def test_mechanical_post_input_failure_keeps_actual_receipts_and_png(self):
        s=object.__new__(Session);s.game=self.game;s.ui=self.ui;s.journal=Mock()
        def ocr(path):
            if self.game.keys:raise ValueError(GEOMETRY)
            return self.recognized(path)
        with patch('civ2.ui.recognize',side_effect=ocr),patch('civ2.ui.time.sleep'):
            after=s.mechanical('TEST exact original notice')
        self.assertEqual(self.game.keys,[('Enter',{'holdMs':120})])
        self.assertTrue(after['ocr']['unreadable_after_input'])
        event=s.journal.append.call_args
        self.assertEqual(event.args,('mechanical_input',))
        self.assertEqual(event.kwargs['after'],hashlib.sha256(Path(after['path']).read_bytes()).hexdigest())
        self.assertEqual(event.kwargs['inputs'],[{'test_input':'Enter','issued':True,'sequence':1},
                                               {'test_input':'Enter','issued':True,'sequence':2}])

    def test_mechanical_pre_input_failure_issues_no_key_or_receipt(self):
        s=object.__new__(Session);s.game=self.game;s.ui=self.ui;s.journal=Mock()
        with patch('civ2.ui.recognize',side_effect=ValueError(GEOMETRY)),patch('civ2.ui.time.sleep'):
            with self.assertRaisesRegex(ValueError,GEOMETRY):s.mechanical('TEST notice')
        self.assertEqual(self.game.keys,[]);s.journal.append.assert_not_called()

    def test_model_dialog_pre_input_failure_remains_strict(self):
        from civ2.policy import dialog_candidates
        s=session();d=dialog();s._evaluate=Mock(return_value=dialog_candidates(s.state,d)['option_0'])
        s.ui=self.ui;s.game=self.game
        with patch('civ2.ui.recognize',side_effect=ValueError(GEOMETRY)):
            with self.assertRaisesRegex(ValueError,GEOMETRY):s.choose_dialog(d)
        self.game.rpc.assert_not_called();self.assertEqual(self.game.keys,[])
        s.journal.append.assert_not_called()


class SessionAfterFlagTests(unittest.TestCase):
    @patch('civ2.session.time.sleep')
    def test_all_five_session_dispatch_paths_opt_in_only_after_input(self,sleep):
        from test_session_planning import session as planning_session
        from test_session_receipts import end_turn
        from test_session_city_controls import setup
        from test_city_controls import reviewed
        for kind in ('unit','dialog','empire','city','mechanical'):
            s=planning_session(False)
            if kind=='city':s,screen=setup()
            elif kind=='empire':screen=end_turn(s)
            elif kind=='dialog':screen=dialog('button')
            else:screen={'sha256':'a'*64}
            s.ui.observe.side_effect=[{'sha256':screen['sha256']},{'sha256':'c'*64}]
            with self.subTest(kind=kind):
                if kind=='unit':s.choose_unit()
                elif kind=='dialog':s.choose_dialog(screen)
                elif kind=='empire':s.choose_empire(screen,{'turn':1,'actions':[]})
                elif kind=='city':s.choose_city_control(screen,reviewed())
                else:s.mechanical('TEST notice')
                self.assertEqual(s.ui.observe.call_args_list,[call(),call(retain_unreadable=True)])


if __name__=='__main__':unittest.main()
