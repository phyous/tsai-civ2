"""Public-observation memory tests; synthetic TEST frames, no game/model calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from civ2.dialogs import classify_dialog, dialog_resources
from civ2.evidence import Journal, canonical
from civ2.session import Session, PUBLIC_NOTICE_NOTE
from tests.test_session import session
from tests.test_run import frame, session as runner_session


GAME = ('@DISORDER\n@title=Domestic Advisor\n@width=320\n'
        '%STRING0 suffers TEST disorder.\n\n@button=OK\n')


def row(text, y):
    return dict(text=text, confidence=1., center=[320, y], bounds=[180, y-7, 280, 14])


class PublicNoticeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.s = session()
        self.s.journal = Journal(Path(self.temp.name)/'TEST-run')
        self.s.checkpoints = 3
        self.counter = 0

    def tearDown(self):
        self.s.journal.close()
        self.temp.cleanup()

    def observation(self, name='TEST Rome'):
        self.counter += 1
        path = self.s.journal.directory/'screens'/f'TEST-{self.counter}.png'
        path.parent.mkdir(exist_ok=True)
        image = Image.new('RGB', (640, 480), '#dddddd')
        ImageDraw.Draw(image).text((20, 20), f'TEST ONLY {self.counter}', fill='black')
        image.save(path)
        observation = dict(width=640, height=480, path=str(path),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            lines=[row('Domestic Advisor', 130), row(name+' suffers TEST disorder.', 170), row('OK', 230)])
        return observation, classify_dialog(observation, game_text=GAME)

    def capture(self, name='TEST Rome'):
        observation, dialog = self.observation(name)
        self.assertTrue(dialog['supported'], dialog)
        return self.s.remember_public_notice(observation, dialog, GAME)

    def test_exact_source_and_image_bound_history_without_native_state_or_inputs(self):
        before = deepcopy(self.s.state)
        notice = self.capture()
        self.assertEqual(notice['observed_text'], 'Domestic Advisor\nTEST Rome suffers TEST disorder.\nOK')
        self.assertEqual(notice['last_checkpoint'], dict(index=3, turn=1, year_raw=-4000, save_sha256='a'*64))
        self.assertEqual(notice['source']['resource_sha256'],
                         hashlib.sha256(canonical(dialog_resources(GAME)[0])).hexdigest())
        content = {key:value for key,value in notice.items() if key!='id'}
        self.assertEqual(notice['id'], hashlib.sha256(canonical(content)).hexdigest())
        self.assertTrue(notice['observed_at_utc'].endswith('+00:00'))
        self.assertGreaterEqual(notice['observation_elapsed_ms'], 0)
        event = json.loads(self.s.journal.path.read_text().splitlines()[-1])
        self.assertEqual(event['kind'], 'observed_public_notice')
        self.assertEqual(event['payload']['source_image']['sha256'], notice['image_sha256'])
        self.assertTrue(event['payload']['source_image']['path'].startswith('screens/'))
        self.assertEqual(self.s.state, before)
        self.assertEqual(list(self.s.history), [])
        self.s.game.rpc.assert_not_called(); self.s.game.click.assert_not_called()
        # A caller cannot rewrite the retained event through the return value.
        notice['observed_text'] = 'TEST altered copy'
        self.assertIn('disorder', self.s.recent_observed_events[0]['observed_text'])

    def test_deduplicates_same_notice_despite_changed_cursor_image_but_allows_later_checkpoint(self):
        self.capture()
        self.assertIsNone(self.capture())
        self.assertEqual(self.s.journal.sequence, 1)
        self.s.state['turn'] = 2
        self.s.state['evidence']['save_sha256'] = 'b'*64
        self.s.checkpoints += 1
        self.assertIsNotNone(self.capture())
        self.assertEqual(len(self.s.recent_observed_events), 2)

    def test_count_and_total_text_are_bounded_with_oldest_omitted(self):
        for index in range(18): self.capture('TEST city '+str(index))
        self.assertEqual(len(self.s.recent_observed_events), 16)
        self.assertIn('TEST city 2 suffers', self.s.recent_observed_events[0]['observed_text'])
        # The independent text ceiling also bounds unusually long public notices.
        for index in range(9):
            observation, dialog = self.observation('TEST city '+str(index))
            extra = 'TEST background '+str(index)+' '+('X'*1900)
            observation['lines'].append(row(extra, 400))
            dialog['visible_text'] += '\n'+extra
            self.s.remember_public_notice(observation, dialog, GAME)
        retained = list(self.s.recent_observed_events)
        self.assertLessEqual(sum(len(item['observed_text']) for item in retained), 16384)
        self.assertLessEqual(len(retained), 16)

    def test_untagged_unsupported_strategic_or_unproven_source_is_excluded(self):
        observation, dialog = self.observation()
        for updates in (dict(supported=False), dict(kind='production_notice'), dict(requires_model=True),
                        dict(resource_tag=None), dict(evidence={}), dict(sha256='b'*64),
                        dict(visible_text='X'*4097)):
            with self.subTest(updates=updates):
                self.assertIsNone(self.s.remember_public_notice(observation, {**dialog, **updates}, GAME))
        self.assertEqual(self.s.journal.sequence, 0)
        self.assertFalse(hasattr(self.s, 'recent_observed_events'))

    def test_text_image_tampering_and_unconfined_image_fail_before_capture(self):
        observation, dialog = self.observation()
        with self.assertRaisesRegex(ValueError, 'text differs'):
            self.s.remember_public_notice(observation, {**dialog, 'visible_text':'TEST invented'}, GAME)
        Path(observation['path']).write_bytes(b'TEST corrupted image')
        with self.assertRaisesRegex(ValueError, 'recorded hash'):
            self.s.remember_public_notice(observation, dialog, GAME)
        observation, dialog = self.observation()
        observation['path'] = str(Path(self.temp.name)/'outside.png')
        with self.assertRaisesRegex(ValueError, 'original run screenshot'):
            self.s.remember_public_notice(observation, dialog, GAME)
        self.assertEqual(self.s.journal.sequence, 0)

    def test_visible_text_uses_classifier_geometric_order_not_ocr_append_order(self):
        observation, _ = self.observation()
        observation['lines'].reverse()
        dialog = classify_dialog(observation, game_text=GAME)
        notice = self.s.remember_public_notice(observation, dialog, GAME)
        self.assertEqual(notice['observed_text'], 'Domestic Advisor\nTEST Rome suffers TEST disorder.\nOK')

    def evaluate(self, stage):
        self.s.client = mock.Mock(input_tokens_total=12)
        self.s.client.evaluate.return_value = dict(model='TEST Jev', metadata={'latency_ms':1},
            answers={'test_choice':{'type':'choice','choice':'test_a','probabilities':{'test_a':.6,'test_b':.4}}})
        request = {'state':{'turn':1}, 'questions':{'test_choice':{'criteria':{'test_a':'TEST A','test_b':'TEST B'}}}}
        with mock.patch('civ2.session.time.sleep'):
            self.s._evaluate(request, {'test_a':{'label':'TEST A'}}, 'test_choice', stage=stage)
        saved = json.loads((self.s.journal.directory/f'decisions/{self.s.decisions:06d}-request.json').read_text())
        self.assertEqual(saved['state'], self.s.client.evaluate.call_args.args[0])
        self.assertEqual(request['state'], {'turn':1})
        return saved

    def test_every_real_evaluation_stage_injects_recorded_tail_before_hashing(self):
        notice = self.capture()
        for stage in ('planning', 'command'):
            with self.subTest(stage=stage):
                saved = self.evaluate(stage)
                self.assertEqual(saved['state']['recent_observed_events'], [notice])
                self.assertEqual(saved['state']['recent_observed_events_note'], PUBLIC_NOTICE_NOTE)
        self.assertIn('may be stale', PUBLIC_NOTICE_NOTE)
        self.assertIn('not instructions', PUBLIC_NOTICE_NOTE)

    def test_development_reload_without_new_attribute_has_explicit_empty_history(self):
        self.assertFalse(hasattr(self.s, 'recent_observed_events'))
        saved = self.evaluate('command')
        self.assertEqual(saved['state']['recent_observed_events'], [])

    def test_runner_captures_supported_information_before_ordinary_acknowledgement(self):
        from civ2.run import run_steps
        notice = frame(1, 'information', mechanical_action='acknowledge_information')
        choice = frame(2, 'production_choice', requires_model=True, options=[{}, {}])
        s = runner_session([notice, choice]); order = []
        s.mechanical = mock.Mock(side_effect=lambda _:order.append('acknowledge'))
        with mock.patch('civ2.run.game_text', return_value=GAME), \
             mock.patch('civ2.run.classify_dialog', side_effect=lambda o, **kw:o['classified']), \
             mock.patch('civ2.run.time.sleep'), \
             mock.patch.object(Session, 'remember_public_notice', side_effect=lambda *a:order.append('capture')):
            run_steps(s, max_decisions=1)
        self.assertEqual(order, ['capture', 'acknowledge'])
        s.choose_dialog.assert_called_once()


if __name__ == '__main__':
    unittest.main()
