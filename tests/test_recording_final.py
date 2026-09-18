"""Synthetic final-state preservation; no game or winning evidence is generated."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw

from civ2.recording import Recorder
from civ2.recording_final import METHOD, retain_final_sample
from civ2.session import Session
from civ2.verify import Files, VerificationError, _recording
from tests.test_verify import Evidence, picture


class Clock:
    def __init__(self): self.now = 1.0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class FinalRecordingTests(unittest.TestCase):
    def fixture(self, directory):
        frame = picture();digest = hashlib.sha256(frame).hexdigest()
        game = Mock();game.rpc.return_value = dict(paused=True,inputSequence=7,heldKeys=[],buttons=0)
        game.request.return_value = frame
        r = Recorder(directory,game=game);r.started = 0;r.thread = Mock()
        r.thread.is_alive.return_value = True
        row = dict(sample=2,elapsed_ms=1000,frame=4,sha256=digest)
        (Path(directory)/'frames.jsonl').write_text(json.dumps(row)+'\n')
        return r,row,frame

    def test_current_state_is_sampled_retained_and_has_a_real_frame_interval(self):
        with tempfile.TemporaryDirectory() as d:
            r,row,frame = self.fixture(d);clock = Clock()
            with patch('civ2.recording_final.time.monotonic',clock.monotonic), patch('civ2.recording_final.time.sleep',clock.sleep):
                proof = retain_final_sample(r)
            self.assertGreaterEqual(clock.now, 1.25)
            self.assertEqual(proof['frame'],row['frame']);self.assertEqual(proof['sample'],2)
            for key in ('game','dashboard'):
                self.assertEqual((Path(d)/proof[key]['name']).read_bytes(),frame)
            self.assertEqual(proof['method'],METHOD)
            self.assertFalse(r.stop_event.is_set())
            self.assertEqual(set(call.args[0] for call in r.game.rpc.call_args_list),{'status'})
            self.assertEqual(set(call.args[0] for call in r.game.request.call_args_list),
                             {'/bridge/capture/game','/bridge/capture/dashboard'})

    def test_stale_missing_changed_or_unpaused_state_cannot_finalize(self):
        for mode in ('stale','mismatch','pixels','input','held','running','invalid'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                r,row,frame=self.fixture(d);clock=Clock()
                if mode=='stale':row['elapsed_ms']=0
                if mode=='mismatch':row['sha256']='0'*64
                (Path(d)/'frames.jsonl').write_text(json.dumps(row)+'\n')
                if mode=='pixels':r.game.request.side_effect=[frame,frame,picture((639,480))]
                if mode=='invalid':r.game.request.return_value=b'TEST invalid PNG'
                if mode=='input':r.game.rpc.side_effect=[dict(paused=True,inputSequence=7,heldKeys=[],buttons=0),dict(paused=True,inputSequence=8,heldKeys=[],buttons=0)]
                if mode=='held':r.game.rpc.return_value['heldKeys']=['Enter']
                if mode=='running':r.game.rpc.return_value['paused']=False
                with patch('civ2.recording_final.time.monotonic',clock.monotonic),patch('civ2.recording_final.time.sleep',clock.sleep):
                    with self.assertRaises(RuntimeError):retain_final_sample(r,timeout=.1)
                self.assertFalse(r.stop_event.is_set());self.assertFalse(list(Path(d).glob('final-*.png')))

    def test_finish_failure_keeps_journal_open_without_a_false_stop(self):
        s=Session.__new__(Session);s.game=Mock();s.publish=Mock();s.recorder=Mock();s.journal=Mock()
        s.recorder.stop.side_effect=RuntimeError('Final capture unavailable')
        with self.assertRaises(RuntimeError):s.finish()
        s.journal.append.assert_not_called();s.journal.close.assert_not_called()
        s.game.rpc.assert_called_once_with('pause')

    def test_verifier_binds_final_pngs_to_actual_sample_and_preserves_legacy(self):
        for mode in ('valid','hash','sample','frame','sequence','manifest','traversal','dimensions'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                e=Evidence(d,recording=True);folder=e.directory/'video'
                manifest=json.loads((folder/'recording.json').read_text())
                frame=picture();digest=hashlib.sha256(frame).hexdigest()
                final=dict(method=METHOD,input_sequence=7,sample=2,elapsed_ms=750,frame=3,
                    game=dict(name='final-game-001.png',sha256=digest,bytes=len(frame)),
                    dashboard=dict(name='final-dashboard-001.png',sha256=digest,bytes=len(frame)))
                (folder/final['game']['name']).write_bytes(frame);(folder/final['dashboard']['name']).write_bytes(frame)
                if mode=='hash':final['dashboard']['sha256']='0'*64
                if mode=='sample':final['sample']=3
                if mode=='frame':final['frame']=2
                if mode=='sequence':final['input_sequence']=1
                if mode=='traversal':final['game']['name']='../screens/test.png'
                if mode=='dimensions':
                    raw=picture((639,480));(folder/final['game']['name']).write_bytes(raw)
                    final['game'].update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
                payload={**manifest,'path':'video/full-game.mp4','final_observation':deepcopy(final)}
                manifest['final_observation']=final
                if mode=='manifest':manifest['final_observation']['frame']=0
                (folder/'recording.json').write_text(json.dumps(manifest))
                if mode=='valid':
                    result=_recording(Files(e.directory),payload,None,7)
                    self.assertEqual(result['final_observation']['dashboard']['path'],'video/final-dashboard-001.png')
                else:
                    with self.assertRaises(VerificationError):_recording(Files(e.directory),payload,None,7)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg/ffprobe unavailable')
    def test_existing_capture_loop_records_new_final_state_without_restart(self):
        def frame(color,text):
            im=Image.new('RGB',(640,480),color);ImageDraw.Draw(im).text((20,30),text,fill='white')
            b=BytesIO();im.save(b,format='PNG');return b.getvalue()
        old=frame('#114466','TEST OLD FRAME');final=frame('#662211','TEST FINAL FRAME - NOT A GAME')
        class Game:
            current=old
            def request(self,path,binary=False):return self.current
            def rpc(self,command):
                assert command=='status'
                return dict(paused=True,inputSequence=7,heldKeys=[],buttons=0)
        with tempfile.TemporaryDirectory() as d:
            r=Recorder(Path(d)/'video',game=Game()).start();original_thread=r.thread
            r.game.current=final
            result=r.stop()
            self.assertIs(r.thread,original_thread);self.assertIsNone(r.error)
            self.assertGreaterEqual(result['frames'],result['final_observation']['frame']+1)
            self.assertGreaterEqual(time.monotonic()-r.started,result['duration_seconds']-.03)
            self.assertEqual(result['final_observation']['dashboard']['sha256'],hashlib.sha256(final).hexdigest())
            payload={**result,'path':'video/full-game.mp4'}
            checked=_recording(Files(d),payload,'ffprobe',7)
            self.assertEqual(checked['ffprobe']['status'],'passed')
            self.assertIsNotNone(checked['final_observation'])
            last=subprocess.run(['ffmpeg','-v','error','-i',str(r.directory/'full-game.mp4'),
                '-vf',f"select='eq(n,{result['frames']-1})'",'-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'],capture_output=True,check=True,timeout=10).stdout
            with Image.open(BytesIO(last)) as image:
                pixel=image.convert('RGB').getpixel((5,5))
            self.assertTrue(all(abs(a-b)<=4 for a,b in zip(pixel,(102,34,17))),pixel)


if __name__=='__main__':unittest.main()
