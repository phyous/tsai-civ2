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
from civ2.verify import VerificationError, _inputs, verify_run


def initial_save(unit_type=0):
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
    data[base+6] = unit_type
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
    def __init__(self, parent, *, dispatch=True, recording=False, unit_type=0):
        self.directory = Path(parent)/'test-evidence'
        self.journal = Journal(self.directory)
        self.initial = self.journal.artifact('initial.sav', initial_save(unit_type))
        state = parse_save(initial_save(unit_type))
        self.journal.append('begin', initial_save=self.initial, checks=verify_setup(state),
                            settings=state['settings'], model='jev-latest')
        self.screen = self.journal.artifact('screens/test.png', picture())
        self.journal.append('screen_observed', path=self.screen['path'], screen=self.screen['sha256'],
                            classification='normal_map', supported=True)
        self.action = dict(id='settle', kind='settle', label='TEST found city',
            actor=dict(id=0,type_id=unit_type,owner=1,x=8,y=8),
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

    def add_plan(self):
        state=parse_save(initial_save());actor={k:state['units'][0].get(k) for k in
            ('id','owner','type_id','x','y','home_city_id','veteran')}
        task=dict(id='hold_one_turn',task='hold',label='TEST hold objective',actor=actor,
            preconditions=dict(save_sha256=self.initial['sha256'],turn=1,selected_unit_id=0),target={'turn':2})
        request=dict(state=dict(turn=1,selected_unit=actor,planning=dict(targets={
            'hold_one_turn':dict(task='hold',target={'turn':2}),
            'settle_8_8':dict(task='settle',target={'x':8,'y':8})})),
            questions=dict(task_choice=dict(type='choice',instructions='TEST context only',
                criteria=dict(hold_one_turn='TEST hold objective',settle_8_8='TEST settle objective'))))
        response=deepcopy(self.response);response['answers']=dict(task_choice=dict(type='choice',choice='hold_one_turn',
            probabilities=dict(hold_one_turn=.7,settle_8_8=.3),confidence=.7))
        descriptors=[]
        for name,value in [('decisions/plan-request.json',request),('decisions/plan-response.json',response)]:
            data=canonical(value);(self.directory/name).write_bytes(data)
            descriptors.append(dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        plan=dict(candidate=task,actor=actor,current_save_sha256=self.initial['sha256'],created_turn=1,
            expires_turn=9,observations=0,status='active',reason='TEST context only',decision_id=1)
        self.request['state']['persistent_plan']=dict(planning_decision=1,task='hold',target={'turn':2},
            label=task['label'],actor=actor,status='active',created_turn=1,expires_turn=9)
        self.change_artifact('decisions/request.json',self.request)
        def change(rows):
            rows[0]['payload']['planning_enabled']=True
            first=next(i for i,r in enumerate(rows) if r['kind']=='inference_started')
            for row in rows:
                if row['payload'].get('decision')==1:row['payload']['decision']=2
            elapsed=rows[first]['elapsed_ms']
            extra=[dict(kind='inference_started',elapsed_ms=elapsed,payload=dict(decision=1,request=descriptors[0],stage='planning')),
                   dict(kind='model_plan',elapsed_ms=elapsed,payload=dict(decision=1,response=descriptors[1],
                       selected_question='task_choice',task=task,executes_input=False)),
                   dict(kind='plan_status',elapsed_ms=elapsed,payload=dict(planning_decision=1,plan=plan,
                       previous_status=None,executes_input=False,checkpoint=0))]
            rows[first:first]=extra
        self.rewrite(change)


def city_evidence(parent, identifier='open_buy_quote', *, forced=False):
    """Native-format TEST checkpoint, with independent explicit city UI bindings."""
    e=Evidence(parent)
    data=bytearray(initial_save())
    city_base=13432+14+13*2000+2*20*13+1024+26
    data[city_base:city_base]=bytes(88)
    struct.pack_into('<H',data,60,1)
    struct.pack_into('<hh',data,city_base,8,8)
    data[city_base+8]=data[city_base+9]=1
    data[city_base+32:city_base+41]=b'TEST Rome'
    name='city-test.sav';(e.directory/name).write_bytes(data)
    descriptor=dict(path=name,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
    actor=dict(kind='city',id=0,owner=1,name='TEST Rome',x=8,y=8)
    pre=dict(save_sha256=descriptor['sha256'],turn=1,image_sha256=e.screen['sha256'],
             width=640,height=480,screen_kind='city_screen',observed_city_title='City of TEST Rome, 4000 B.C.',
             year_raw=-4000,reviewed_action_ids=['change_production','open_buy_quote'] if forced else [])
    buttons={'change_production':('Change','production_choice'),
             'open_buy_quote':('Buy','buy_quote'),'exit_city':('Exit','original_map')}
    native,next_screen=buttons[identifier]
    action=dict(id=identifier,kind='city_control',label='TEST '+identifier,actor=actor,preconditions=pre,
        parameters=dict(center=[120,150],observed_text=native,button_index=0,control='button',
                        only_open_menu=identifier!='exit_city',expected_screen=next_screen,
                        purchase_authorized=False,confirmation_requires_separate_choice=identifier=='open_buy_quote'))
    criteria={key:'TEST '+key for key in buttons}
    request=dict(state=dict(turn=1,city_control_review=dict(actor=actor,observed_title=pre['observed_city_title'],
        year_raw=-4000,reviewed_action_ids=pre['reviewed_action_ids'],controls=criteria)),
        questions=dict(city_action=dict(type='choice',instructions='TEST choose one actual city button',criteria=criteria)))
    response=deepcopy(e.response)
    response['answers']=dict(city_action=dict(type='choice',choice=identifier,confidence=.7,
        probabilities={key:.7 if key==identifier else .15 for key in buttons}))
    e.change_artifact('decisions/request.json',request);e.change_artifact('decisions/response.json',response)
    reviewed=dict(city_id=0,city_name='TEST Rome',year_raw=-4000,actions=list(pre['reviewed_action_ids']))
    def change(rows):
        rows.insert(1,dict(kind='checkpoint',elapsed_ms=rows[0]['elapsed_ms'],payload=dict(artifact=descriptor,turn=1,year=-4000)))
        selected=next(r for r in rows if r['kind']=='model_decision')
        selected['payload'].update(action=action,selected_question='city_action')
        dispatch=next(r for r in rows if r['kind']=='command_dispatched')
        dispatch.update(kind='city_control_dispatched',payload=dict(decision=None if forced else 1,
            action=action,reviewed=reviewed,before=e.screen['sha256'],after=e.screen['sha256'],inputs=[
                dict(type='mouse',sequence=1,event='mousedown',x=120,y=150,button=0),
                dict(type='mouse',sequence=2,event='mouseup',x=120,y=150,button=0)]))
        if forced:
            rows[:]=[r for r in rows if r['kind'] not in ('inference_started','model_decision')]
            rows.insert(rows.index(dispatch),dict(kind='forced_city_control',elapsed_ms=dispatch['elapsed_ms'],
                payload=dict(action=action,reviewed=reviewed,reason='TEST only observed Exit remains')))
    e.rewrite(change)
    return e,action,reviewed


def labor_evidence(parent, *, mode='remove_worker', outcome='observed_expected_change', complete=True):
    """Synthetic native bytes exercise a real close/save/reopen transaction."""
    e,action,reviewed=city_evidence(parent)
    city_base=13432+14+13*2000+2*20*13+1024+26
    data=bytearray((e.directory/'city-test.sav').read_bytes())
    data[city_base+48:city_base+51]=bytes([128 if mode=='remove_worker' else 0,0,16])
    data[city_base+22]=0 if mode=='remove_worker' else 1
    data[city_base+51]=0 if mode=='remove_worker' else 4
    # Slot0 is the explored (8,6) square, independently encoded in save bytes.
    tile=6*40+4
    data[13446+7*2000+6*tile]=2
    data[13446+7*2000+6*tile+4]=2
    before=parse_save(bytes(data))
    def artifact(name,content):
        content=bytes(content);(e.directory/name).write_bytes(content)
        return dict(path=name,sha256=hashlib.sha256(content).hexdigest(),bytes=len(content))
    source=artifact('city-test.sav',data)
    actor=action['actor'];city={k:actor[k] for k in ('id','owner','name','x','y')}
    def values(state):
        c=state['cities'][0]
        return {k:deepcopy(c[k]) for k in ('worked_tiles_bits','specialist_count','specialists','size')}
    old=values(before);expected=deepcopy(old)
    expected['worked_tiles_bits'][0]^=128
    expected['specialist_count']=1 if mode=='remove_worker' else 0
    expected['specialists']={'entertainer':1} if mode=='remove_worker' else {}
    action.update(id=f'labor_{mode}_0',kind='city_labor',label='TEST original labor click')
    action['preconditions'].update(save_sha256=source['sha256'],labor_before=old,
        labor_review_used=0,labor_review_limit=2,labor_calibration='classic640-labor-grid-20-native-save-v1')
    action['parameters']=dict(control='resource_map',center=[104,168],slot=0,position={'x':8,'y':6},
        mode=mode,source_byte=48,source_bit=7,only_open_menu=False,purchase_authorized=False,
        expected_screen='city_screen',native_checkpoint_required=True,city_center_immutable=True)
    request=json.loads((e.directory/'decisions/request.json').read_text())
    criteria={action['id']:action['label'],'exit_city':'TEST exit'}
    request['questions']['city_action']['criteria']=criteria
    request['state']['city_control_review'].update(controls=criteria,labor_checkpoint_ready=True,
        labor_review=dict(used=0,limit=2,remaining=2,scope='Budget omission does not establish native illegality'))
    response=deepcopy(e.response)
    response['answers']={'city_action':dict(type='choice',choice=action['id'],confidence=.7,
                                          probabilities={action['id']:.7,'exit_city':.3})}
    e.change_artifact('decisions/request.json',request);e.change_artifact('decisions/response.json',response)
    after_data=bytearray(data)
    if outcome=='observed_expected_change':
        after_data[city_base+48]=expected['worked_tiles_bits'][0]
        after_data[city_base+22]=1 if mode=='remove_worker' else 0
        after_data[city_base+51]=4 if mode=='remove_worker' else 0
    elif outcome=='unexpected_change':
        after_data[city_base+48]=64
        after_data[city_base+22]=after_data[city_base+51]=0
    after=parse_save(bytes(after_data));followup=artifact('labor-after.sav',after_data)
    result=dict(status=outcome,before=old,expected=expected,after=values(after),
        before_save_sha256=source['sha256'],after_save_sha256=followup['sha256'],turn=1,
        city={k:after['cities'][0][k] for k in ('id','owner','name','x','y','size')},
        observation='TEST actual retained byte comparison; no yield attribution')
    seq=10
    def keys(*codes):
        nonlocal seq
        rows=[]
        for code,down in [(c,True) for c in codes]+[(c,False) for c in reversed(codes)]:
            rows.append(dict(type='key',sequence=seq,code=code,down=down,repeat=False));seq+=1
        return rows
    def click(label,point):
        nonlocal seq
        rows=[dict(type='mouse',sequence=seq+i,event=event,x=point[0],y=point[1],button=0)
              for i,event in enumerate(('mousedown','mouseup'))];seq+=2
        return dict(before=e.screen['sha256'],target=label,point=point,inputs=rows)
    def refresh(event,purpose,descriptor,action=None):
        identifier=1 if action else None
        base=dict(decision=identifier,purpose=purpose)
        return [event('city_labor_refresh_started',**base,action=action,city=city,before_save_sha256=source['sha256']),
            event('city_labor_refresh_input',**base,step='close_city',before=e.screen['sha256'],inputs=keys('Escape')),
            event('checkpoint',artifact=descriptor,turn=1,year=-4000),
            event('city_labor_checkpoint',**base,checkpoint=2 if action else 1,
                  save_sha256=descriptor['sha256'],result=result if action else None),
            event('city_labor_refresh_input',**base,step='open_locator',before=e.screen['sha256'],inputs=keys('ShiftLeft','KeyC')),
            event('navigate_selected_city',city=city,receipt=click('TEST Rome',[100,100]),
                  zoom_receipt=click('Zoom To City',[150,400])),
            event('city_labor_ready',**base,city=city,save_sha256=descriptor['sha256'],screen=e.screen['sha256'])]
    def rewrite(rows):
        cp=next(r for r in rows if r['kind']=='checkpoint');cp['payload']['artifact']=source
        elapsed=cp['elapsed_ms']
        def event(kind,**payload):return dict(kind=kind,elapsed_ms=elapsed,payload=payload)
        rows[rows.index(cp)+1:rows.index(cp)+1]=refresh(event,'prepare_labor_choices',source)
        for row in rows:
            if row['kind'] in ('model_decision','city_control_dispatched'):row['payload']['action']=deepcopy(action)
            if row['kind']=='city_control_dispatched':
                row['payload']['inputs']=click(action['label'],[104,168])['inputs']
        if complete:
            elapsed=rows[-1]['elapsed_ms']
            rows[-1:-1]=refresh(event,'verify_labor',followup,deepcopy(action))
    e.rewrite(rewrite)
    return e,action,result


class VerifyTests(unittest.TestCase):
    def test_presentation_notice_click_is_not_a_model_or_decoration_choice(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d)
            def add(rows):
                elapsed=rows[-1]['elapsed_ms']
                rows[-1:-1]=[dict(kind='screen_observed',elapsed_ms=elapsed,payload=dict(
                    screen=e.screen['sha256'],classification='presentation_notice',supported=True)),
                    dict(kind='native_presentation_acknowledged',elapsed_ms=elapsed,payload=dict(
                        source_hash=e.screen['sha256'],resource_tag='THRONE',receipt=dict(
                            before=e.screen['sha256'],target='(Click mouse to continue...)',point=[320,135],method='Original full-screen click-to-continue prompt; clicked observed narrative',inputs=[
                                dict(type='mouse',sequence=i,event=operation,x=320,y=135,button=0)
                                for i,operation in ((3,'mousedown'),(4,'mouseup'))])))]
            e.rewrite(add);result=verify_run(e.directory,ffprobe=None)
            self.assertEqual(result['decisions']['native_presentation_acknowledgments'],1)
            self.assertEqual(result['decisions']['model_dispatches'],1)
            def provenance(rows, point, digest):
                p=next(r for r in rows if r['kind']=='native_presentation_acknowledged')['payload']
                p.update(acknowledgement_point=point,template_sha256=digest)
            e.rewrite(lambda rows:provenance(rows,[320,135],'a'*64))
            self.assertEqual(verify_run(e.directory,ffprobe=None)['integrity'],'passed')
            for point,digest in (([317,141],'a'*64),([320,135],None)):
                e.rewrite(lambda rows:provenance(rows,point,digest))
                with self.assertRaisesRegex(VerificationError,'classified narrative'):
                    verify_run(e.directory,ffprobe=None)
            e.rewrite(lambda rows:provenance(rows,[320,135],'a'*64))
            for mode in ('resource','prompt','position','Enter','unsupported'):
                def bad(rows):
                    p=next(r for r in rows if r['kind']=='native_presentation_acknowledged')['payload']
                    p.update(resource_tag='THRONE');p['receipt'].update(target='(Click mouse to continue...)',point=[320,135])
                    p['receipt']['inputs']=p['receipt']['inputs'][:2]
                    observed=[r for r in rows if r['kind']=='screen_observed'][-1]['payload'];observed['supported']=True
                    if mode=='resource':p['resource_tag']='THRONE_UPGRADE'
                    elif mode=='prompt':p['receipt']['target']='Choose decoration'
                    elif mode=='position':p['receipt']['point']=[320,465]
                    elif mode=='unsupported':observed['supported']=False
                    else:p['receipt']['inputs']+=[dict(type='key',sequence=5+i,code='Enter',down=down,repeat=False) for i,down in enumerate((True,False))]
                e.rewrite(bad)
                with self.subTest(mode=mode),self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_checkpoint_reuse_requires_actual_advanced_save_and_observation_only_gap(self):
        def fixture(directory):
            e=Evidence(directory)
            a=dict(id='finish_turn',kind='empire_control',label='TEST finish turn',actor={'kind':'empire'},
                preconditions=dict(save_sha256=e.initial['sha256'],turn=1,screen_kind='end_turn',image_sha256=e.screen['sha256']),
                parameters=dict(key='Enter',modifiers=[]))
            req=dict(state={'turn':1},questions={'empire_action':dict(type='choice',instructions='TEST',criteria={'finish_turn':a['label'],'open_tax':'TEST tax'})})
            response=deepcopy(e.response);response['answers']={'empire_action':dict(type='choice',choice='finish_turn',confidence=.7,probabilities={'finish_turn':.7,'open_tax':.3})}
            e.change_artifact('decisions/request.json',req);e.change_artifact('decisions/response.json',response)
            data=bytearray(initial_save());struct.pack_into('<Hh',data,28,2,-3950)
            (e.directory/'advanced.sav').write_bytes(data)
            desc=dict(path='advanced.sav',sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
            def rewrite(rows):
                for r in rows:
                    if r['kind']=='model_decision':r['payload'].update(action=a,selected_question='empire_action')
                    if r['kind']=='command_dispatched':
                        r['kind']='empire_command_dispatched';r['payload']['action']=a
                        for x in r['payload']['inputs']:x['code']='Enter'
                elapsed=rows[-1]['elapsed_ms']
                rows[-1:-1]=[
                    dict(kind='checkpoint',elapsed_ms=elapsed,payload=dict(artifact=desc,turn=2,year=-3950)),
                    dict(kind='screen_observed',elapsed_ms=elapsed,payload=dict(screen=e.screen['sha256'],classification='end_turn',supported=True)),
                    dict(kind='checkpoint_reused',elapsed_ms=elapsed,payload=dict(checkpoint=1,save_sha256=desc['sha256'],turn=2,year=-3950,screen=e.screen['sha256'],ordinary_inputs_since_checkpoint=False,
                        reason='TEST use existing checkpoint without gameplay input'))]
            e.rewrite(rewrite);return e
        with tempfile.TemporaryDirectory() as d:
            e=fixture(d);r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['decisions']['reused_native_checkpoints'],1)
            self.assertEqual(r['decisions']['model_dispatches'],1)
        for mode in ('duplicate','input','old_hash','wrong_index','wrong_year','normal_map','claimed_no_input','no_finish'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                e=fixture(d)
                def bad(rows):
                    reused=next(r for r in rows if r['kind']=='checkpoint_reused');p=reused['payload']
                    if mode=='duplicate':rows.insert(rows.index(reused)+1,deepcopy(reused))
                    elif mode=='input':rows.insert(rows.index(reused),dict(kind='pointer_park_for_observation',elapsed_ms=reused['elapsed_ms'],payload={'receipt':{'issued':False}}))
                    elif mode=='old_hash':p['save_sha256']=e.initial['sha256']
                    elif mode=='wrong_index':p['checkpoint']=2
                    elif mode=='wrong_year':p['year']=-3900
                    elif mode=='normal_map':[r for r in rows if r['kind']=='screen_observed'][-1]['payload']['classification']='normal_map'
                    elif mode=='claimed_no_input':p['ordinary_inputs_since_checkpoint']=True
                    else:rows.remove(next(r for r in rows if r['kind']=='empire_command_dispatched'))
                e.rewrite(bad)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_labor_native_byte_comparison_distinguishes_effect_failure_and_unobserved(self):
        for mode in ('remove_worker','assign_entertainer'):
            for outcome in ('observed_expected_change','no_observed_change','unexpected_change'):
                with self.subTest(mode=mode,outcome=outcome),tempfile.TemporaryDirectory() as d:
                    e,_,result=labor_evidence(d,mode=mode,outcome=outcome)
                    r=verify_run(e.directory,ffprobe=None)
                    actual=r['decisions']['city_labor_results'][0]
                    self.assertEqual(actual['status'],outcome)
                    self.assertEqual(actual['after'],result['after'])
                    self.assertFalse(r['completeness']['pending_labor_refresh'])
                    self.assertFalse(r['completeness']['pending_city_control'])
                    self.assertNotIn('accepted',actual)
        with tempfile.TemporaryDirectory() as d:
            e,_,_=labor_evidence(d,complete=False);r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['decisions']['city_labor_results'][0]['status'],'unobserved')
            self.assertTrue(r['completeness']['pending_city_control'])

    def test_labor_tampered_bound_native_actor_bitmap_slot_geometry_or_allowance_refuses(self):
        for mode in ('actor','bitmap','bool_bitmap','center','source_bit','position','slot','budget','used','mixed_type'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                e,_,_=labor_evidence(d)
                def change(rows):
                    a=next(r['payload']['action'] for r in rows if r['kind']=='model_decision')
                    if mode=='actor':a['actor']['name']='Different city'
                    elif mode=='bitmap':a['preconditions']['labor_before']['worked_tiles_bits'][0]=64
                    elif mode=='bool_bitmap':a['preconditions']['labor_before']['size']=True
                    elif mode=='center':a['parameters']['center']=[105,168]
                    elif mode=='source_bit':a['parameters']['source_bit']=6
                    elif mode=='position':a['parameters']['position']={'x':8,'y':10}
                    elif mode=='slot':a['parameters']['slot']=16
                    elif mode=='budget':a['preconditions']['labor_review_limit']=200
                    elif mode=='used':a['preconditions']['labor_review_used']=2
                    else:a['preconditions']['labor_before']['specialists']={'scientist':1}
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_labor_outcome_cannot_be_claimed_without_exact_followup_native_transaction(self):
        for mode in ('claim','old_save','wrong_city','skip_close','skip_checkpoint','skip_locator','skip_ready','extra_key','wrong_click'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                e,_,_=labor_evidence(d,outcome='no_observed_change')
                def change(rows):
                    start=next(i for i,r in enumerate(rows) if r['kind']=='city_labor_refresh_started' and r['payload']['purpose']=='verify_labor')
                    tail=rows[start:]
                    if mode=='claim':next(r for r in tail if r['kind']=='city_labor_checkpoint')['payload']['result']['status']='observed_expected_change'
                    elif mode=='old_save':rows[:]=[r for r in rows if r not in tail or r['kind']!='checkpoint']
                    elif mode=='wrong_city':next(r for r in tail if r['kind']=='city_labor_ready')['payload']['city']['name']='Other'
                    elif mode.startswith('skip_'):
                        kind={'skip_close':'city_labor_refresh_input','skip_checkpoint':'city_labor_checkpoint','skip_locator':'navigate_selected_city','skip_ready':'city_labor_ready'}[mode]
                        target=next(r for r in tail if r['kind']==kind);rows.remove(target)
                    elif mode=='extra_key':next(r for r in tail if r['kind']=='city_labor_refresh_input')['payload']['inputs'][0]['code']='Enter'
                    else:next(r for r in rows if r['kind']=='city_control_dispatched')['payload']['inputs'][0]['x']=150
                e.rewrite(change)
                if mode=='skip_ready':
                    r=verify_run(e.directory,ffprobe=None)
                    self.assertTrue(r['completeness']['pending_labor_refresh'])
                    self.assertFalse(r['completeness']['release_review_ready'])
                else:
                    with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_labor_preparation_proof_and_current_policy_independence(self):
        with tempfile.TemporaryDirectory() as d:
            e,_,_=labor_evidence(d)
            with mock.patch('civ2.city_controls.city_control_candidates',side_effect=AssertionError('Do not regenerate old policy')):
                self.assertEqual(verify_run(e.directory,ffprobe=None)['integrity'],'passed')
            e.rewrite(lambda rows:rows.__setitem__(slice(None),[r for r in rows if not (r['kind']=='city_labor_ready' and r['payload']['purpose']=='prepare_labor_choices')]))
            with self.assertRaisesRegex(VerificationError,'completed native refresh'):
                verify_run(e.directory,ffprobe=None)

    def test_labor_refresh_failure_is_explicit_without_inventing_native_effect(self):
        for after_checkpoint in (False,True):
            with self.subTest(after_checkpoint=after_checkpoint),tempfile.TemporaryDirectory() as d:
                e,_,_=labor_evidence(d,outcome='unexpected_change')
                def failed(rows):
                    start=next(i for i,r in enumerate(rows) if r['kind']=='city_labor_refresh_started' and r['payload']['purpose']=='verify_labor')
                    end=next(i for i in range(start,len(rows)) if rows[i]['kind']=='city_labor_checkpoint') if after_checkpoint else start
                    stop=rows[-1];rows[:]=rows[:end+1]+[dict(kind='city_labor_refresh_failed',elapsed_ms=stop['elapsed_ms'],
                        payload=dict(decision=1,purpose='verify_labor',reason='TEST ambiguous original follow-up')),stop]
                e.rewrite(failed);r=verify_run(e.directory,ffprobe=None)
                status='unexpected_change' if after_checkpoint else 'unobserved'
                self.assertEqual(r['decisions']['city_labor_results'][0]['status'],status)
                self.assertTrue(r['decisions']['city_labor_results'][0]['refresh_failed'])
                self.assertEqual(r['decisions']['city_labor_refresh_failures'][0]['native_result_status'],status)
                self.assertTrue(r['completeness']['pending_labor_refresh'])
                self.assertEqual(r['completeness']['uninterpreted_event_counts'],{})

    def test_labor_review_usage_cannot_reset_after_an_unchanged_click(self):
        with tempfile.TemporaryDirectory() as d:
            e,_,_=labor_evidence(d,outcome='no_observed_change')
            def repeat(rows):
                extra=[deepcopy(next(r for r in rows if r['kind']==kind)) for kind in ('inference_started','model_decision')]
                for row in extra:row['payload']['decision']=2;row['elapsed_ms']=rows[-1]['elapsed_ms']
                rows[-1:-1]=extra
            e.rewrite(repeat)
            with self.assertRaisesRegex(VerificationError,'reuses its review allowance'):
                verify_run(e.directory,ffprobe=None)

    def test_labor_locator_keeps_observed_case_but_cannot_select_another_city(self):
        with tempfile.TemporaryDirectory() as d:
            e,_,_=labor_evidence(d)
            def observed_case(rows):
                for row in rows:
                    if row['kind']=='navigate_selected_city':
                        for key in ('receipt','zoom_receipt'):
                            row['payload'][key]['target']=row['payload'][key]['target'].upper()
            e.rewrite(observed_case)
            self.assertEqual(verify_run(e.directory,ffprobe=None)['integrity'],'passed')
            e.rewrite(lambda rows:next(r for r in rows if r['kind']=='navigate_selected_city')['payload']['receipt'].update(target='Different city'))
            with self.assertRaisesRegex(VerificationError,'locator'):
                verify_run(e.directory,ffprobe=None)

    def test_labor_locator_cannot_add_an_unobserved_confirmation_key(self):
        with tempfile.TemporaryDirectory() as d:
            e,_,_=labor_evidence(d)
            def extra_enter(rows):
                receipt=next(r for r in rows if r['kind']=='navigate_selected_city')['payload']['zoom_receipt']
                receipt['inputs'].extend(dict(type='key',sequence=90+i,code='Enter',down=down,repeat=False)
                                         for i,down in enumerate((True,False)))
            e.rewrite(extra_enter)
            with self.assertRaisesRegex(VerificationError,'without confirmation keys'):
                verify_run(e.directory,ffprobe=None)

    def test_city_recovered_title_keeps_raw_text_and_exact_native_identity_proof(self):
        with tempfile.TemporaryDirectory() as d:
            e,a,_=city_evidence(d)
            digest=a['preconditions']['save_sha256'];raw='City of TEST Rme, 4000 B.C.'
            proof=dict(source='Unique one-edit match to owned city in original save',ocr_text='TEST Rme',
                canonical_name='TEST Rome',city_id=0,save_sha256=digest,source_line=3)
            request=json.loads((e.directory/'decisions/request.json').read_text())
            request['state']['city_control_review']['observed_title']=raw
            e.change_artifact('decisions/request.json',request)
            def recover(rows):
                for row in rows:
                    if row['kind'] in ('model_decision','city_control_dispatched'):
                        row['payload']['action']['preconditions'].update(observed_city_title=raw,
                            observed_city_name='TEST Rome',city_name_recovery=deepcopy(proof))
            e.rewrite(recover)
            self.assertEqual(verify_run(e.directory,ffprobe=None)['integrity'],'passed')
            for key,value in (('save_sha256','0'*64),('ocr_text','TEST Wrong'),('city_id',True),('source_line',-1)):
                e.rewrite(recover)
                e.rewrite(lambda rows:next(r for r in rows if r['kind']=='model_decision')['payload']['action']['preconditions']['city_name_recovery'].update({key:value}))
                with self.subTest(key=key),self.assertRaisesRegex(VerificationError,'provenance'):
                    verify_run(e.directory,ffprobe=None)

    def test_city_fixture_keeps_time_monotonic_when_initial_artifact_takes_time(self):
        ticks=iter(range(100))
        with tempfile.TemporaryDirectory() as d, mock.patch('civ2.evidence.time.monotonic',side_effect=lambda:next(ticks)/1000):
            e,_,_=city_evidence(d)
            first=json.loads((e.directory/'events.jsonl').read_text().splitlines()[0])
            self.assertGreater(first['elapsed_ms'],0)
            result=verify_run(e.directory,ffprobe=None)
            self.assertEqual(result['decisions']['model_dispatches'],1)

    def test_graphics_preferences_change_only_verified_presentation_checkbox(self):
        for initially_checked in (False,True):
            with self.subTest(checked=initially_checked),tempfile.TemporaryDirectory() as d:
                e=Evidence(d)
                labels=('Throne Room','Diplomacy Screen','Animated Heralds','Civilopedia for Advances','High Council','Wonder Movies')
                before={name:True for name in labels};before['Civilopedia for Advances']=initially_checked
                after={**before,'Civilopedia for Advances':False}
                keys=[dict(type='key',sequence=i,code=code,down=down,repeat=False) for i,code,down in (
                    (1,'ControlLeft',True),(2,'KeyP',True),(3,'KeyP',False),(4,'ControlLeft',False),(9,'Enter',True),(10,'Enter',False))]
                click=None
                if initially_checked:
                    click=dict(target='Civilopedia for Advances',before=e.screen['sha256'],inputs=[
                        dict(type='mouse',sequence=i,event=event,x=120,y=150,button=0)
                        for i,event in ((5,'mousedown'),(6,'mouseup'))],pointer_park=dict(
                            issued=False,target=[620,410],observed_cursor=[619,410],tolerance=3,inputs=[
                                dict(type='relativeMouse',sequence=7,dx=12,dy=12,dispatched=True,emulate=True,via='DOSBox Mouse_CursorMoved')]))
                receipt=dict(before=e.screen['sha256'],opening=e.screen['sha256'],after=e.screen['sha256'],
                    checkbox_before=before,checkbox_after=after,other_checkboxes_unchanged=True,inputs=keys,
                    changes=[dict(label='Civilopedia for Advances',before=initially_checked,after=False,
                                  receipt=click,verified_image=e.screen['sha256'])])
                e.rewrite(lambda rows:rows.insert(-1,dict(kind='graphics_preferences_configured',
                    elapsed_ms=rows[-1]['elapsed_ms'],payload={'receipt':receipt})))
                r=verify_run(e.directory,ffprobe=None)
                self.assertEqual(r['decisions']['graphics_preference_reviews'],1)
                self.assertEqual(r['decisions']['model_dispatches'],1)
                if initially_checked:
                    e.rewrite(lambda rows:next(r for r in rows if r['kind']=='graphics_preferences_configured')['payload']['receipt']['changes'][0]['receipt'].update(target='M Civilopedia for Advances'))
                    self.assertEqual(verify_run(e.directory,ffprobe=None)['decisions']['graphics_preference_reviews'],1)
                def unrelated(rows):
                    p=next(r['payload']['receipt'] for r in rows if r['kind']=='graphics_preferences_configured')
                    p['checkbox_after']['Wonder Movies']=False
                e.rewrite(unrelated)
                with self.assertRaisesRegex(VerificationError,'single presentation option'):
                    verify_run(e.directory,ffprobe=None)

    def test_city_buy_opens_only_quote_and_pending_review_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            e,action,reviewed=city_evidence(d)
            r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['decisions']['model_dispatches'],1)
            self.assertEqual(r['decisions']['completed_city_reviews'],0)
            self.assertTrue(r['completeness']['pending_city_control'])
            e.rewrite(lambda rows:next(r for r in rows if r['kind']=='model_decision')['payload']['action']['parameters'].update(purchase_authorized=True))
            with self.assertRaisesRegex(VerificationError,'quote-only'):verify_run(e.directory,ffprobe=None)

    def test_city_action_wrong_native_actor_year_or_click_refuses(self):
        for mode in ('actor','year','click','enter'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                e,_,_=city_evidence(d)
                def change(rows):
                    selected=next(r['payload']['action'] for r in rows if r['kind']=='model_decision')
                    dispatched=next(r['payload'] for r in rows if r['kind']=='city_control_dispatched')
                    if mode=='actor':selected['actor']['name']='TEST Other'
                    elif mode=='year':selected['preconditions']['year_raw']=-3950
                    elif mode=='click':dispatched['inputs'][0]['x']=130
                    else:dispatched['inputs'] += [dict(type='key',sequence=i,code='Enter',down=down,repeat=False) for i,down in ((3,True),(4,False))]
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_forced_city_exit_has_no_fabricated_model_response(self):
        with tempfile.TemporaryDirectory() as d:
            e,action,_=city_evidence(d,'exit_city',forced=True)
            def close(rows):
                rows.insert(-1,dict(kind='city_control_closed',elapsed_ms=rows[-1]['elapsed_ms'],payload=dict(
                    decision=None,action_id='exit_city',city=dict(id=0,name='TEST Rome',year_raw=-4000),
                    completion_screen=e.screen['sha256'])))
            e.rewrite(close)
            r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['decisions']['validated_responses'],0)
            self.assertEqual(r['decisions']['forced_city_exit_dispatches'],1)
            self.assertEqual(r['decisions']['closed_city_controls'],1)
            self.assertFalse(r['completeness']['pending_city_control'])
            e.rewrite(lambda rows:next(r for r in rows if r['kind']=='city_control_closed')['payload']['city'].update(name='TEST Other'))
            with self.assertRaisesRegex(VerificationError,'another city'):verify_run(e.directory,ffprobe=None)

    def test_information_only_quote_needs_its_original_resource_and_acknowledgement(self):
        with tempfile.TemporaryDirectory() as d:
            e,action,reviewed=city_evidence(d)
            def complete(rows):
                elapsed=rows[-1]['elapsed_ms']
                ack=dict(kind='mechanical_input',elapsed_ms=elapsed,payload=dict(label='acknowledge_information',
                    before=e.screen['sha256'],after=e.screen['sha256'],inputs=[
                        dict(type='key',sequence=i,code='Enter',down=down,repeat=False) for i,down in ((3,True),(4,False))]))
                done=dict(kind='city_control_review_completed',elapsed_ms=elapsed,payload=dict(decision=1,
                    action_id='open_buy_quote',reviewed={**reviewed,'actions':['open_buy_quote']},
                    observed_dialog=dict(kind='buy_quote',sha256=e.screen['sha256'],resource_tag='COMPLETE0'),
                    response_decision=None,completion_screen=e.screen['sha256']))
                rows[-1:-1]=[ack,done]
            e.rewrite(complete)
            r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['decisions']['completed_city_reviews'],1)
            self.assertFalse(r['completeness']['pending_city_control'])
            e.rewrite(lambda rows:next(r for r in rows if r['kind']=='city_control_review_completed')['payload']['observed_dialog'].update(resource_tag='COMPLETE1'))
            with self.assertRaisesRegex(VerificationError,'information-only'):verify_run(e.directory,ffprobe=None)

    def test_production_and_purchase_reviews_need_a_separate_dispatched_model_choice(self):
        for control,kind,resource in (('change_production','production_choice',None),('open_buy_quote','buy_quote','COMPLETE1')):
            with self.subTest(control=control),tempfile.TemporaryDirectory() as d:
                e,_,reviewed=city_evidence(d,control)
                action=dict(id='option_0',kind='dialog_choice',label='TEST observed option',
                    actor=dict(kind='dialog',id='test_followup',title='TEST native followup'),
                    preconditions=dict(save_sha256=hashlib.sha256((e.directory/'city-test.sav').read_bytes()).hexdigest(),
                        turn=1,image_sha256=e.screen['sha256'],width=640,height=480),
                    parameters=dict(center=[180,200],observed_text='TEST observed option',option_index=0))
                request=dict(state=dict(turn=1,mandatory_dialog=dict(title='TEST native followup',options=['TEST observed option','TEST alternative'])),
                    questions=dict(dialog_action=dict(type='choice',instructions='TEST separate followup choice',
                        criteria=dict(option_0='TEST observed option',option_1='TEST alternative'))))
                if control=='open_buy_quote':
                    action['actor']['id']='buy_quote'
                    request['state']['mandatory_dialog']['quote']=dict(item='TEST unit',cost=20,treasury=50,
                        purchase_executed=False,source='Original GAME.TXT COMPLETE1 and complete visible quote')
                response=deepcopy(e.response)
                response['answers']=dict(dialog_action=dict(type='choice',choice='option_0',confidence=.7,
                    probabilities=dict(option_0=.7,option_1=.3)))
                descriptors=[]
                for name,value in [('decisions/followup-request.json',request),('decisions/followup-response.json',response)]:
                    data=canonical(value);(e.directory/name).write_bytes(data)
                    descriptors.append(dict(path=name,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
                def complete(rows):
                    elapsed=rows[-1]['elapsed_ms']
                    def event(kind,**payload):return dict(kind=kind,elapsed_ms=elapsed,payload=payload)
                    rows[-1:-1]=[
                        event('inference_started',decision=2,request=descriptors[0]),
                        event('model_decision',decision=2,selected_question='dialog_action',action=action,response=descriptors[1]),
                        event('dialog_dispatched',decision=2,action=action,after=e.screen['sha256'],receipt=dict(
                            before=e.screen['sha256'],point=[180,200],target='TEST observed option',inputs=[
                                dict(type='mouse',sequence=i,event=operation,x=180,y=200,button=0)
                                for i,operation in ((3,'mousedown'),(4,'mouseup'))])),
                        event('city_control_review_completed',decision=1,action_id=control,
                            reviewed={**reviewed,'actions':[control]},
                            observed_dialog=dict(kind=kind,sha256=e.screen['sha256'],resource_tag=resource),
                            response_decision=2,completion_screen=e.screen['sha256'])]
                e.rewrite(complete)
                r=verify_run(e.directory,ffprobe=None)
                self.assertEqual(r['decisions']['validated_responses'],2)
                self.assertEqual(r['decisions']['model_dispatches'],2)
                self.assertEqual(r['decisions']['completed_city_reviews'],1)
                self.assertFalse(r['completeness']['pending_city_control'])
                if control=='open_buy_quote':
                    for bad_quote in (None,{'cost':True},{'cost':60},{'purchase_executed':True}):
                        bad=deepcopy(request)
                        if bad_quote is None:bad['state']['mandatory_dialog'].pop('quote')
                        else:bad['state']['mandatory_dialog']['quote'].update(bad_quote)
                        e.change_artifact('decisions/followup-request.json',bad)
                        with self.subTest(bad_quote=bad_quote),self.assertRaisesRegex(VerificationError,'cost/treasury quote'):
                            verify_run(e.directory,ffprobe=None)
                    e.change_artifact('decisions/followup-request.json',request)
                e.rewrite(lambda rows:next(r for r in rows if r['kind']=='city_control_review_completed')['payload'].update(response_decision=1))
                with self.assertRaisesRegex(VerificationError,'separate dispatched choice'):
                    verify_run(e.directory,ffprobe=None)

    def test_planning_is_a_validated_separate_response_without_a_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d);e.add_plan();r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['decisions']['validated_responses'],2)
            self.assertEqual(r['decisions']['planning_decisions'],1)
            self.assertEqual(r['decisions']['command_decisions'],1)
            self.assertEqual(r['decisions']['planning_dispatches'],0)
            self.assertEqual(r['decisions']['model_dispatches'],1)
            self.assertEqual(r['decisions']['undispatched_decisions'],[])
            self.assertEqual(r['decisions']['inferences_without_response'],[])
            self.assertEqual(r['decisions']['accepted_response_input_tokens'],200)

    def test_plan_cannot_be_reclassified_as_command_or_native_effect(self):
        for mode in ('execute','stage','dispatch','effect'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                e=Evidence(d);e.add_plan()
                def change(rows):
                    if mode=='execute':next(r for r in rows if r['kind']=='model_plan')['payload']['executes_input']=True
                    elif mode=='stage':next(r for r in rows if r['kind']=='inference_started')['payload']['stage']='command'
                    elif mode=='dispatch':next(r for r in rows if r['kind']=='command_dispatched')['payload']['decision']=1
                    else:rows.append(dict(kind='batch_observed_effect',elapsed_ms=rows[-1]['elapsed_ms'],payload=dict(decisions=[1])))
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_plan_context_and_model_target_cannot_be_silently_rewritten(self):
        for mode in ('context','target','choice','actor'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                e=Evidence(d);e.add_plan()
                if mode=='context':
                    e.request['state']['persistent_plan']['target']={'turn':20}
                    e.change_artifact('decisions/request.json',e.request)
                else:
                    def change(rows):
                        plan=next(r for r in rows if r['kind']=='model_plan')['payload']['task']
                        if mode=='target':plan['target']={'turn':20}
                        elif mode=='choice':plan['id']='settle_8_8'
                        else:plan['actor']['id']=20
                    e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

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

    def test_unload_receipt_requires_selected_key_u_without_claiming_native_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d,unit_type=32)
            specification=dict(id=32,domain=2,role=4,transport_capacity=2)
            action={**e.action,'id':'unload','kind':'unload','label':'TEST request unload',
                    'parameters':{'key':'KeyU','transport_specification':specification}}
            request=deepcopy(e.request)
            request['state']['selected_unit']['specification']=specification
            request['questions']['unit_action']['criteria']={'unload':action['label'],'skip':'TEST skip'}
            response=deepcopy(e.response)
            response['answers']['unit_action'].update(choice='unload',probabilities={'unload':.7,'skip':.3})
            e.change_artifact('decisions/request.json',request)
            e.change_artifact('decisions/response.json',response)
            def change(rows):
                for row in rows:
                    if row['kind'] in ('model_decision','command_dispatched'):
                        row['payload']['action']=deepcopy(action)
                    if row['kind']=='command_dispatched':
                        for receipt in row['payload']['inputs']:receipt['code']='KeyU'
            e.rewrite(change)
            report=verify_run(e.directory,ffprobe=None)
            self.assertEqual(report['decisions']['model_dispatches'],1)
            self.assertIn('Native acceptance',report['decisions']['acceptance'])
            for change_spec in ({'domain':0},{'role':2},{'transport_capacity':0},
                                {'transport_capacity':3},{'id':33},{'role':True}):
                bad=deepcopy(request)
                bad['state']['selected_unit']['specification'].update(change_spec)
                e.change_artifact('decisions/request.json',bad)
                with self.subTest(change_spec=change_spec),self.assertRaisesRegex(VerificationError,'transport specification'):
                    verify_run(e.directory,ffprobe=None)
            e.change_artifact('decisions/request.json',request)
            def missing_spec(rows):
                next(r for r in rows if r['kind']=='model_decision')['payload']['action']['parameters'].pop('transport_specification')
            e.rewrite(missing_spec)
            with self.assertRaisesRegex(VerificationError,'transport specification'):
                verify_run(e.directory,ffprobe=None)
            e.rewrite(change)
            e.rewrite(lambda rows:next(r for r in rows if r['kind']=='command_dispatched')['payload']['inputs'][0].update(code='KeyB'))
            with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_historical_request_is_not_regenerated_with_todays_candidate_policy(self):
        with tempfile.TemporaryDirectory() as d:
            e=Evidence(d)
            # A controller update may later exclude a formerly offered order.
            # This test is receipt integrity, not a claim that TEST settling was legal.
            with mock.patch('civ2.policy.validate_action',side_effect=AssertionError('new policy rejects old action')):
                report=verify_run(e.directory,ffprobe=None)
            self.assertEqual(report['integrity'],'passed')
            self.assertTrue(any('not regenerated' in item for item in report['limitations']))

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
                inputs=[dict(type='relativeMouse',sequence=10,dx=10,dy=0,
                             dispatched=True,emulate=True,via='DOSBox Mouse_CursorMoved'),
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

    def test_relative_motion_accepts_only_verified_backend_receipts_and_bounds(self):
        legacy=dict(type='relativeMouse',sequence=1,dx=12,dy=-12,
                    queued=True,via='SDL_SendMouseMotion')
        current=dict(type='relativeMouse',sequence=1,dx=12,dy=-12,
                     dispatched=True,emulate=True,via='DOSBox Mouse_CursorMoved')
        self.assertEqual(_inputs([legacy]),[legacy])
        self.assertEqual(_inputs([current]),[current])
        for changes in ({'dispatched':False}, {'dispatched':1}, {'emulate':False},
                        {'emulate':1}, {'via':'guestWrite'}, {'via':'SDL_SendMouseMotion'},
                        {'dx':33}, {'dy':-33}, {'dx':True}, {'dx':0,'dy':0}):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(VerificationError,'Relative mouse receipt'):
                    _inputs([{**current,**changes}])
        for key in ('dispatched','emulate','via'):
            invalid={k:v for k,v in current.items() if k!=key}
            with self.subTest(missing=key),self.assertRaisesRegex(VerificationError,'Relative mouse receipt'):
                _inputs([invalid])
        with self.assertRaisesRegex(VerificationError,'Relative mouse receipt'):
            _inputs([{**legacy,'queued':False}])

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
