"""Synthetic native-format evidence; no real game input or victory claim."""
from copy import deepcopy
import hashlib
import tempfile
import unittest

from civ2.evidence import canonical
from civ2.save import parse_save
from civ2.verify import VerificationError, verify_run
from test_verify import Evidence, initial_save, city_evidence
from test_controller_update_notes import append_note


F3_CHANGE = ('Support original complete two-contact F3 report with independently observed '
             'selected radio and separate model-only contact/button choices; no Enter follows contact selection')


def production_return_evidence(directory):
    e = Evidence(directory, unit_type=2)
    raw = parse_save(initial_save(2))['units'][0]
    assert raw['type'] is None and 'hp' not in raw and 'specification' not in raw
    noted = {**raw, 'type': 'Warriors', 'hp': 10,
             'specification': {'id': 2, 'name': 'Warriors', 'max_hp': 10}}
    pre = dict(save_sha256=e.initial['sha256'], turn=1, image_sha256=e.screen['sha256'])
    finish = dict(id='finish_turn', kind='finish_turn', label='TEST finish turn',
                  actor={'kind': 'empire', 'player_id': 1},
                  preconditions={**pre, 'screen_kind': 'end_turn'},
                  parameters={'key': 'Enter', 'modifiers': []})
    proceed = dict(id='option_1', kind='dialog_choice', label='Continue',
                   actor={'kind': 'dialog', 'id': 'production_notice', 'title': 'TEST Rome builds Warriors.'},
                   preconditions={**pre, 'width': 640, 'height': 480},
                   parameters={'center': [120, 150], 'observed_text': 'Continue', 'option_index': 1})

    def request(question, criteria, state):
        return dict(state={'turn': 1, **state}, questions={question: dict(
            type='choice', instructions='TEST independent choice', criteria=criteria)})

    def response(question, criteria, chosen):
        result = deepcopy(e.response)
        result['answers'] = {question: dict(type='choice', choice=chosen, confidence=.7,
            probabilities={k: .7 if k == chosen else .3 for k in criteria})}
        return result

    first = {'finish_turn': finish['label'], 'open_tax': 'TEST tax'}
    second = {'option_0': 'Zoom to City', 'option_1': 'Continue'}
    e.change_artifact('decisions/request.json', request('empire_action', first, {}))
    e.change_artifact('decisions/response.json', response('empire_action', first, 'finish_turn'))

    def artifact(name, value):
        data = canonical(value)
        (e.directory/name).write_bytes(data)
        return dict(path=name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))

    req = artifact('decisions/continue-request.json', request('dialog_action', second,
        {'mandatory_dialog': {'title': proceed['actor']['title'], 'options': list(second.values())}}))
    res = artifact('decisions/continue-response.json', response('dialog_action', second, 'option_1'))
    note = dict(change='Resolve pending FinishTurn after production returns to owned unit input',
        finish_decision=1, continue_decision=2, source_turn=1, notice_image=e.screen['sha256'],
        selected_unit=noted, save_sha256=e.initial['sha256'], current_image=e.screen['sha256'],
        turn_advanced=False, executes_input=False)

    def change(rows):
        model = next(r for r in rows if r['kind']=='model_decision')
        model['payload'].update(action=finish, selected_question='empire_action')
        dispatch = next(r for r in rows if r['kind']=='command_dispatched')
        dispatch.update(kind='empire_command_dispatched', payload=dict(decision=1, action=finish,
            before=e.screen['sha256'], after=e.screen['sha256'], inputs=[
                dict(type='key',code='Enter',down=down,repeat=False,sequence=i+1)
                for i,down in enumerate((True,False))]))
        stop = rows.pop()
        stop['payload'].update(decisions=2, api_requests=2, input_tokens=200, output_tokens=20)
        def event(kind, **payload):
            return dict(kind=kind, elapsed_ms=stop['elapsed_ms'], payload=payload)
        rows.extend([
            event('inference_started', decision=2, request=req),
            event('model_decision', decision=2, action=proceed, selected_question='dialog_action', response=res),
            event('dialog_dispatched', decision=2, action=proceed, after=e.screen['sha256'],
                receipt=dict(before=e.screen['sha256'], target='Continue', point=[120,150], inputs=[
                    dict(type='mouse', sequence=i+3, event=kind, x=120, y=150, button=0)
                    for i,kind in enumerate(('mousedown','mouseup'))])),
            event('checkpoint', artifact=e.initial, turn=1, year=-4000),
            event('controller_update', **note), stop])
    e.rewrite(change)
    return e


