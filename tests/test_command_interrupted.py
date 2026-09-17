"""Synthetic TEST failed pointer approaches never authorize clicks or effects."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from civ2.session import Session
from civ2.evidence import Journal
from civ2.verify import verify_run, VerificationError
from test_session_pending import RefusalEvidenceTests, different_picture
from test_session_planning import session
from test_session_receipts import end_turn
from test_verify import picture


def receipt(start=0):
    return dict(issued=False,status='failed',target=[120,150],error='TEST clipped cursor',
        button_down_attempted=False,inputs=[dict(type='relativeMouse',dx=1,dy=-2,
        dispatched=True,emulate=True,via='DOSBox Mouse_CursorMoved',sequence=start+i) for i in (1,2,3)])


class InterruptedTests(unittest.TestCase):
    def evidence(self,directory):
        e=RefusalEvidenceTests().refusal(directory)
        def change(rows):
            event=next(r for r in rows if r['kind']=='model_command_not_dispatched')
            p=event['payload'];event['kind']='model_command_interrupted'
            event['payload']={k:p[k] for k in ('decision','action','before','after')}
            event['payload'].update(receipt=receipt(),input_sequence_before=0,input_sequence_after=3)
        e.rewrite(change);return e

    def test_motion_counted_but_no_command_dispatch_or_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            e=self.evidence(directory);report=verify_run(e.directory,ffprobe=None)['decisions']
            self.assertEqual(report['ordinary_input_events'],3)
            self.assertEqual(report['model_dispatches'],0)
            self.assertEqual(report['undispatched_decisions'],[1])
            self.assertEqual(report['interrupted_pointer_approaches'],[1])

    def test_tampered_or_ambiguous_receipts_fail(self):
        for mode in ('button','attempt','gap','start','source','target','duplicate','effect','dispatch'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=self.evidence(directory)
                def change(rows):
                    event=next(r for r in rows if r['kind']=='model_command_interrupted');p=event['payload']
                    if mode=='button':p['receipt']['inputs'][0]['type']='mouse'
                    elif mode=='attempt':p['receipt']['button_down_attempted']=True
                    elif mode=='gap':p['receipt']['inputs'].pop(1)
                    elif mode=='start':p['input_sequence_before']=1
                    elif mode=='source':p['before']=deepcopy(p['after'])
                    elif mode=='target':p['receipt']['target']=[121,150]
                    elif mode=='duplicate':rows.insert(-1,deepcopy(event))
                    elif mode=='effect':rows.insert(-1,dict(kind='batch_observed_effect',elapsed_ms=event['elapsed_ms'],payload={'decisions':[1]}))
                    else:rows.insert(-1,dict(kind='dialog_dispatched',elapsed_ms=event['elapsed_ms'],payload={'decision':1,'action':p['action']}))
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_prior_declared_gap_establishes_sequence_without_erasing_limitation(self):
        with tempfile.TemporaryDirectory() as directory:
            e=self.evidence(directory)
            def change(rows):
                event=next(r for r in rows if r['kind']=='model_command_interrupted');index=rows.index(event)
                # A separate prior selected decision owns the unaccounted gap.
                model=deepcopy(next(r for r in rows if r['kind']=='model_decision'))
                started=deepcopy(next(r for r in rows if r['kind']=='inference_started'))
                event['payload']['decision']=2;model['payload']['decision']=2;started['payload']['decision']=2
                p=event['payload'];gap={k:deepcopy(p[k]) for k in ('action','before','after')}
                gap.update(decision=1,input_sequence_after=7,reason='cursor_positioning_failed_partial_receipts_unavailable')
                started['elapsed_ms']=model['elapsed_ms']=event['elapsed_ms']
                rows[index:index]=[dict(kind='controller_input_gap',elapsed_ms=event['elapsed_ms'],payload=gap),started,model]
                p.update(receipt=receipt(7),input_sequence_before=7,input_sequence_after=10)
            e.rewrite(change);report=verify_run(e.directory,ffprobe=None)['decisions']
            self.assertEqual(report['interrupted_pointer_approaches'],[2])
            self.assertEqual(report['unverified_input_gaps'],[{'decision':1,'observed_input_sequence_after':7}])

    @mock.patch('civ2.session.time.sleep')
    def test_session_records_only_existing_motion_and_preserves_other_pending(self,sleep):
        with tempfile.TemporaryDirectory() as directory:
            s=session(False);s.journal=Journal(Path(directory)/'run')
            descriptors=[s.journal.artifact('screens/'+name,data) for name,data in
                         [('before.png',picture()),('after.png',different_picture())]]
            observations=[{**d,'path':str(s.journal.directory/d['path'])} for d in descriptors]
            action=dict(id='option_0',preconditions={'image_sha256':descriptors[0]['sha256']},parameters={'center':[120,150]})
            s.decision=dict(id=2,stage='command',receipt='pending',selected_question='dialog_action',
                            answers={'dialog_action':{'choice':'option_0'}})
            s.pending_decisions=[1,2];s.history=[]
            s.game.rpc.return_value=dict(paused=True,heldKeys=[],buttons=0,inputSequence=3)
            s.note_interrupted(action,before=observations[0],after=observations[1],receipt=receipt(),
                               input_sequence_before=0,input_sequence_after=3)
            self.assertEqual(s.pending_decisions,[1]);self.assertEqual(s.decision['receipt'],'not_dispatched')
            s._mark_dispatched(2,'dialog_action',action,[{'issued':True}]);self.assertEqual(s.pending_decisions,[1])
            with self.assertRaises(ValueError):s.note_interrupted(action,before=observations[0],after=observations[1],
                receipt=receipt(),input_sequence_before=0,input_sequence_after=3)
            s.game.rpc.assert_called_once_with('status');s.game.click.assert_not_called();s.ui.key.assert_not_called()
            s.journal.close()


if __name__=='__main__':unittest.main()
