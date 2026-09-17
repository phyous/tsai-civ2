"""Synthetic TEST refusals never become dispatched native-effect batches."""
from copy import deepcopy
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from PIL import Image

from civ2.session import Session
from civ2.evidence import Journal
from civ2.policy import unit_candidates, unit_request_for
from civ2.empire import empire_candidates
from civ2.verify import verify_run, VerificationError
from test_session import dialog
from test_session_planning import session, events
from test_session_receipts import end_turn
from test_session_city_controls import setup as city_setup
from test_city_controls import reviewed
from test_verify import Evidence, picture


def different_picture():
    out=BytesIO();Image.new('RGB',(640,480),(21,31,41)).save(out,format='PNG')
    return out.getvalue()


@mock.patch('civ2.session.time.sleep')
class PendingDispatchTests(unittest.TestCase):
    def test_evaluation_alone_and_failed_validation_do_not_enter_batch(self, sleep):
        s=session(False);actions=unit_candidates(s.state,rules=s.rules)
        s._evaluate(unit_request_for(s.state,actions,s.rules),actions,'unit_action')
        self.assertEqual(s.pending_decisions,[])
        with mock.patch('civ2.session.validate_action',side_effect=ValueError('TEST stale actor')):
            with self.assertRaises(ValueError):s.choose_unit()
        s.ui.key.assert_not_called();self.assertEqual(s.pending_decisions,[])
        with mock.patch('civ2.session.parse_save',return_value=deepcopy(s.state)):s.checkpoint()
        self.assertEqual(events(s,'batch_observed_effect'),[])

    def test_stale_empire_dialog_and_city_images_leave_no_pending_command(self, sleep):
        for kind in ('empire','dialog','city'):
            with self.subTest(kind=kind):
                s=session(False)
                if kind=='city':s,screen=city_setup()
                elif kind=='empire':screen=end_turn(s)
                else:screen=dialog('button')
                s.ui.observe.side_effect=None;s.ui.observe.return_value={'sha256':'e'*64}
                with self.assertRaises(RuntimeError):
                    if kind=='city':s.choose_city_control(screen,reviewed())
                    elif kind=='empire':s.choose_empire(screen,{'turn':1,'actions':[]})
                    else:s.choose_dialog(screen)
                self.assertEqual(len(events(s,'model_decision')),1)
                self.assertEqual(s.pending_decisions,[])
                s.game.click.assert_not_called();s.game.chord.assert_not_called();s.ui.key.assert_not_called()

    def test_only_successful_dispatch_is_batched_once(self, sleep):
        s=session(False);action,_=s.choose_unit()
        self.assertEqual(s.pending_decisions,[1])
        s._mark_dispatched(1,'unit_action',action,[{'issued':True}])
        self.assertEqual(s.pending_decisions,[1])
        with mock.patch('civ2.session.parse_save',return_value=deepcopy(s.state)):s.checkpoint()
        self.assertEqual(events(s,'batch_observed_effect')[0]['decisions'],[1])
        self.assertEqual(s.pending_decisions,[])

    def test_refusal_cleanup_keeps_other_pending_commands_and_uses_no_input(self, sleep):
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory)/'run'
            s=session(False);s.journal=Journal(directory)
            before_bytes=picture();after_bytes=different_picture()
            before=s.journal.artifact('screens/before.png',before_bytes)
            after=s.journal.artifact('screens/after.png',after_bytes)
            screen=end_turn(s);screen['sha256']=before['sha256']
            s.ui.observe.return_value={'sha256':after['sha256']}
            with self.assertRaises(RuntimeError):s.choose_empire(screen,{'turn':1,'actions':[]})
            action=empire_candidates(s.state,screen,{'turn':1,'actions':[]},s.rules)[s.decision['answers']['empire_action']['choice']]
            s.pending_decisions=[9,1]  # Older development-session bookkeeping.
            s.game.rpc.return_value=dict(paused=True,heldKeys=[],buttons=0,inputSequence=7)
            observations=[dict(path=str(Path(directory)/d['path']),sha256=d['sha256']) for d in (before,after)]
            for sequence in (8,True):
                with self.assertRaises((ValueError,RuntimeError)):
                    s.note_undispatched(action,before=observations[0],after=observations[1],
                        input_sequence_before=7,input_sequence_after=sequence)
            self.assertEqual(s.pending_decisions,[9,1])
            s.note_undispatched(action,before=observations[0],after=observations[1],
                input_sequence_before=7,input_sequence_after=7)
            self.assertEqual(s.pending_decisions,[9]);self.assertEqual(s.decision['receipt'],'not_dispatched')
            s._mark_dispatched(1,'empire_action',action,[{'issued':True}])
            self.assertEqual(s.pending_decisions,[9]);self.assertEqual(s.decision['receipt'],'not_dispatched')
            s.game.click.assert_not_called();s.game.chord.assert_not_called();s.ui.key.assert_not_called()
            s.journal.close()


