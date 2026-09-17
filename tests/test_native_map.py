"""Synthetic TEST map proof; no native game, model, or saved-rule changes."""
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zlib
from PIL import Image
from civ2.dialogs import classify_dialog
from civ2.evidence import canonical
from civ2.memory import MemoryObservationError,parse_memory
from civ2.native_map import NativeMapContext,context_for,evidence_for,LEFT_MAP_REASON
from civ2.run import _native_map_fallback
from civ2.verify import verify_run,VerificationError
from test_memory import capsule,wire,topology
from test_verify import initial_save,picture
from test_verify_memory import LiveEvidence
from test_dialogs import native_map,row


def fixture(data=None):
    image=picture();digest=hashlib.sha256(image).hexdigest()
    data=data or capsule([wire(initial_save()),wire(initial_save(),nonce='b'*32)],image_sha256=[digest]*3)
    observation=native_map();observation['sha256']=digest
    observation['lines'].append(row('TEST unexplained sprite',x=200,y=340,w=150))
    return data,observation,parse_memory(data)


class NativeMapProofTests(unittest.TestCase):
    def test_only_exact_bracketed_frame_can_omit_map_artwork_check(self):
        data,o,state=fixture();ordinary=classify_dialog(o,state=state)
        self.assertEqual(ordinary['reason'],LEFT_MAP_REASON)
        context=context_for(data,o['sha256'],7)
        actual=classify_dialog(o,state=state,native_map_context=context)
        self.assertEqual(actual['kind'],'normal_map');self.assertTrue(actual['supported'])
        self.assertEqual(actual['evidence']['native_map']['image_index'],1)
        self.assertEqual(actual['options'],[]);self.assertIsNone(actual['mechanical_action'])
        o['sha256']='f'*64
        self.assertFalse(classify_dialog(o,state=state,native_map_context=context)['supported'])

    def test_unchecked_boolean_or_dict_never_grants_context(self):
        _,o,state=fixture()
        for context in (True,{'valid':True,'image_sha256':o['sha256']},NativeMapContext(b'{}',o['sha256'],7)):
            self.assertFalse(classify_dialog(o,state=state,native_map_context=context)['supported'])

    def test_outer_frame_and_changed_input_fail_even_with_valid_capsule(self):
        digest=hashlib.sha256(picture()).hexdigest()
        data=capsule([wire(initial_save()),wire(initial_save(),nonce='b'*32)],
                     image_sha256=['a'*64,digest,'b'*64])
        self.assertIsNotNone(context_for(data,digest,7))
        for image,sequence in [('a'*64,7),(digest,8),(digest,True)]:
            with self.assertRaises(MemoryObservationError):context_for(data,image,sequence)

    def test_missing_status_and_control_or_warning_still_fail(self):
        data,o,state=fixture();context=context_for(data,o['sha256'],7)
        for mode in ('status','pane','menu','ok','warning'):
            x=deepcopy(o)
            if mode in ('status','pane','menu'):
                needle={'status':'Moving Units','pane':'World','menu':'Game Kingdom'}[mode]
                x['lines']=[r for r in x['lines'] if not r['text'].startswith(needle)]
            else:x['lines'].append(row('OK' if mode=='ok' else 'Please choose',x=200,y=200,w=100))
            self.assertFalse(classify_dialog(x,state=state,native_map_context=context)['supported'],mode)

    def test_extra_windows_foreign_owner_hit_grid_and_source_tamper_fail(self):
        data,o,_=fixture()
        for change in ('city','modal','foreign','hit','pin'):
            blob=json.loads(data)
            if change=='pin':blob['helper_sha256']='0'*64
            else:
                tree=topology('a'*32)
                if change=='city':tree['windows']=tree['windows'][:1]
                elif change=='modal':tree['active']=200
                elif change=='foreign':tree['active_task']=8192
                else:tree['hit_grid'][0][2]=999
                raw=wire(initial_save(),tree=tree)
                blob['snapshots'][0]={'wire_zlib_base64':base64.b64encode(zlib.compress(raw)).decode(),
                                      'wire_sha256':hashlib.sha256(raw).hexdigest()}
            with self.assertRaises(MemoryObservationError):context_for(canonical(blob),o['sha256'],7)


