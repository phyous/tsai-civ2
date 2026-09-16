"""Offline recording ownership/timing tests; TEST bytes are never real video evidence."""
import io
import json
from pathlib import Path
import tempfile
from unittest import mock
import unittest

from civ2.recording import Recorder


class RetainedBytes(io.BytesIO):
    def close(self):
        self.was_closed=True


class RetainedText(io.StringIO):
    def close(self):
        self.was_closed=True


class OneCaptureStop:
    def __init__(self):self.stopped=False
    def is_set(self):return self.stopped
    def wait(self, delay):self.stopped=True


class RecordingTests(unittest.TestCase):
    def recorder(self, directory):
        r=Recorder(directory,game=mock.Mock(),fps=4)
        r.initial_frame=b'\x89PNG\r\n\x1a\nTEST_FIRST'
        r.started=0;r.stop_event=OneCaptureStop()
        r.ledger=RetainedText();r.errors=RetainedBytes()
        r.process=mock.Mock();r.process.stdin=RetainedBytes();r.process.wait.return_value=0
        return r

    def test_delayed_capture_repeats_previous_observed_frame_not_future_frame(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.recorder(d);new=b'\x89PNG\r\n\x1a\nTEST_SECOND'
            r.game.request.return_value=new
            with mock.patch('civ2.recording.time.monotonic',return_value=1.0):r._run()
            self.assertEqual(r.process.stdin.getvalue(),r.initial_frame*4+new)
            self.assertEqual((r.frames,r.samples),(5,2))
            records=[json.loads(line) for line in r.ledger.getvalue().splitlines()]
            self.assertTrue(records[0]['initial_observation'])
            self.assertEqual((records[0]['frame'],records[0]['elapsed_ms']),(0,0))
            self.assertEqual((records[1]['frame'],records[1]['elapsed_ms']),(4,1000))
            self.assertNotEqual(records[0]['sha256'],records[1]['sha256'])
            self.assertIsNone(r.error)

    def test_failed_capture_is_not_replaced_by_generated_frame_or_reported_success(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.recorder(d);r.game.request.return_value=b'TEST: not a PNG'
            with mock.patch('civ2.recording.time.monotonic',return_value=1):r._run()
            self.assertEqual(r.process.stdin.getvalue(),r.initial_frame)
            self.assertEqual((r.frames,r.samples),(1,1))
            with self.assertRaisesRegex(RuntimeError,'Continuous recording failed'):r.check()
            r.process.wait.assert_called_once_with(timeout=45)

    def test_encoder_failure_propagates_after_successful_capture(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.recorder(d);r.game.request.return_value=r.initial_frame;r.process.wait.return_value=1
            with mock.patch('civ2.recording.time.monotonic',return_value=.25):r._run()
            self.assertEqual(r.error,'EncoderFailure')
            with self.assertRaises(RuntimeError):r.check()

    def test_initial_capture_failure_never_starts_encoder_or_claims_recording(self):
        with tempfile.TemporaryDirectory() as d:
            game=mock.Mock();game.request.return_value=b'TEST INVALID FRAME'
            r=Recorder(Path(d)/'video',game=game)
            with mock.patch('civ2.recording.shutil.which',return_value='/TEST/ffmpeg'),mock.patch('civ2.recording.subprocess.Popen') as encoder:
                with self.assertRaisesRegex(RuntimeError,'Initial dashboard capture'):r.start()
            encoder.assert_not_called();self.assertIsNone(r.thread)
            self.assertFalse((r.directory/'recording.json').exists())

    def test_invalid_recording_rates_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for fps in (0,31,-1,True,4.0):
                with self.subTest(fps=fps),self.assertRaises(ValueError):Recorder(d,game=mock.Mock(),fps=fps)


if __name__=='__main__':
    unittest.main()