class RefusalEvidenceTests(unittest.TestCase):
    def refusal(self, directory):
        e=Evidence(directory,dispatch=False)
        action=dict(id='option_0',kind='dialog_choice',label='TEST first',
            actor=dict(kind='dialog',id='test',title='TEST dialog'),
            preconditions=dict(save_sha256=e.initial['sha256'],turn=1,
                image_sha256=e.screen['sha256'],width=640,height=480),
            parameters=dict(center=[120,150],observed_text='TEST first',option_index=0))
        request=dict(state=dict(turn=1,mandatory_dialog=dict(title='TEST dialog',options=['TEST first','TEST second'])),
            questions=dict(dialog_action=dict(type='choice',instructions='TEST select one',
                criteria=dict(option_0='TEST first',option_1='TEST second'))))
        response=deepcopy(e.response);response['answers']=dict(dialog_action=dict(type='choice',choice='option_0',
            probabilities=dict(option_0=.7,option_1=.3),confidence=.7))
        e.change_artifact('decisions/request.json',request);e.change_artifact('decisions/response.json',response)
        after=different_picture();path=e.directory/'screens/after.png';path.write_bytes(after)
        descriptor=dict(path='screens/after.png',bytes=len(after),sha256=hashlib.sha256(after).hexdigest())
        def change(rows):
            next(r for r in rows if r['kind']=='model_decision')['payload'].update(action=action,selected_question='dialog_action')
            rows.insert(-1,dict(kind='model_command_not_dispatched',elapsed_ms=rows[-1]['elapsed_ms'],payload=dict(
                decision=1,action=action,before=e.screen,after=descriptor,executes_input=False,
                reason='source_image_changed_before_input',input_sequence_before=0,input_sequence_after=0)))
        e.rewrite(change);return e

    def test_refusal_is_reported_and_not_counted_as_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            e=self.refusal(directory);result=verify_run(e.directory,ffprobe=None)
            self.assertEqual(result['decisions']['source_image_refusals'],[1])
            self.assertEqual(result['decisions']['undispatched_decisions'],[1])
            self.assertEqual(result['decisions']['model_dispatches'],0)

    def test_controller_diagnostic_requires_independent_refusal_proof(self):
        for missing in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                e=self.refusal(directory)
                def change(rows):
                    if missing:rows[:]=[r for r in rows if r['kind']!='model_command_not_dispatched']
                    rows.insert(-1,dict(kind='controller_error',elapsed_ms=rows[-1]['elapsed_ms'],payload=dict(
                        decision=1,error='RuntimeError',reason='TEST stale image',scope='TEST diagnostic only')))
                    rows.insert(-1,dict(kind='controller_update',elapsed_ms=rows[-1]['elapsed_ms'],payload=dict(
                        reason='TEST source update',scope='TEST narrative only')))
                e.rewrite(change)
                if missing:
                    with self.assertRaisesRegex(VerificationError,'separate source-bound'):verify_run(e.directory,ffprobe=None)
                else:
                    report=verify_run(e.directory,ffprobe=None)
                    self.assertEqual(report['decisions']['controller_error_diagnostics'],[1])
                    self.assertEqual(report['decisions']['controller_update_notes'],1)
                    self.assertEqual(report['decisions']['model_dispatches'],0)

    def test_batch_cannot_include_undispatched_duplicate_or_refused_choice(self):
        for mode in ('undispatched','duplicate','refused'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=self.refusal(directory) if mode=='refused' else Evidence(directory,dispatch=mode=='duplicate')
                e.rewrite(lambda rows:rows.insert(-1,dict(kind='batch_observed_effect',elapsed_ms=rows[-1]['elapsed_ms'],
                    payload=dict(decisions=[1,1] if mode=='duplicate' else [1]))))
                with self.assertRaisesRegex(VerificationError,'Native effect batch'):verify_run(e.directory,ffprobe=None)

    def test_refusal_rejects_changed_inputs_same_image_and_wrong_source(self):
        for mode in ('input','boolean','same','source','action'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=self.refusal(directory)
                def change(rows):
                    p=next(r['payload'] for r in rows if r['kind']=='model_command_not_dispatched')
                    if mode=='input':p['input_sequence_after']=1
                    elif mode=='boolean':p['input_sequence_after']=False
                    elif mode=='same':p['after']=deepcopy(p['before'])
                    elif mode=='source':p['before']=deepcopy(p['after'])
                    else:p['action']['label']='TEST different'
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_refused_choice_cannot_later_be_dispatched(self):
        with tempfile.TemporaryDirectory() as directory:
            e=self.refusal(directory)
            def change(rows):
                action=next(r['payload']['action'] for r in rows if r['kind']=='model_command_not_dispatched')
                rows.insert(-1,dict(kind='dialog_dispatched',elapsed_ms=rows[-1]['elapsed_ms'],payload=dict(
                    decision=1,action=action,after=e.screen['sha256'],receipt=dict(
                        before=e.screen['sha256'],point=[120,150],target='TEST first',inputs=[
                            dict(type='mouse',sequence=i,event=event,x=120,y=150,button=0)
                            for i,event in ((1,'mousedown'),(2,'mouseup'))]))))
            e.rewrite(change)
            with self.assertRaisesRegex(VerificationError,'unique prior selected'):verify_run(e.directory,ffprobe=None)


if __name__=='__main__':unittest.main()