class NativeMapRunnerVerifierTests(unittest.TestCase):
    def fallback(self,e):
        s=e.session;_,o,_=fixture();o['path']=str(e.directory/'screens'/'memory-000000-0.png')
        original=classify_dialog(o,state=s.state)
        status=dict(paused=True,inputSequence=7,heldKeys=[],buttons=0)
        s.game.rpc.return_value=status
        s.game.request.return_value=picture()
        with mock.patch('civ2.observe.recognize',return_value=deepcopy(o)):
            fresh,result=_native_map_fallback(s,o,original,'')
        return fresh,result

    def test_full_runner_proof_is_distinct_checkpoint_and_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            e=LiveEvidence(directory,decide=False);s=e.session
            original=(e.directory/'screens/memory-000000-0.png').read_bytes()
            state=deepcopy(s.state);fresh,result=self.fallback(e)
            self.assertTrue(result['supported']);self.assertEqual(result['kind'],'normal_map')
            self.assertEqual(s.checkpoints,0);self.assertEqual(s.state,state)
            self.assertEqual((e.directory/'screens/memory-000000-0.png').read_bytes(),original)
            s.ui.key.assert_not_called();s.ui.save_native.assert_not_called();s.game.click.assert_not_called()
            e.finish(checkpoint=False);report=verify_run(e.directory,ffprobe=None)
            self.assertEqual(report['decisions']['native_map_observations'],1)
            self.assertEqual(report['decisions']['model_dispatches'],0)

    def test_only_left_map_unknown_and_live_backend_can_request_probe(self):
        for mode in ('legacy','modal','status','supported'):
            with tempfile.TemporaryDirectory() as directory:
                e=LiveEvidence(directory,decide=False);s=e.session
                _,o,_=fixture();d=dict(kind='unknown',supported=False,reason=LEFT_MAP_REASON)
                before=e.observer.calls
                if mode=='legacy':s.observer=None
                elif mode=='modal':d['kind']='research'
                elif mode=='status':d['reason']='Native moving-unit or end-of-turn status is not uniquely observed'
                else:d['supported']=True
                self.assertEqual(_native_map_fallback(s,o,d,''),(o,d))
                self.assertEqual(e.observer.calls,before);e.finish(checkpoint=False)

    def test_input_during_ocr_and_failed_observer_do_not_grant_context(self):
        for mode in ('input','observer'):
            with tempfile.TemporaryDirectory() as directory:
                e=LiveEvidence(directory,decide=False);s=e.session;_,o,_=fixture()
                o['path']=str(e.directory/'screens/memory-000000-0.png');d=classify_dialog(o,state=s.state)
                status=dict(paused=True,inputSequence=7,heldKeys=[],buttons=0)
                s.game.request.return_value=picture()
                if mode=='input':s.game.rpc.side_effect=[status,{**status,'inputSequence':8}]
                else:e.observer.failure=MemoryObservationError('TEST failed helper')
                with mock.patch('civ2.observe.recognize',return_value=deepcopy(o)):
                    actual=_native_map_fallback(s,o,d,'')
                self.assertEqual(actual,(o,d));s.game.rpc.side_effect=None;e.finish(checkpoint=False)
                report=verify_run(e.directory,ffprobe=None)
                self.assertEqual(report['decisions']['native_map_observation_failures'],1)

    def test_repeated_unknown_frame_can_record_separate_failed_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            e=LiveEvidence(directory,decide=False);s=e.session;_,o,_=fixture()
            o['path']=str(e.directory/'screens/memory-000000-0.png');d=classify_dialog(o,state=s.state)
            e.observer.failure=MemoryObservationError('TEST unavailable')
            for _ in range(2):self.assertEqual(_native_map_fallback(s,o,d,''),(o,d))
            e.finish(checkpoint=False)
            self.assertEqual(verify_run(e.directory,ffprobe=None)['decisions']['native_map_observation_failures'],2)

    def test_stale_middle_frame_retries_before_returning_a_model_context(self):
        for persistent in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                e=LiveEvidence(directory,decide=False);s=e.session;_,o,_=fixture()
                o['path']=str(e.directory/'screens/memory-000000-0.png');d=classify_dialog(o,state=s.state)
                s.game.rpc.return_value=dict(paused=True,inputSequence=7,heldKeys=[],buttons=0)
                image=Image.open(BytesIO(picture())).convert('RGB');image.putpixel((1,1),(255,0,0))
                output=BytesIO();image.save(output,format='PNG');changed=output.getvalue()
                s.game.request.side_effect=[changed,changed,changed] if persistent else [changed,picture()]
                before=e.observer.calls
                with mock.patch('civ2.observe.recognize',return_value=deepcopy(o)):
                    fresh,result=_native_map_fallback(s,o,d,'')
                self.assertEqual(e.observer.calls-before,3 if persistent else 2)
                self.assertEqual(result['supported'],not persistent)
                s.game.click.assert_not_called();s.ui.key.assert_not_called()
                e.finish(checkpoint=False)
                report=verify_run(e.directory,ffprobe=None)
                self.assertEqual(report['decisions']['native_map_observation_failures'],3 if persistent else 1)

    def test_offline_tamper_of_image_sequence_ocr_or_boundary_refuses(self):
        for mode in ('image','sequence','status','receipt','trigger','inventory'):
            with tempfile.TemporaryDirectory() as directory:
                e=LiveEvidence(directory,decide=False);self.fallback(e);e.finish(checkpoint=False)
                def mutate(rows):
                    p=next(r['payload'] for r in rows if r['kind']=='native_map_observed')
                    if mode=='image':p['observation']['sha256']='a'*64
                    elif mode=='sequence':p['input_sequence']=8
                    elif mode=='status':p['observation']['lines']=[r for r in p['observation']['lines'] if r['text']!='Moving Units']
                    elif mode=='receipt':p['receipt']['proof']['image_sha256'][1]='a'*64
                    elif mode=='trigger':p['trigger_reason']='TEST unknown research dialog'
                    else:
                        data=json.loads((e.directory/p['artifact']['path']).read_bytes())
                        data['proof']['campaign_start']=None
                        raw=canonical(data);(e.directory/p['artifact']['path']).write_bytes(raw)
                        p['artifact'].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
                        p['receipt']['proof']=data['proof']
                        p['receipt']['observation_sha256']=hashlib.sha256(canonical(data)).hexdigest()
                e.rewrite(mutate)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)
