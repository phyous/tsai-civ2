"""Continuous real-time dashboard recording without retaining PNG frame piles.

Capture samples are timestamped; gaps repeat the preceding real frame. No game
time is removed. The sample ledger distinguishes captures from repeated frames.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
from .engine import Game


class Recorder:
    def __init__(self, directory, *, game=None, fps=4):
        if type(fps) is not int or not 1 <= fps <= 30:
            raise ValueError('Recording rate must be 1–30 fps')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.game = game or Game()
        self.fps = fps
        self.stop_event = threading.Event()
        self.error = None
        self.thread = None
        self.frames = 0
        self.samples = 0

    def start(self):
        if self.thread is not None:
            raise RuntimeError('Recorder already started')
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            raise RuntimeError('Install ffmpeg to record the original game')
        self.initial_frame = self.game.request('/bridge/capture/dashboard', binary=True)
        if not self.initial_frame.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('Initial dashboard capture returned invalid data')
        output = self.directory / 'full-game.mp4'
        self.errors = (self.directory / 'encoder.log').open('xb')
        self.ledger = (self.directory / 'frames.jsonl').open('x', encoding='utf-8')
        self.process = subprocess.Popen([ffmpeg, '-hide_banner', '-loglevel', 'warning',
            '-n', '-f', 'image2pipe', '-framerate', str(self.fps), '-vcodec', 'png',
            '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)],
            # A controller debugging interrupt must not also signal the encoder.
            # The recorder owns orderly EOF/finalization independently of the REPL.
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.errors,
            start_new_session=True)
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._run, name='original-game-recorder', daemon=True)
        self.thread.start()
        return self

    def _write(self, frame, count):
        for _ in range(count):
            self.process.stdin.write(frame)
            self.frames += 1

    def _run(self):
        previous = self.initial_frame
        try:
            self._write(previous, 1)
            self.samples += 1
            self.ledger.write(json.dumps({'sample':self.samples,'elapsed_ms':0,'frame':0,
                'sha256':hashlib.sha256(previous).hexdigest(),'initial_observation':True})+'\n')
            while not self.stop_event.is_set():
                frame = self.game.request('/bridge/capture/dashboard', binary=True)
                if not frame.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise RuntimeError('Original dashboard capture returned invalid data')
                elapsed = time.monotonic() - self.started
                tick = int(elapsed * self.fps)
                self._write(previous, max(0, tick-self.frames))
                self._write(frame, 1)
                self.samples += 1
                self.ledger.write(json.dumps({'sample':self.samples,'elapsed_ms':round(elapsed*1000),
                    'frame':self.frames-1,'sha256':hashlib.sha256(frame).hexdigest()})+'\n')
                self.ledger.flush()
                previous = frame
                self.stop_event.wait(max(0, self.frames/self.fps-(time.monotonic()-self.started)))
            if previous is not None:
                self._write(previous, max(0, round((time.monotonic()-self.started)*self.fps)-self.frames))
        except Exception as error:
            self.error = type(error).__name__
        finally:
            try:
                self.process.stdin.close()
                code = self.process.wait(timeout=45)
                if code:
                    self.error = self.error or 'EncoderFailure'
            except Exception:
                self.process.kill()
                self.error = self.error or 'EncoderFinalizationFailure'
            self.errors.close()
            self.ledger.close()

    def check(self):
        if self.error:
            raise RuntimeError('Continuous recording failed: '+self.error)

    def stop(self):
        if self.thread is None:
            return None
        from .recording_final import retain_final_sample, validate_final_game
        final = retain_final_sample(self)
        self.stop_event.set()
        self.thread.join(timeout=55)
        if self.thread.is_alive():
            raise RuntimeError('Recorder has not finalized')
        self.check()
        # A last capture can race the stop signal by one frame. Let its actual
        # encoded interval elapse while the original game remains paused.
        time.sleep(max(0, self.frames/self.fps-(time.monotonic()-self.started)))
        validate_final_game(self, final)
        result = {'path':'full-game.mp4','fps':self.fps,'frames':self.frames,
                  'samples':self.samples,'duration_seconds':self.frames/self.fps,
                  'time_compression':False, 'final_observation':final}
        (self.directory/'recording.json').write_text(json.dumps(result, indent=2))
        return result
