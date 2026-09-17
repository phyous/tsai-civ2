"""End-to-end synthetic TEST memory evidence; no original assets or live calls."""
from copy import deepcopy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from civ2.boot import load_setup_report, verify_setup
from civ2.evidence import canonical
from civ2.memory import parse_memory
from civ2.preferences import GAME_LABELS
from civ2.session import Session
from civ2.verify import VerificationError, verify_run
from test_memory import capsule, wire
from test_verify import initial_save, picture, Evidence
from test_policy import RULES_TEXT


def descriptor(path, data):
    return {'path':path, 'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}


def setup_fixture(parent):
    directory=Path(parent)/'source-setup';directory.mkdir()
    frame=picture();digest=hashlib.sha256(frame).hexdigest()
    states=dict.fromkeys(GAME_LABELS,False);states['Always wait at end of turn']=True
    preferences=dict(autosave_disabled=True,checkbox_before=dict(states),checkbox_after=dict(states),
        other_checkboxes_unchanged=True,before=digest,after=digest,opening=digest,
        changes=[dict(label=k,before=states[k],after=states[k],verified_image=digest)
                 for k in ('Always wait at end of turn','Instant advice','Autosave each turn')])
    auto=dict(name='CA_AUTO.SAV',size=len(initial_save()),modifiedAt='2026-09-16T00:00:00.000Z')
    boundary=dict(phase='after_verified_autosave_off_before_first_observation',startup_inventory=[],
        campaign_inventory=[auto],startup_changes=[dict(name=auto['name'],before=None,after=auto)],
        preferences_sha256=hashlib.sha256(canonical(preferences)).hexdigest())
    data=make_capsule(initial_save(),boundary,digest)
    state=parse_memory(data)
    paths=[];images=[]
    for i in range(3):
        name=f'initial-observer-{i}.png';(directory/name).write_bytes(frame);paths.append(name);images.append(descriptor(name,frame))
    (directory/'initial-observation.json').write_bytes(data)
    report=dict(checks=verify_setup(state),settings=state['settings'],player=state['player'],map_dimensions=[40,50],
        receipts=[],preferences=preferences,campaign_start=boundary,observation_kind='live_memory',
        save_policy='no_saves_during_playthrough',initial_observation=descriptor('initial-observation.json',data),
        initial_observation_sha256=hashlib.sha256(data).hexdigest(),images=images,
        observation_receipt=dict(kind='live_memory',source_images=paths,proof=json.loads(data)['proof'],campaign_start=boundary))
    (directory/'setup.json').write_bytes(canonical(report));load_setup_report(directory,require_no_saves=True)
    return directory,report,frame


def make_capsule(save,boundary,digest,nonces=('a','b'),inventory=None):
    inventory=boundary['campaign_inventory'] if inventory is None else inventory
    return capsule([wire(save,nonce=nonces[0]*32),wire(save,nonce=nonces[1]*32)],
        image_sha256=[digest]*3,save_inventory_initial=inventory,save_inventory_before=inventory,save_inventory_after=inventory,
        campaign_start=boundary)


class FakeObserver:
    def __init__(self,directory,boundary,frame):
        self.directory=Path(directory);self.directory.mkdir();self.campaign_start=None
        self.expected_boundary=boundary;self.frame=frame;self.calls=0;self.failure=None
        self.saved=initial_save();self.adopted=[]
    def adopt_campaign_start(self,boundary):
        if boundary!=self.expected_boundary:raise ValueError('TEST wrong boot baseline')
        self.campaign_start=deepcopy(boundary);self.adopted.append(deepcopy(boundary))
    def read(self,rules_text=None,middle_settle=0.0):
        if self.failure:raise self.failure
        self.calls+=1;digest=hashlib.sha256(self.frame).hexdigest()
        data=make_capsule(self.saved,self.campaign_start,digest,('c','d') if self.calls==1 else ('e','f'))
        paths=[]
        for i in range(3):
            path=self.directory/f'test-{self.calls}-{i}.png';path.write_bytes(self.frame);paths.append(str(path))
        return dict(state=parse_memory(data,rules_text),data=data,receipt=dict(kind='live_memory',
            observation_sha256=hashlib.sha256(data).hexdigest(),source_images=paths,
            proof=json.loads(data)['proof'],campaign_start=deepcopy(self.campaign_start)))


class FakeClient:
    model='jev-TEST';request_count=0;input_tokens_total=0;output_tokens_total=0
    def evaluate(self,state,questions):
        self.request_count+=1;self.input_tokens_total+=100;self.output_tokens_total+=10
        answers={}
        for name,q in questions.items():
            choice='skip' if name=='unit_action' else next(iter(q['criteria']))
            answers[name]=dict(type='choice',choice=choice,confidence=1.0,
                probabilities={key:float(key==choice) for key in q['criteria']})
        return dict(model=self.model,answers=answers,usage=dict(input_tokens=100,output_tokens=10),
            metadata=dict(attempts=1,request_count=self.request_count,latency_ms=1.0,
                rejected_response_attempts=0,rejected_input_tokens=0,rejected_output_tokens=0))


class LiveEvidence:
    """Actual Session/journal code, synthetic original-format capsule and Jev transport."""
    def __init__(self,parent,*,decide=True):
        self.setup,self.setup_report,self.frame=setup_fixture(parent)
        self.observer=FakeObserver(Path(parent)/'observer',self.setup_report['campaign_start'],self.frame)
        self.game=mock.Mock();self.stack=ExitStack()
        self.stack.enter_context(mock.patch('civ2.session.original_rules',return_value=RULES_TEXT))
        self.stack.enter_context(mock.patch('civ2.session.TypeSafeClient',return_value=FakeClient()))
        self.stack.enter_context(mock.patch.object(Session,'publish'))
        self.stack.enter_context(mock.patch('civ2.session.time.sleep'))
        self.directory=Path(parent)/'run'
        self.session=Session(self.directory,game=self.game,observer=self.observer,setup_directory=self.setup,record=False)
        self.session.ui=mock.Mock()
        self.session.ui.save_native.side_effect=AssertionError('TEST no native save fallback')
        digest=hashlib.sha256(self.frame).hexdigest()
        self.session.ui.observe.return_value=dict(sha256=digest,text='TEST ONLY')
        self.session.ui.key.side_effect=lambda key,**kw:[dict(type='key',code=key,down=True,repeat=False,sequence=101),
                                                       dict(type='key',code=key,down=False,repeat=False,sequence=102)]
        self.session.journal.append('screen_observed',screen=digest,path='screens/memory-000000-0.png',classification='normal_map',supported=True)
        try:
            if decide:self.session.choose_unit()
        except Exception:
            self.session.journal.close();self.stack.close()
            raise
    def finish(self,*,checkpoint=True):
        if checkpoint:
            changed=bytearray(self.observer.saved);struct.pack_into('<Hh',changed,28,2,-3950)
            self.observer.saved=bytes(changed);self.session.checkpoint()
        self.session.finish(reason='TEST ONLY; no victory claim');self.stack.close()
    rewrite=Evidence.rewrite
    change_artifact=Evidence.change_artifact


class VerifyMemoryTests(unittest.TestCase):
    def test_full_session_choice_checkpoint_and_verifier_without_game_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            e=LiveEvidence(directory);e.finish();result=verify_run(e.directory,ffprobe=None)
            self.assertEqual(result['integrity'],'passed')
            self.assertEqual(result['decisions']['model_dispatches'],1)
            self.assertEqual(result['decisions']['ordinary_input_events'],2)
            self.assertEqual(result['outcome']['status'],'unverified')
            self.assertFalse(list(e.directory.rglob('*.sav')))
            e.session.ui.save_native.assert_not_called()
            self.assertEqual(e.observer.adopted,[e.setup_report['campaign_start']])

    def test_source_alias_and_backend_switch_are_rejected(self):
        for mode in ('alias','switch','action_alias'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=LiveEvidence(directory);e.finish()
                def change(rows):
                    if mode=='alias':rows[0]['payload']['initial_save']=rows[0]['payload']['initial_observation']
                    elif mode=='switch':next(row for row in rows if row['kind']=='checkpoint')['payload'].pop('observation_kind')
                    else:
                        for row in rows:
                            if row['kind'] in ('model_decision','command_dispatched'):
                                preconditions=row['payload']['action']['preconditions']
                                preconditions['save_sha256']=preconditions.pop('observation_sha256')
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_capsule_image_and_setup_tampering_are_rejected(self):
        for mode in ('capsule','frame','setup','pin'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=LiveEvidence(directory);e.finish()
                if mode in ('capsule','pin'):
                    value=json.loads((e.directory/'observations/d000001.json').read_bytes())
                    if mode=='capsule':value['snapshots'][0]['wire_sha256']='0'*64
                    else:value['helper_sha256']='0'*64
                    e.change_artifact('observations/d000001.json',value)
                elif mode=='frame':(e.directory/'screens/memory-000001-0.png').write_bytes(b'TEST altered PNG')
                else:
                    value=json.loads((e.directory/'setup/setup.json').read_bytes())
                    value['preferences']['checkbox_after']['Autosave each turn']=True
                    e.change_artifact('setup/setup.json',value)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_initial_inventory_cannot_differ_from_verified_boot_even_with_valid_capsule(self):
        with tempfile.TemporaryDirectory() as directory:
            e=LiveEvidence(directory,decide=False);e.finish(checkpoint=False)
            new_entry=dict(name='manual.sav',size=10,modifiedAt='2026-09-16T00:00:01.000Z')
            inventory=e.setup_report['campaign_start']['campaign_inventory']+[new_entry]
            data=capsule([wire(initial_save(),nonce='c'*32),wire(initial_save(),nonce='d'*32)],
                image_sha256=[hashlib.sha256(e.frame).hexdigest()]*3,
                save_inventory_initial=inventory,save_inventory_before=inventory,save_inventory_after=inventory)
            value=json.loads(data);e.change_artifact('initial-observation.json',value)
            def change(rows):
                receipt=rows[0]['payload']['receipt'];receipt['observation_sha256']=hashlib.sha256(data).hexdigest()
                receipt['proof']=value['proof'];receipt['campaign_start']=None
            e.rewrite(change)
            with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_checkpoint_cannot_change_campaign_boundary_even_when_inventory_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            e=LiveEvidence(directory);e.finish()
            value=json.loads((e.directory/'observations/d000001.json').read_bytes())
            value['proof']['campaign_start']=None
            data=canonical(value);e.change_artifact('observations/d000001.json',value)
            def change(rows):
                receipt=next(row for row in rows if row['kind']=='checkpoint')['payload']['receipt']
                receipt['proof']=value['proof'];receipt['observation_sha256']=hashlib.sha256(data).hexdigest();receipt['campaign_start']=None
            e.rewrite(change)
            with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)


if __name__=='__main__':unittest.main()
