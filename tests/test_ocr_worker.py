"""Transport tests use real local child processes, never game/browser inputs."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from civ2 import ocr_worker


class OCRWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(ocr_worker.close_workers)
        self.root = Path(self.directory.name)
        self.log = self.root / 'events.jsonl'
        self.image = self.root / 'capture TEST.png'
        self.image.write_text('TEST original observation')

    def executable(self, mode='worker', name='ocr'):
        path = self.root / name
        path.write_text(f'''#!{sys.executable}
import json,sys,time
from pathlib import Path
mode={mode!r}
log=Path({str(self.log)!r})
def event(name):
 with log.open('a') as f:f.write(json.dumps(name)+'\\n')
def rows(path):return [{{'text':Path(path).read_text()}}]
if sys.argv[1]!='--worker':
 event('oneshot')
 print(json.dumps(rows(sys.argv[1])))
 sys.exit(0)
event('worker')
if mode=='legacy':sys.exit(2)
print(json.dumps({{'ready':1}}),flush=True)
for line in sys.stdin:
 request=json.loads(line);event('request')
 if mode=='crash':sys.exit(1)
 if mode=='timeout':time.sleep(5)
 if mode=='oversize':print('x'*2048,flush=True);continue
 if mode=='malformed':print('not json',flush=True);continue
 if Path(request['path']).name=='bad':
  print(json.dumps({{'id':request['id'],'error':'Game image OCR failed'}}),flush=True);continue
 identifier=request['id']+1 if mode=='stale' else request['id']
 print(json.dumps({{'id':identifier,'rows':rows(request['path'])}}),flush=True)
''')
        path.chmod(0o700)
        return path

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_reuses_child_but_never_caches_image_results(self):
        worker = ocr_worker.OCRWorker(self.executable())
        self.addCleanup(worker.close)
        self.assertEqual(worker.run(self.image), [{'text': 'TEST original observation'}])
        pid = worker.process.pid
        self.image.write_text('TEST changed original pixels')
        self.assertEqual(worker.run(self.image), [{'text': 'TEST changed original pixels'}])
        self.assertEqual(worker.process.pid, pid)
        self.assertEqual(self.events(), ['worker', 'request', 'request'])

    def test_legacy_binary_probed_only_once_then_uses_original_cli(self):
        worker = ocr_worker.OCRWorker(self.executable('legacy'))
        self.addCleanup(worker.close)
        for _ in range(2):
            self.assertEqual(worker.run(self.image), [{'text': 'TEST original observation'}])
        self.assertTrue(worker.disabled)
        self.assertIsNone(worker.process)
        self.assertEqual(self.events(), ['worker', 'oneshot', 'oneshot'])

    def test_wrong_response_identity_is_never_used(self):
        worker = ocr_worker.OCRWorker(self.executable('stale'))
        self.addCleanup(worker.close)
        self.assertEqual(worker.run(self.image), [{'text': 'TEST original observation'}])
        self.assertEqual(self.events(), ['worker', 'request', 'oneshot'])
        self.assertTrue(worker.disabled)

    def test_crash_and_malformed_response_fall_back_to_same_image(self):
        for mode in ('crash', 'malformed'):
            with self.subTest(mode=mode):
                worker = ocr_worker.OCRWorker(self.executable(mode, mode))
                self.addCleanup(worker.close)
                self.assertEqual(worker.run(self.image), [{'text': 'TEST original observation'}])
                self.assertTrue(worker.disabled)

    def test_response_size_is_bounded(self):
        worker = ocr_worker.OCRWorker(self.executable('oversize'))
        self.addCleanup(worker.close)
        with patch.object(ocr_worker, 'MAX_RESPONSE_BYTES', 1024):
            self.assertEqual(worker.run(self.image), [{'text': 'TEST original observation'}])
        self.assertTrue(worker.disabled)

    def test_timeout_kills_owned_child_without_fresh_full_timeout_fallback(self):
        worker = ocr_worker.OCRWorker(self.executable('timeout'))
        self.addCleanup(worker.close)
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            worker.run(self.image, timeout=.15)
        self.assertLess(time.monotonic() - start, 1)
        self.assertTrue(worker.disabled)
        self.assertIsNone(worker.process)
        self.assertNotIn('oneshot', self.events())

    def test_image_failure_is_reported_and_next_image_can_succeed(self):
        worker = ocr_worker.OCRWorker(self.executable())
        self.addCleanup(worker.close)
        with self.assertRaises(subprocess.CalledProcessError):
            worker.run(self.root / 'bad')
        self.assertFalse(worker.disabled)
        self.assertEqual(worker.run(self.image), [{'text': 'TEST original observation'}])
        self.assertEqual(self.events(), ['worker', 'request', 'request'])

    def test_concurrent_callers_are_serialized_and_bound_to_their_image(self):
        executable = self.executable()
        paths = [self.root / f'TEST-{i}.png' for i in range(12)]
        for index, path in enumerate(paths):
            path.write_text(f'TEST frame {index}')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda path: ocr_worker.run_ocr(executable, path), paths))
        self.assertEqual(results, [[{'text': f'TEST frame {i}'}] for i in range(12)])
        self.assertEqual(self.events().count('worker'), 1)
        self.assertEqual(self.events().count('request'), 12)

    def test_atomic_binary_replacement_retires_only_old_worker(self):
        executable = self.executable()
        ocr_worker.run_ocr(executable, self.image)
        old = next(worker for worker in ocr_worker._workers.values()
                   if worker.executable == str(executable.resolve()))
        old_process = old.process
        replacement = self.executable('worker', 'replacement')
        os.replace(replacement, executable)
        self.assertEqual(ocr_worker.run_ocr(executable, self.image), [{'text': 'TEST original observation'}])
        self.assertIsNotNone(old_process.returncode)
        self.assertIsNone(old.process)
        self.assertEqual(self.events().count('worker'), 2)
        # An in-flight caller may have retained the retired object before the
        # global cache switched revisions. It can only use one-shot fallback.
        self.assertEqual(old.run(self.image), [{'text': 'TEST original observation'}])
        self.assertIsNone(old.process)
        self.assertEqual(self.events().count('worker'), 2)

    def test_close_reaps_child_and_closes_private_pipes(self):
        worker = ocr_worker.OCRWorker(self.executable())
        worker.run(self.image)
        process = worker.process
        worker.close()
        worker.close()
        self.assertIsNotNone(process.returncode)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    def test_framework_lifetime_is_bounded_without_changing_results(self):
        worker = ocr_worker.OCRWorker(self.executable())
        self.addCleanup(worker.close)
        with patch.object(ocr_worker, 'MAX_WORKER_REQUESTS', 2):
            worker.run(self.image)
            first = worker.process
            worker.run(self.image)
            self.assertIsNone(first.returncode)
            self.assertEqual(worker.run(self.image), [{'text': 'TEST original observation'}])
            self.assertIsNotNone(first.returncode)
            self.assertNotEqual(first.pid, worker.process.pid)
        self.assertEqual(self.events().count('worker'), 2)


if __name__ == '__main__':
    unittest.main()
