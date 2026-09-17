"""Synthetic native-format activation transactions; no emulator or model calls."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct
import tempfile
import unittest
from PIL import Image

from civ2.evidence import canonical
from civ2.save import parse_save
from civ2.unit_activation import activation_candidates,activation_popup,activation_result,CALIBRATION,ACTIVATE
from civ2.verify import verify_run,VerificationError,_ACTIVATION_POPUP_SHA
from test_verify import city_evidence
from test_unit_activation import fixture,popup,GAME,LABELS


def descriptor(path,data):return dict(path=path,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())


def activation_evidence(parent):
    e=city_evidence(parent,identifier='exit_city')[0];data=bytearray((e.directory/'city-test.sav').read_bytes())
    base=13432+14+13*2000+2*20*13+1024
    data[base+6]=2;data[base+15]=2;data[base+16]=0;struct.pack_into('<hh',data,base+22,-1,-1)
    before=parse_save(bytes(data),include_stack_links=True)
    _,image,rules=fixture();rules['leaders'][0]['adjective']='Roman'
    for row in image['lines']:
        if row['text'].startswith('City of '):row['text']='City of TEST Rome, 4000 B.C., Population 10,000 (Treasury: 50 Gold)'
    image['sha256']=e.screen['sha256']
    action=activation_candidates(before,image,rules,ready=True)['activate_city_unit_0']
    pre=action['preconditions'];city={k:pre['city'][k] for k in ('id','owner','name','x','y')}
    request=dict(state=dict(turn=1,city_control_review=dict(actor=pre['city'],observed_title=pre['observed_city_title'],
        year_raw=-4000,reviewed_action_ids=[],labor_checkpoint_ready=True,
        controls={action['id']:action['label'],'exit_city':'TEST Exit'})),questions=dict(city_action=dict(
        type='choice',instructions='TEST select one',criteria={action['id']:action['label'],'exit_city':'TEST Exit'})))
    response=deepcopy(e.response);response['answers']=dict(city_action=dict(type='choice',choice=action['id'],
        confidence=.7,probabilities={action['id']:.7,'exit_city':.3}))
    e.change_artifact('decisions/request.json',request);e.change_artifact('decisions/response.json',response)
    (e.directory/'saves').mkdir(exist_ok=True)
    artifacts=[]
    for n in (1,2):
        name=f'saves/d{n:06d}.sav';(e.directory/name).write_bytes(data);artifacts.append(descriptor(name,bytes(data)))
    afterdata=bytearray(data);afterdata[base+15]=255
    after=parse_save(bytes(afterdata),include_stack_links=True)
    name='saves/d000003.sav';(e.directory/name).write_bytes(afterdata);artifacts.append(descriptor(name,bytes(afterdata)))
    # The selected-radio source is a visibly synthetic image with exact small
    # original control-center colors; its integrity is independently checked.
    selected=Image.new('RGB',(640,480),'#244663')
    for n,y in enumerate((195,220,246,271,296,321)):
        for x in range(243,248):
            for yy in range(y-1,y+2):selected.putpixel((x,yy),(0,0,0) if n==5 else (195,195,195))
    out=BytesIO();selected.save(out,format='PNG');radio_bytes=out.getvalue()
    radio=descriptor('screens/TEST-radio.png',radio_bytes);(e.directory/radio['path']).write_bytes(radio_bytes)
    observed=popup()
    next(r for r in observed['lines'] if r['text']=='TEST Roman Warriors')['text']='Roman Warriors'
    observed['sha256']=e.screen['sha256'];proof=activation_popup(action,observed,GAME,LABELS)
    assert proof['source_sha256']==_ACTIVATION_POPUP_SHA
    selected_proof=deepcopy(proof);selected_proof['source_image_sha256']=radio['sha256']
    commands=[dict(kind='click',point=action['parameters']['center'],source_image_sha256=e.screen['sha256']),
        dict(kind='click',point=proof['option']['center'],source_image_sha256=e.screen['sha256'],popup=proof),
        dict(kind='key',code='Enter',source_image_sha256=radio['sha256'],popup=selected_proof,
             radio=dict(source_image_sha256=radio['sha256'],calibration='classic640-unit-options-radio-centers-v1',
                selected_label=ACTIVATE,selected_bounds=[243,320,5,3],
                unselected_bounds=[[243,y-1,5,3] for y in (195,220,246,271,296)],popup_source_sha256=_ACTIVATION_POPUP_SHA))]
    def keys(code,start):return [dict(type='key',code=code,down=down,repeat=False,sequence=start+i) for i,down in enumerate((True,False))]
    def mouse(point,start):return [dict(type='mouse',event=event,x=point[0],y=point[1],button=0,sequence=start+i)
                                   for i,event in enumerate(('mousedown','mouseup'))]
    def change(rows):
        elapsed=rows[-1]['elapsed_ms']
        def event(kind,**payload):return dict(kind=kind,elapsed_ms=elapsed,payload=payload)
        initial=rows[0];initial['elapsed_ms']=elapsed
        inference=next(r for r in rows if r['kind']=='inference_started');inference['elapsed_ms']=elapsed
        decision=next(r for r in rows if r['kind']=='model_decision');decision['elapsed_ms']=elapsed
        decision['payload'].update(action=action,selected_question='city_action')
        navigation={}
        for field,text,point,start in [('receipt','TEST Rome',[200,200],7),('zoom_receipt','Zoom To City',[250,350],9)]:
            navigation[field]=dict(target=text,point=point,before=e.screen['sha256'],inputs=mouse(point,start))
        rows[:]=[initial,event('unit_activation_enabled',calibration=CALIBRATION,executes_input=False),
            event('checkpoint',artifact=artifacts[0],turn=1,year=-4000),
            event('city_labor_refresh_started',purpose='prepare_labor_choices',decision=None,action=None,city=city,before_save_sha256=artifacts[0]['sha256']),
            event('city_labor_refresh_input',purpose='prepare_labor_choices',decision=None,step='close_city',before=e.screen['sha256'],inputs=keys('Escape',1)),
            event('checkpoint',artifact=artifacts[1],turn=1,year=-4000),
            event('city_labor_checkpoint',purpose='prepare_labor_choices',decision=None,checkpoint=2,save_sha256=artifacts[1]['sha256'],result=None),
            event('city_labor_refresh_input',purpose='prepare_labor_choices',decision=None,step='open_locator',before=e.screen['sha256'],inputs=[
                dict(type='key',code=key,down=down,repeat=False,sequence=i+3) for i,(key,down) in enumerate(
                    [('ShiftLeft',True),('KeyC',True),('KeyC',False),('ShiftLeft',False)])]),
            event('navigate_selected_city',city=city,**navigation),
            event('city_labor_ready',purpose='prepare_labor_choices',decision=None,city=city,save_sha256=artifacts[1]['sha256'],screen=e.screen['sha256']),
            inference,decision,event('unit_activation_started',decision=1,action=action,
                before_revision={'save_sha256':artifacts[1]['sha256']},source_image_sha256=e.screen['sha256'])]
        for n,(step,command) in enumerate(zip(('inspect_unit','select_activation','confirm_activation'),commands)):
            rows.extend([event('unit_activation_step_started',decision=1,step=step,command=command),
                event('unit_activation_step_dispatched',decision=1,step=step,command=command,
                    before=command['source_image_sha256'],after=radio['sha256'] if n==1 else e.screen['sha256'],
                    inputs=keys('Enter',15) if n==2 else mouse(command['point'],11+2*n),
                    pointer_park=None if n==2 else dict(issued=False,target=[2,1],inputs=[]))])
        rows.extend([event('checkpoint',artifact=artifacts[2],turn=1,year=-4000),
            event('batch_observed_effect',decisions=[1]),event('unit_activation_observed',decision=1,checkpoint=3,
                result=activation_result(action,before,after)),event('session_stopped',decisions=1,status='paused',reason='TEST ONLY')])
    e.rewrite(change);return e


class VerifyActivationTests(unittest.TestCase):
    def test_full_selected_icon_radio_confirmation_native_result(self):
        with tempfile.TemporaryDirectory() as directory:
            e=activation_evidence(directory);r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['decisions']['model_dispatches'],1)
            self.assertEqual(r['decisions']['unit_activation_steps'],3)
            self.assertEqual(r['decisions']['unit_activation_results'][0]['status'],'observed_expected_change')
            self.assertFalse(r['completeness']['pending_unit_activation'])

    def test_tampered_identity_readiness_input_radio_and_result_reject(self):
        for mode in ('capability','ready','actor','slot','popup','radio','skip','key','result','replay'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=activation_evidence(directory)
                def change(rows):
                    if mode=='capability':rows[:]=[r for r in rows if r['kind']!='unit_activation_enabled']
                    elif mode=='ready':rows[:]=[r for r in rows if r['kind']!='city_labor_ready']
                    elif mode in ('actor','slot'):
                        a=next(r for r in rows if r['kind']=='model_decision')['payload']['action']
                        if mode=='actor':a['actor']['hp_lost']=10
                        else:a['parameters']['center'][0]+=48
                    elif mode=='result':next(r for r in rows if r['kind']=='unit_activation_observed')['payload']['result']['status']='no_observed_change'
                    elif mode=='replay':
                        event=next(r for r in rows if r['kind']=='unit_activation_step_dispatched');rows.insert(rows.index(event)+1,deepcopy(event))
                    elif mode=='skip':rows[:]=[r for r in rows if not(r['kind']=='unit_activation_step_started' and r['payload']['step']=='confirm_activation')]
                    else:
                        event=next(r for r in rows if r['kind']=='unit_activation_step_started' and r['payload']['step']=='confirm_activation')
                        if mode=='popup':event['payload']['command']['popup']['source_sha256']='a'*64
                        elif mode=='radio':event['payload']['command']['radio']['selected_label']='Disband'
                        else:next(r for r in rows if r['kind']=='unit_activation_step_dispatched' and r['payload']['step']=='confirm_activation')['payload']['inputs'][0]['code']='Escape'
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_opened_popup_without_confirmation_remains_pending_and_undispatched(self):
        with tempfile.TemporaryDirectory() as directory:
            e=activation_evidence(directory)
            def change(rows):
                cut=next(i for i,r in enumerate(rows) if r['kind']=='unit_activation_step_started' and r['payload']['step']=='select_activation')
                rows[cut:-1]=[]
            e.rewrite(change);r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['decisions']['model_dispatches'],0)
            self.assertTrue(r['completeness']['pending_unit_activation'])

    def test_changed_original_radio_pixels_fail_even_with_consistent_new_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            e=activation_evidence(directory);path=e.directory/'screens/TEST-radio.png'
            old=hashlib.sha256(path.read_bytes()).hexdigest()
            with Image.open(path) as original:changed=original.convert('RGB')
            changed.putpixel((243,320),(195,195,195));out=BytesIO();changed.save(out,format='PNG');data=out.getvalue()
            path.write_bytes(data);new=hashlib.sha256(data).hexdigest()
            def change(rows):
                def replace(value):
                    if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
                    if isinstance(value,list):return [replace(v) for v in value]
                    return new if value==old else value
                rows[:]=replace(rows)
            e.rewrite(change)
            with self.assertRaisesRegex(VerificationError,'radio pixels'):verify_run(e.directory,ffprobe=None)

    def test_failed_partial_motion_remains_uncertain_and_blocks_new_input(self):
        for unrelated in (False,True):
            with self.subTest(unrelated=unrelated),tempfile.TemporaryDirectory() as directory:
                e=activation_evidence(directory)
                def change(rows):
                    cut=next(i for i,r in enumerate(rows) if r['kind']=='unit_activation_step_dispatched')
                    first=rows[cut];point=first['payload']['command']['point']
                    failure=dict(kind='unit_activation_failed',elapsed_ms=first['elapsed_ms'],payload=dict(
                        decision=1,step='inspect_unit',reason='TEST failed pointer approach',pointer_park=None,
                        success_not_inferred=True,inputs=[dict(issued=False,target=point,inputs=[
                            dict(type='relativeMouse',dx=1,dy=1,sequence=11,dispatched=True,emulate=True,via='DOSBox Mouse_CursorMoved')])]))
                    if unrelated:failure['payload']['inputs']=[dict(type='key',code='KeyD',down=down,repeat=False,sequence=11+i)
                                                              for i,down in enumerate((True,False))]
                    rows[cut:-1]=[failure]
                e.rewrite(change)
                if unrelated:
                    with self.assertRaisesRegex(VerificationError,'unrelated key'):verify_run(e.directory,ffprobe=None)
                else:
                    r=verify_run(e.directory,ffprobe=None)
                    self.assertEqual(r['decisions']['model_dispatches'],0)
                    self.assertEqual(r['decisions']['unit_activation_failures'][0]['status'],'uncertain_input_not_replayed')
                    self.assertTrue(r['completeness']['pending_unit_activation'])


if __name__=='__main__':unittest.main()