class ProductionReturnNotes(unittest.TestCase):
    def report(self, e):
        return verify_run(e.directory, ffprobe=None)

    def mutate(self, e, change):
        e.rewrite(lambda rows: change(next(r['payload'] for r in rows if r['kind']=='controller_update')))

    def test_portable_null_name_accepts_enrichment_without_extra_input_or_effect(self):
        with tempfile.TemporaryDirectory() as d:
            e = production_return_evidence(d)
            result = self.report(e)
            self.assertEqual(result['decisions']['controller_update_notes'], 1)
            self.assertEqual(result['decisions']['model_dispatches'], 2)
            self.assertEqual(result['decisions']['ordinary_input_events'], 4)
            self.assertFalse(result['completeness']['release_review_ready'])
            e.rewrite(lambda rows: rows.__setitem__(slice(None), [r for r in rows if r['kind']!='controller_update']))
            without = self.report(e)
            self.assertEqual(result['completeness'], without['completeness'])

    def test_every_native_value_and_json_type_remain_exact(self):
        for field, value in [('id', 30), ('type_id', 3), ('owner', True), ('x', 10), ('y', 10),
                ('veteran', 0), ('hp_lost', 1), ('movement_thirds_spent', 1), ('order_id', 2),
                ('home_city_id', 10), ('counter_or_commodity', 1), ('waiting', 0), ('goto', {'x': 1, 'y': 1})]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as d:
                e = production_return_evidence(d)
                self.mutate(e, lambda p: p['selected_unit'].update({field: value}))
                with self.assertRaisesRegex(VerificationError, 'eligible owned unit'): self.report(e)

    def test_missing_native_fields_and_inconsistent_enrichment_rejected(self):
        changes = [lambda u:u.pop('goto'), lambda u:u.update(extra='unbound'),
                   lambda u:u.update(type=None), lambda u:u.update(hp=True), lambda u:u.update(hp=9),
                   lambda u:u['specification'].update(id=3), lambda u:u['specification'].update(id=True),
                   lambda u:u['specification'].update(name='Settlers'), lambda u:u['specification'].update(max_hp=0)]
        for change in changes:
            with self.subTest(change=changes.index(change)), tempfile.TemporaryDirectory() as d:
                e = production_return_evidence(d)
                self.mutate(e, lambda p:change(p['selected_unit']))
                with self.assertRaisesRegex(VerificationError, 'eligible owned unit'): self.report(e)

    def test_consistent_statistics_are_diagnostic_not_independent_rules_attestation(self):
        with tempfile.TemporaryDirectory() as d:
            e = production_return_evidence(d)
            before = self.report(e)
            def change(p):
                p['selected_unit']['hp'] = 20
                p['selected_unit']['specification']['max_hp'] = 20
            self.mutate(e, change)
            after = self.report(e)
            self.assertEqual(before['decisions'], after['decisions'])
            self.assertEqual(before['completeness'], after['completeness'])

    def test_stale_decisions_revision_image_or_authority_claim_rejected(self):
        for field, value in [('finish_decision', 2), ('continue_decision', 1), ('source_turn', 2),
                             ('notice_image', 'a'*64), ('save_sha256', 'a'*64),
                             ('current_image', 'a'*64), ('turn_advanced', True), ('executes_input', True)]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as d:
                e = production_return_evidence(d)
                self.mutate(e, lambda p:p.update({field:value}))
                with self.assertRaises(VerificationError): self.report(e)


class F3ControllerNote(unittest.TestCase):
    def test_exact_historical_note_does_not_close_pending_city_or_add_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            e, _, _ = city_evidence(d)
            before = verify_run(e.directory, ffprobe=None)
            append_note(e, {'change': F3_CHANGE, 'executes_input': False})
            after = verify_run(e.directory, ffprobe=None)
            self.assertEqual(after['decisions']['controller_update_notes'], 1)
            for key in ('model_dispatches', 'ordinary_input_events', 'completed_city_reviews'):
                self.assertEqual(after['decisions'][key], before['decisions'][key])
            self.assertEqual(after['completeness'], before['completeness'])
            self.assertTrue(after['completeness']['pending_city_control'])

    def test_only_exact_historical_string_shape_and_false_boolean_accepted(self):
        for payload in ({'change': F3_CHANGE+'!', 'executes_input': False},
                        {'change': F3_CHANGE, 'executes_input': True},
                        {'change': F3_CHANGE, 'executes_input': 0}, {'change': F3_CHANGE},
                        {'change': F3_CHANGE, 'executes_input': False, 'clears_pending': True}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as d:
                e = Evidence(d); append_note(e, payload)
                with self.assertRaises(VerificationError): verify_run(e.directory, ffprobe=None)


if __name__=='__main__': unittest.main()
