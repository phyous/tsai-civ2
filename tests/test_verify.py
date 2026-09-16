"""Offline TEST evidence only: generated save bytes and visibly labeled images."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from civ2.boot import verify_setup
from civ2.evidence import Journal, canonical
from civ2.save import parse_save
from civ2.verify import VerificationError, verify_run


def initial_save():
    """Minimal synthetic classic TEST layout, with the requested setup fields."""
    area = 2000
    base = 13432+14+13*area+2*20*13+1024
    data = bytearray(base+26+1600)
    data[:10] = b'CIVILIZE\0\x1a'
    struct.pack_into('<H', data, 10, 39)
    data[12] = 16
    data[252:308] = b'\xff'*56
    struct.pack_into('<Hh', data, 28, 1, -4000)
    data[39] = data[40] = data[41] = 1
    data[44], data[45], data[46], data[47] = 2, 2, 0b111111, 2
    struct.pack_into('<HH', data, 58, 1, 0)
    struct.pack_into('<7H', data, 13432, 80, 50, area, 0, 0, 20, 13)
    civ = 2264+1396
    struct.pack_into('<I', data, civ+2, 50)
    data[civ+19], data[civ+20], data[civ+21] = 6, 4, 1
    data[civ+10] = 255
    struct.pack_into('<hh', data, base, 8, 8)
    data[base+7] = 1
    data[base+15] = data[base+16] = 255
    struct.pack_into('<hh', data, base+18, -1, -1)
    tile = 8*40+4
    data[13446+7*area+6*tile] = 2
    data[13446+7*area+6*tile+4] = 2
    return bytes(data)


def picture(size=(640, 480)):
    image = Image.new('RGB', size, '#244663')
    ImageDraw.Draw(image).text((20, 30), 'TEST ONLY - NOT ORIGINAL GAMEPLAY OR A VICTORY', fill='white')
    output = BytesIO(); image.save(output, format='PNG')
    return output.getvalue()


class Evidence:
    def __init__(self, parent, *, dispatch=True, recording=False):
        self.directory = Path(parent)/'test-evidence'
        self.journal = Journal(self.directory)
        self.initial = self.journal.artifact('initial.sav', initial_save())
        state = parse_save(initial_save())
        self.journal.append('begin', initial_save=self.initial, checks=verify_setup(state),
                            settings=state['settings'], model='jev-latest')
        self.screen = self.journal.artifact('screens/test.png', picture())
        self.journal.append('screen_observed', path=self.screen['path'], screen=self.screen['sha256'],
                            classification='normal_map', supported=True)
        self.action = dict(id='settle', kind='settle', label='TEST found city',
            actor=dict(id=0,type_id=0,owner=1,x=8,y=8),
            preconditions=dict(save_sha256=self.initial['sha256'],turn=1,selected_unit_id=0),
            parameters=dict(key='KeyB'))
        self.request = dict(state=dict(turn=1,selected_unit=deepcopy(self.action['actor'])),
            questions=dict(unit_action=dict(type='choice',instructions='TEST choose one',
                criteria=dict(settle='TEST found city',skip='TEST skip'))))
        self.response = dict(model='jev-1.13.0', answers=dict(unit_action=dict(type='choice',
            choice='settle', probabilities=dict(settle=.7,skip=.3), confidence=.7)),
            usage=dict(input_tokens=100,output_tokens=10),
            metadata=dict(attempts=1,request_count=1,latency_ms=12.5,
                          rejected_response_attempts=0,rejected_input_tokens=0,rejected_output_tokens=0))
        self.journal.append('inference_started', decision=1,
                            request=self.journal.artifact('decisions/request.json',self.request))
        self.journal.append('model_decision',decision=1,selected_question='unit_action',
            action=self.action,response=self.journal.artifact('decisions/response.json',self.response))
        self.dispatch = dict(decision=1,action=self.action,before=self.screen['sha256'],after=self.screen['sha256'],
            inputs=[dict(type='key',code='KeyB',down=True,repeat=False,sequence=1),
                    dict(type='key',code='KeyB',down=False,repeat=False,sequence=2)])
        if dispatch:
            self.journal.append('command_dispatched',**self.dispatch)
        self.journal.append('session_stopped',decisions=1,api_requests=1,input_tokens=100,
                            output_tokens=10,status='paused',reason='TEST ONLY')
        if recording:
            folder=self.directory/'video';folder.mkdir()
            (folder/'full-game.mp4').write_bytes(b'TEST PLACEHOLDER; no ffprobe validation requested')
            manifest=dict(path='full-game.mp4',fps=4,frames=4,samples=2,duration_seconds=1.0,time_compression=False)
            (folder/'recording.json').write_bytes(canonical(manifest))
            samples=[dict(sample=1,elapsed_ms=0,frame=0,sha256=self.screen['sha256'],initial_observation=True),
                     dict(sample=2,elapsed_ms=750,frame=3,sha256=self.screen['sha256'])]
            (folder/'frames.jsonl').write_text('\n'.join(json.dumps(s) for s in samples)+'\n')
            self.journal.append('recording_finalized',**{**manifest,'path':'video/full-game.mp4'})
        self.journal.close()

    def rewrite(self, change):
        path=self.directory/'events.jsonl'
        events=[json.loads(line) for line in path.read_text().splitlines()]
        change(events)
        previous='0'*64
        for index,row in enumerate(events):
            row['sequence']=index+1;row['previous_sha256']=previous;row.pop('sha256',None)
            row['sha256']=hashlib.sha256(canonical(row)).hexdigest();previous=row['sha256']
        path.write_text('\n'.join(canonical(row).decode() for row in events)+'\n')

    def change_artifact(self,name,value):
        data=canonical(value);(self.directory/name).write_bytes(data)
        def change(events):
            def walk(v):
                if isinstance(v,dict):
                    if v.get('path')==name:
                        v.update(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
                    for child in v.values():walk(child)
                elif isinstance(v,list):
                    for child in v:walk(child)
            walk(events)
        self.rewrite(change)

    def terminal(self, **overrides):
        chain=json.loads((self.directory/'events.jsonl').read_text().splitlines()[-1])['sha256']
        # This tests declaration validation, not visual truth. The screenshot is
        # unmistakably synthetic TEST data, and is never distributed as a run.
        review=dict(schema_version=1,game='original-civilization-ii-1.06',source='original_game',
            review_method='human_visual_review',reviewed=True,journal_last_sha256=chain,
            outcome='victory_conquest',screenshots=[self.screen],test_fixture=True)
        review.update(overrides)
        (self.directory/'terminal-review.json').write_bytes(canonical(review))
        return 'terminal-review.json'


class VerifyTests(unittest.TestCase):
    def test_intact_setup_model_choice_receipt_and_unverified_outcome(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d);r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['integrity'],'passed')
            self.assertTrue(all(r['initial_setup']['checks'].values()))
            self.assertEqual(r['decisions']['model_dispatches'],1)
            self.assertEqual(r['decisions']['ordinary_input_events'],2)
            self.assertEqual(r['outcome']['status'],'unverified')
            self.assertFalse(r['completeness']['release_review_ready'])
            self.assertNotIn(str(Path(d)),json.dumps(r))

    def test_raw_hash_chain_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d);p=e.directory/'events.jsonl'
            p.write_text(p.read_text().replace('TEST found city','TEST changed city'))
            with self.assertRaisesRegex(VerificationError,'hash chain'):verify_run(e.directory,ffprobe=None)

    def test_artifact_bytes_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d);(e.directory/'decisions/response.json').write_text('{}')
            with self.assertRaisesRegex(VerificationError,'SHA-256'):verify_run(e.directory,ffprobe=None)

    def test_path_traversal_and_external_symlink_rejected(self):
        for symlink in (False,True):
            with self.subTest(symlink=symlink),tempfile.TemporaryDirectory() as d:
                e=Evidence(d);outside=Path(d)/'outside.sav';outside.write_bytes(initial_save())
                name='../outside.sav'
                if symlink:
                    name='escape.sav';(e.directory/name).symlink_to(outside)
                e.rewrite(lambda rows:rows[0]['payload']['initial_save'].update(path=name))
                with self.assertRaisesRegex(VerificationError,'confined|escapes'):verify_run(e.directory,ffprobe=None)

    def test_wrong_initial_difficulty_rejected_even_when_ledger_hashes_repaired(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d);data=bytearray(initial_save());data[44]=0
            path=e.directory/'initial.sav';path.write_bytes(data)
            e.rewrite(lambda rows:rows[0]['payload']['initial_save'].update(sha256=hashlib.sha256(data).hexdigest()))
            with self.assertRaisesRegex(VerificationError,'setup'):verify_run(e.directory,ffprobe=None)

    def test_invalid_probability_distribution_rejected_without_repair(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d);e.response['answers']['unit_action']['probabilities']['settle']=.2
            e.change_artifact('decisions/response.json',e.response)
            with self.assertRaisesRegex(VerificationError,'probability'):verify_run(e.directory,ffprobe=None)

    def test_selected_choice_and_criterion_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d);e.response['answers']['unit_action'].update(choice='skip',probabilities=dict(settle=.3,skip=.7))
            e.change_artifact('decisions/response.json',e.response)
            with self.assertRaisesRegex(VerificationError,'actual model choice'):verify_run(e.directory,ffprobe=None)

    def test_dispatch_cannot_swap_model_action_or_key(self):
        for field in ('action','inputs'):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as d:
                e=Evidence(d)
                def change(rows):
                    payload=next(r['payload'] for r in rows if r['kind']=='command_dispatched')
                    if field=='action':payload['action']['parameters']['key']='KeyD'
                    else:
                        for receipt in payload['inputs']:receipt['code']='KeyD'
                e.rewrite(change)
                with self.assertRaisesRegex(VerificationError,'differs|exactly'):verify_run(e.directory,ffprobe=None)

    def test_missing_screenshot_and_duplicate_dispatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d);(e.directory/e.screen['path']).unlink()
            with self.assertRaisesRegex(VerificationError,'missing'):verify_run(e.directory,ffprobe=None)
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d)
            def duplicate(rows):
                dispatch=next(r for r in rows if r['kind']=='command_dispatched')
                rows.insert(rows.index(dispatch)+1,deepcopy(dispatch))
            e.rewrite(duplicate)
            with self.assertRaisesRegex(VerificationError,'unique prior'):verify_run(e.directory,ffprobe=None)

    def test_actor_cannot_bind_another_native_save_slot(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d)
            e.rewrite(lambda rows:next(r for r in rows if r['kind']=='model_decision')['payload']['action']['actor'].update(id=7))
            with self.assertRaisesRegex(VerificationError,'owned unit'):verify_run(e.directory,ffprobe=None)

    def test_unsupported_operation_or_held_key_cannot_pass_as_ordinary_input(self):
        for kind in ('guestWrite','held_key'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                e=Evidence(d)
                def change(rows):
                    p=next(r['payload'] for r in rows if r['kind']=='command_dispatched')
                    if kind=='guestWrite':p['inputs'][0]['type']='guestWrite'
                    else:p['inputs']=p['inputs'][:1]
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_dialog_cursor_receipt_is_bound_to_the_selected_observed_option(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d)
            action=dict(id='option_0',kind='dialog_choice',label='TEST first',
                actor=dict(kind='dialog',id='test',title='TEST production'),
                preconditions=dict(save_sha256=e.initial['sha256'],turn=1,
                    image_sha256=e.screen['sha256'],width=640,height=480),
                parameters=dict(center=[120,150],observed_text='TEST first',option_index=0))
            request=dict(state=dict(turn=1,mandatory_dialog=dict(title='TEST production',options=['TEST first','TEST second'])),
                questions=dict(dialog_action=dict(type='choice',instructions='TEST select one',
                    criteria=dict(option_0='TEST first',option_1='TEST second'))))
            response=deepcopy(e.response)
            response['answers']=dict(dialog_action=dict(type='choice',choice='option_0',
                probabilities=dict(option_0=.7,option_1=.3),confidence=.7))
            e.change_artifact('decisions/request.json',request);e.change_artifact('decisions/response.json',response)
            wrapper=dict(issued=True,target=[120,150],observed_cursor=[121,150],tolerance=3,
                inputs=[dict(type='relativeMouse',sequence=10,dx=10,dy=0,queued=True,via='SDL_SendMouseMotion'),
                        dict(type='mouse',sequence=11,event='mousedown',x=310,y=225,button=0),
                        dict(type='mouse',sequence=12,event='mouseup',x=310,y=225,button=0)])
            def change(rows):
                model=next(r['payload'] for r in rows if r['kind']=='model_decision')
                model.update(action=action,selected_question='dialog_action')
                event=next(r for r in rows if r['kind']=='command_dispatched')
                event.update(kind='dialog_dispatched',payload=dict(decision=1,action=action,after=e.screen['sha256'],
                    receipt=dict(before=e.screen['sha256'],point=[120,150],target='TEST first',inputs=[wrapper])))
            e.rewrite(change)
            self.assertEqual(verify_run(e.directory,ffprobe=None)['decisions']['model_dispatches'],1)
            def wrong(rows):
                event=next(r for r in rows if r['kind']=='dialog_dispatched')
                event['payload']['receipt']['inputs'][0]['target']=[122,150]
            e.rewrite(wrong)
            with self.assertRaisesRegex(VerificationError,'different dialog option'):verify_run(e.directory,ffprobe=None)
            def recovery(rows):
                event=next(r for r in rows if r['kind']=='dialog_dispatched')
                event.update(kind='dialog_keyboard_recovery',payload=dict(decision=1,label='TEST first',
                    before=e.screen['sha256'],after=e.screen['sha256'],
                    inputs=[dict(type='key',code='Enter',down=down,repeat=False,sequence=20+i)
                            for i,down in enumerate((True,False))]))
            e.rewrite(recovery)
            recovered=verify_run(e.directory,ffprobe=None)
            self.assertEqual(recovered['decisions']['manually_reviewed_keyboard_recoveries'],[1])
            self.assertEqual(recovered['decisions']['model_dispatches'],0)
            self.assertFalse(recovered['completeness']['release_review_ready'])

    def test_empire_implicit_decision_binding_and_no_forged_forced_key(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d)
            action=dict(id='open_tax',kind='empire_menu',label='TEST review tax',actor=dict(kind='empire',player_id=1),
                preconditions=dict(save_sha256=e.initial['sha256'],turn=1,image_sha256=e.screen['sha256'],
                    screen_kind='end_turn'),parameters=dict(key='KeyT',modifiers=['ShiftLeft']))
            request=dict(state=dict(turn=1),questions=dict(empire_action=dict(type='choice',instructions='TEST choose',
                criteria=dict(open_tax='TEST review tax',finish_turn='TEST finish'))))
            response=deepcopy(e.response);response['answers']=dict(empire_action=dict(type='choice',choice='open_tax',
                probabilities=dict(open_tax=.7,finish_turn=.3),confidence=.7))
            e.change_artifact('decisions/request.json',request);e.change_artifact('decisions/response.json',response)
            def change(rows):
                model=next(r['payload'] for r in rows if r['kind']=='model_decision')
                model.update(action=action,selected_question='empire_action')
                event=next(r for r in rows if r['kind']=='command_dispatched')
                keys=[('ShiftLeft',True),('KeyT',True),('KeyT',False),('ShiftLeft',False)]
                event.update(kind='empire_command_dispatched',payload=dict(action=action,
                    before=e.screen['sha256'],after=e.screen['sha256'],inputs=[dict(type='key',code=k,down=down,
                        repeat=False,sequence=i+1) for i,(k,down) in enumerate(keys)]))
            e.rewrite(change)
            self.assertEqual(verify_run(e.directory,ffprobe=None)['decisions']['model_dispatches'],1)
            def forge(rows):
                bad=deepcopy(action);bad.update(id='finish_turn');bad['parameters']=dict(key='KeyK',modifiers=['ControlLeft'])
                rows.append(dict(kind='forced_empire_command',elapsed_ms=rows[-1]['elapsed_ms'],payload=dict(action=bad)))
            e.rewrite(forge)
            with self.assertRaisesRegex(VerificationError,'command mapping'):verify_run(e.directory,ffprobe=None)

    def test_malformed_schema_raises_fixed_verification_error(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d)
            e.rewrite(lambda rows:rows[0]['payload'].pop('initial_save'))
            with self.assertRaisesRegex(VerificationError,'Evidence structure'):verify_run(e.directory,ffprobe=None)

    def test_undispatched_response_is_reported_not_counted_as_gameplay(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d,dispatch=False);r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['decisions']['undispatched_decisions'],[1])
            self.assertEqual(r['decisions']['model_dispatches'],0)

    def test_recording_counts_and_missing_ffprobe_disclosed(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d,recording=True);r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['recording']['duration_seconds'],1)
            self.assertEqual(r['recording']['ffprobe']['status'],'unavailable')
            self.assertFalse(r['recording']['journal_hash_anchored'])
            self.assertFalse(r['completeness']['release_review_ready'])
            path=e.directory/'video/recording.json';data=json.loads(path.read_text());data['frames']=8
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(VerificationError,'manifest and journal'):verify_run(e.directory,ffprobe=None)

    def test_recording_ledger_invalid_timing_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d,recording=True);path=e.directory/'video/frames.jsonl'
            path.write_text(path.read_text().replace('750','75000'))
            with self.assertRaisesRegex(VerificationError,'frame/time'):verify_run(e.directory,ffprobe=None)

    def test_actual_ffprobe_integration_on_generated_test_video(self):
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            self.skipTest('ffmpeg/ffprobe unavailable')
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d,recording=True)
            subprocess.run([shutil.which('ffmpeg'),'-v','error','-y','-loop','1','-framerate','4',
                '-i',str(e.directory/e.screen['path']),'-frames:v','4','-c:v','libx264','-pix_fmt','yuv420p',
                str(e.directory/'video/full-game.mp4')],check=True,capture_output=True)
            r=verify_run(e.directory)
            self.assertEqual(r['recording']['ffprobe']['status'],'passed')
            self.assertEqual(r['recording']['ffprobe']['width'],640)
            self.assertEqual(r['outcome']['status'],'unverified')

    def test_terminal_review_must_explicitly_bind_final_journal_and_original_image(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d);name=e.terminal();r=verify_run(e.directory,terminal_review=name,ffprobe=None)
            self.assertEqual(r['outcome']['status'],'human_reviewed')
            self.assertIn('does not recognize victory',r['outcome']['verification'])
            self.assertFalse(r['completeness']['release_review_ready'])
            e.terminal(journal_last_sha256='0'*64)
            with self.assertRaisesRegex(VerificationError,'different journal'):verify_run(e.directory,terminal_review=name,ffprobe=None)

    def test_ledger_win_claim_alone_does_not_verify_outcome(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d)
            e.rewrite(lambda rows:rows[-1]['payload'].update(status='victory',reason='TEST claim'))
            r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['outcome']['status'],'unverified')

    def test_terminal_screenshot_wrong_size_blank_or_hash_rejected(self):
        for mode in ('wrong_size','blank','wrong_hash'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                e=Evidence(d)
                if mode=='wrong_size':data=picture((320,240))
                elif mode=='blank':
                    out=BytesIO();Image.new('RGB',(640,480)).save(out,format='PNG');data=out.getvalue()
                else:data=picture()
                name='terminal.png';(e.directory/name).write_bytes(data)
                desc=dict(path=name,bytes=len(data),sha256='0'*64 if mode=='wrong_hash' else hashlib.sha256(data).hexdigest())
                review=e.terminal(screenshots=[desc])
                with self.assertRaises(VerificationError):verify_run(e.directory,terminal_review=review,ffprobe=None)


if __name__=='__main__':
    unittest.main()
