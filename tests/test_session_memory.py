"""Synthetic TEST capsules exercise the actual no-save Session contract offline."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from civ2.evidence import Journal
from civ2.session import Session
from test_policy import RULES_TEXT
from test_verify_memory import FakeClient, FakeObserver, setup_fixture


class SessionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.setup, self.report, self.frame = setup_fixture(self.root)
        self.observer = FakeObserver(self.root/'observer', self.report['campaign_start'], self.frame)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch('civ2.session.original_rules', return_value=RULES_TEXT))
        self.client = self.stack.enter_context(mock.patch('civ2.session.TypeSafeClient', return_value=FakeClient()))
        self.stack.enter_context(mock.patch.object(Session, 'publish'))
        self.stack.enter_context(mock.patch('civ2.session.time.sleep'))
        self.game, self.ui = mock.Mock(), mock.Mock()
        self.ui.save_native.side_effect = AssertionError('TEST: native save is forbidden')
        self.stack.enter_context(mock.patch('civ2.session.UI', return_value=self.ui))
        # Constructor rejection can happen after the journal is opened; retain
        # cleanup even when no Session object is returned to the test.
        def tracked_journal(*args, **kwargs):
            journal = Journal(*args, **kwargs)
            self.stack.callback(journal.close)
            return journal
        self.stack.enter_context(mock.patch('civ2.session.Journal', side_effect=tracked_journal))

    def create(self, **changes):
        arguments = dict(game=self.game, observer=self.observer, setup_directory=self.setup, record=False)
        arguments.update(changes)
        return Session(self.root/'run', **arguments)

    def rows(self):
        return [json.loads(line) for line in (self.root/'run/events.jsonl').read_text().splitlines()]

    def test_boot_boundary_is_adopted_exactly_and_all_snapshot_images_are_retained(self):
        session = self.create()
        self.assertEqual(self.observer.adopted, [self.report['campaign_start']])
        self.assertEqual(self.observer.campaign_start, self.report['campaign_start'])
        self.assertEqual(self.observer.calls, 1)
        begin = self.rows()[0]['payload']
        self.assertEqual(begin['observation_kind'], 'live_memory')
        self.assertEqual(begin['save_policy'], 'no_saves_during_playthrough')
        self.assertNotIn('initial_save', begin)
        self.assertNotIn('save_sha256', session.state['evidence'])
        self.assertEqual(begin['receipt']['campaign_start'], self.report['campaign_start'])
        self.assertEqual(begin['receipt']['proof']['campaign_start'], self.report['campaign_start'])
        for i, image in enumerate(begin['receipt']['images']):
            self.assertEqual(image['path'], f'screens/memory-000000-{i}.png')
            data = (self.root/'run'/image['path']).read_bytes()
            self.assertEqual(data, self.frame)
            self.assertEqual(hashlib.sha256(data).hexdigest(), image['sha256'])
        self.assertEqual(json.loads((self.root/'run/setup/setup.json').read_bytes()), self.report)
        self.assertFalse(list((self.root/'run').rglob('*.sav')))
        self.ui.save_native.assert_not_called()
        self.game.rpc.assert_not_called()

    def test_already_matching_boot_boundary_is_preserved_without_rebaseline(self):
        self.observer.campaign_start = deepcopy(self.report['campaign_start'])
        self.create()
        self.assertEqual(self.observer.adopted, [])
        self.assertEqual(self.observer.calls, 1)

    def test_wrong_existing_boundary_or_missing_setup_rejects_before_read(self):
        for mode in ('changed', 'missing'):
            with self.subTest(mode=mode):
                self.observer.campaign_start = deepcopy(self.report['campaign_start'])
                self.observer.campaign_start['preferences_sha256'] = '0'*64
                with self.assertRaises(ValueError):
                    self.create(**({'setup_directory':None} if mode=='missing' else {}))
                self.assertEqual(self.observer.calls, 0)
                self.client.assert_not_called()
                self.ui.save_native.assert_not_called()

    def test_changed_original_player_state_after_setup_is_not_a_fresh_start(self):
        changed = bytearray(self.observer.saved)
        struct.pack_into('<I', changed, 2264+1396+2, 51)
        self.observer.saved = bytes(changed)
        with self.assertRaisesRegex(ValueError, 'changed after verified'):
            self.create()
        self.ui.save_native.assert_not_called()
        self.assertFalse(list((self.root/'run').rglob('*.sav')))

    def test_checkpoint_records_real_capsule_and_images_without_native_save_or_parser(self):
        session = self.create()
        changed = bytearray(self.observer.saved)
        struct.pack_into('<Hh', changed, 28, 2, -3950)
        self.observer.saved = bytes(changed)
        with mock.patch('civ2.session.parse_save') as save_parser:
            after = session.checkpoint()
        save_parser.assert_not_called()
        self.ui.save_native.assert_not_called()
        self.game.rpc.assert_not_called()
        self.assertEqual(after['turn'], 2)
        record = self.rows()[-1]
        self.assertEqual(record['kind'], 'checkpoint')
        self.assertEqual(record['payload']['observation_kind'], 'live_memory')
        self.assertEqual(record['payload']['artifact']['path'], 'observations/d000001.json')
        self.assertEqual(record['payload']['receipt']['campaign_start'], self.report['campaign_start'])
        self.assertEqual(len(list((self.root/'run/screens').glob('memory-*.png'))), 6)
        self.assertFalse(list((self.root/'run').rglob('*.sav')))

    def test_failed_read_or_image_validation_has_no_fallback_or_checkpoint_event(self):
        session = self.create()
        old_state = deepcopy(session.state)
        self.observer.failure = RuntimeError('TEST: original map not stable')
        with self.assertRaisesRegex(RuntimeError, 'not stable'):
            session.checkpoint()
        self.assertEqual(session.state, old_state)
        self.assertEqual([row['kind'] for row in self.rows()], ['begin'])
        self.ui.save_native.assert_not_called()
        self.game.rpc.assert_not_called()
        self.observer.failure = None
        original_read = self.observer.read
        def changed_frame(**kwargs):
            result = original_read(**kwargs)
            Path(result['receipt']['source_images'][0]).write_bytes(b'TEST altered PNG')
            return result
        self.observer.read = changed_frame
        with self.assertRaisesRegex(ValueError, 'frame differs'):
            session.checkpoint()
        self.assertEqual([row['kind'] for row in self.rows()], ['begin'])
        self.assertFalse(list((self.root/'run').rglob('*.sav')))

    def test_source_hash_alias_is_rejected_before_checkpoint_or_model_use(self):
        session = self.create()
        original_read = self.observer.read
        def mislabeled(**kwargs):
            result = original_read(**kwargs)
            result['state']['evidence']['save_sha256'] = result['state']['evidence']['observation_sha256']
            return result
        self.observer.read = mislabeled
        with self.assertRaises(ValueError):
            session.checkpoint()
        self.assertEqual([row['kind'] for row in self.rows()], ['begin'])
        self.ui.save_native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
