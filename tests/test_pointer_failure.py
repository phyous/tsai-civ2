"""TEST failed visual cursor movement must retain any ordinary motion."""
from copy import deepcopy
from io import BytesIO
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2.cursor import CursorError,move_cursor
from civ2.ui import UI
from civ2.verify import verify_run,VerificationError
from tests.test_cursor import FakeGame,picture
from tests.test_verify import Evidence


class LostCursorGame(FakeGame):
    def __init__(self,initially_absent=False):
        super().__init__();self.initially_absent=initially_absent;self.receipts=[]
    def request(self,path,binary=False):
        if self.receipts or self.initially_absent:
            out=BytesIO();picture().save(out,format='PNG');return out.getvalue()
        return super().request(path,binary)
    def rpc(self,cmd,*args):
        if cmd=='status':return {'inputSequence':len(self.receipts),'heldKeys':[],'buttons':0}
        result=super().rpc(cmd,*args)
        if cmd=='moveRelative':
            result={'type':'relativeMouse','sequence':len(self.receipts)+1,'dx':args[0],'dy':args[1],
                'via':'DOSBox Mouse_CursorMoved','dispatched':True,'emulate':True}
            self.receipts.append(result)
        return result


class FailedPointer(unittest.TestCase):
    def test_cursor_error_keeps_relative_input_before_failed_readback(self):
        game=LostCursorGame()
        with patch('civ2.cursor.time.sleep'):
            with self.assertRaises(CursorError) as error:move_cursor(game,2,1,tolerance=1)
        r=error.exception.cursor_receipt
        self.assertEqual(r['status'],'failed');self.assertEqual(r['inputs'],game.receipts)
        self.assertEqual(len(r['inputs']),1);self.assertEqual(r['target'],[2,1])
        self.assertEqual(r['checkpoints'][0]['cursor'],[400,320]);self.assertFalse(r['issued'])
        self.assertTrue(all(x['type']=='mousemove' for x in game.inputs))

    def test_ui_records_actual_sequence_pair_and_failure_pixels(self):
        for absent in (True,False):
            with self.subTest(absent=absent),tempfile.TemporaryDirectory() as directory,patch('civ2.cursor.time.sleep'):
                game=LostCursorGame(absent);ui=UI(game,directory);r=ui.park_pointer()
                self.assertEqual(r['input_sequence_before'],0)
                self.assertEqual(r['input_sequence_after'],0 if absent else 1)
                self.assertEqual(r['inputs'],game.receipts)
                self.assertEqual(r['held_keys_after'],[]);self.assertEqual(r['buttons_after'],0)
                self.assertTrue((Path(directory)/('cursor-park-'+r['failure_frame_sha256']+'.png')).is_file())

    @staticmethod
    def receipt(count=1):
        return {'issued':False,'status':'failed','target':[2,1],'tolerance':1,
            'error':'The original Windows arrow is not fully visible','checkpoints':[],
            'inputs':[{'type':'relativeMouse','sequence':3,'dx':-8,'dy':-8,
                'via':'DOSBox Mouse_CursorMoved','dispatched':True,'emulate':True}] if count else [],
            'input_sequence_before':2,'input_sequence_after':2+count,
            'held_keys_before':[],'held_keys_after':[],'buttons_before':0,'buttons_after':0}

    def evidence(self,directory,receipt):
        e=Evidence(directory)
        e.rewrite(lambda rows:rows.insert(-1,{'kind':'pointer_park_for_observation','elapsed_ms':rows[-1]['elapsed_ms'],
            'payload':{'before':e.screen['sha256'],'receipt':receipt}}))
        return e

    def test_verified_failed_park_counts_motion_without_claiming_success(self):
        for count in (0,1):
            with tempfile.TemporaryDirectory() as directory:
                e=self.evidence(directory,self.receipt(count));report=verify_run(e.directory)
                self.assertEqual(report['integrity'],'passed')
                self.assertEqual(report['decisions']['ordinary_input_events'],2+count)
                self.assertEqual(report['decisions']['failed_pointer_parks'][0]['relative_input_events'],count)

    def test_missing_input_or_gameplay_event_cannot_be_hidden_as_failure(self):
        for case in ('gap','missing','button','held','bool_sequence','missing_frame','unknown_status'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                r=self.receipt()
                if case=='gap':r['input_sequence_after']=4
                elif case=='missing':r['inputs']=[]
                elif case=='button':r['inputs']=[{'type':'key','sequence':3,'code':'Space','down':True,'repeat':False}]
                elif case=='held':r['held_keys_after']=['Space']
                elif case=='bool_sequence':r['input_sequence_before']=True
                elif case=='missing_frame':r['failure_frame_sha256']='e'*64
                elif case=='unknown_status':r['status']='successful'
                e=self.evidence(directory,r)
                with self.assertRaises(VerificationError):verify_run(e.directory)

    def test_legacy_unaccounted_failure_remains_explicit_audit_limitation(self):
        with tempfile.TemporaryDirectory() as directory:
            e=self.evidence(directory,{'issued':False,'error':'The original Windows arrow is not fully visible'})
            with self.assertRaisesRegex(VerificationError,'Historical failed pointer park omitted'):verify_run(e.directory)

if __name__=='__main__':unittest.main()
