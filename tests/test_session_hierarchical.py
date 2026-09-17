"""Actual controller/journal integration using synthetic native-format TEST data."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from civ2.boot import verify_setup
from civ2.evidence import Journal
from civ2.save import parse_save
from civ2.session import Session
from civ2.typesafe import TransportError
from civ2.verify import verify_run,VerificationError
from test_session_planning import session,events
from test_verify import Evidence,initial_save,picture


class Client:
    model='jev-TEST'
    def __init__(self,category='settle',fail_target=False):
        self.category=category;self.fail_target=fail_target;self.requests=[]
        self.request_count=0;self.input_tokens_total=0;self.output_tokens_total=0
    def evaluate(self,state,questions):
        self.requests.append(deepcopy(dict(state=state,questions=questions)));self.request_count+=1
        if 'task_choice' in questions and self.fail_target:
            self.fail_target=False;raise TransportError('TEST transport failure',{'http_status':503})
        answers={}
        for name,q in questions.items():
            choice=self.category if name=='task_category' else 'move_e' if name=='unit_action' else next(iter(q['criteria']))
            answers[name]=dict(type='choice',choice=choice,confidence=1,
                               probabilities={k:float(k==choice) for k in q['criteria']})
        self.input_tokens_total+=100;self.output_tokens_total+=10
        return dict(model=self.model,answers=answers,usage=dict(input_tokens=100,output_tokens=10),
                    metadata=dict(latency_ms=1,attempts=1))


def native_session(directory,*,category='settle',multiple=True,fail_target=False):
    s=session();data=bytearray(initial_save())
    if multiple:
        for x in (6,10):
            tile=8*40+x//2;offset=13446+7*2000+6*tile
            data[offset]=2;data[offset+4]=2
    s.state=parse_save(bytes(data));s.initial_settings=deepcopy(s.state['settings'])
    spec=dict(id=0,name='TEST Settlers',domain=0,role=5,attack=0,defense=1,movement=1)
    s.rules=dict(units=[spec],terrain=[],advances=[])
    s.client=Client(category,fail_target);s.game.rpc.side_effect=lambda method,*args,**kw:(
        dict(paused=True,heldKeys=[],buttons=0) if method=='status' else None)
    s.journal=Journal(Path(directory)/'hierarchical-TEST')
    initial=s.journal.artifact('initial.sav',bytes(data))
    s.journal.append('begin',initial_save=initial,checks=verify_setup(s.state),settings=s.initial_settings,
                     model='jev-TEST',planning_enabled=True)
    screen=s.journal.artifact('screens/TEST.png',picture())
    s.ui.observe.return_value=dict(sha256=screen['sha256'])
    s.ui.key.side_effect=lambda key,**kw:[dict(type='key',code=key,down=down,repeat=False,sequence=i+1)
                                        for i,down in enumerate((True,False))]
    s.journal.append('screen_observed',path=screen['path'],screen=screen['sha256'],classification='normal_map',supported=True)
    s.enable_hierarchical_planning()
    e=object.__new__(Evidence);e.directory=s.journal.directory;e.initial=initial;e.screen=screen
    return s,e


class HierarchicalSessionTests(unittest.TestCase):
    def test_two_actual_planning_calls_then_independent_command_only(self):
        with tempfile.TemporaryDirectory() as directory:
            s,e=native_session(directory);s.choose_unit();s.journal.close()
            r=verify_run(e.directory,ffprobe=None)
            self.assertEqual([list(q['questions'])[0] for q in s.client.requests],['task_category','task_choice','unit_action'])
            self.assertEqual(s.pending_decisions,[3]);self.assertEqual(s.plans[0]['decision_id'],2)
            self.assertEqual(r['decisions']['validated_responses'],3)
            self.assertEqual(r['decisions']['planning_decisions'],2)
            self.assertEqual(r['decisions']['planning_category_decisions'],1)
            self.assertEqual(r['decisions']['model_dispatches'],1)
            self.assertEqual(r['decisions']['ordinary_input_events'],2)
            self.assertFalse(r['completeness']['pending_planning_category'])

    def test_hold_and_other_singleton_use_the_actual_category_answer_once(self):
        for category in ('hold','settle'):
            with self.subTest(category=category),tempfile.TemporaryDirectory() as directory:
                s,e=native_session(directory,category=category,multiple=False)
                s._unit_plan();s.journal.close();r=verify_run(e.directory,ffprobe=None)
                self.assertEqual(len(s.client.requests),1)
                self.assertEqual(s.plans[0]['candidate']['task'],category)
                self.assertEqual(s.plans[0]['decision_id'],1)
                self.assertEqual(s.decision['stage'],'planning_category')
                self.assertFalse(s.decision['authorizes_input']);self.assertEqual(s.pending_decisions,[])
                s.ui.key.assert_not_called();s.game.click.assert_not_called()
                self.assertEqual(r['decisions']['validated_responses'],1)
                self.assertEqual(r['decisions']['planning_decisions'],1)
                self.assertEqual(r['decisions']['concrete_plans'],1)
                self.assertEqual(r['decisions']['accepted_response_input_tokens'],100)

    def test_failed_target_preserves_category_and_retry_does_not_resample_it(self):
        with tempfile.TemporaryDirectory() as directory:
            s,e=native_session(directory,fail_target=True)
            with self.assertRaises(TransportError):s._unit_plan()
            self.assertEqual(s.pending_plan_category['decision'],1)
            before=verify_run(e.directory,ffprobe=None)
            self.assertTrue(before['completeness']['pending_planning_category'])
            self.assertEqual(before['decisions']['failed_calls'],1)
            self.assertEqual(before['decisions']['inferences_without_response'],[])
            s._unit_plan();s.journal.close();r=verify_run(e.directory,ffprobe=None)
            self.assertEqual([list(q['questions'])[0] for q in s.client.requests],['task_category','task_choice','task_choice'])
            self.assertIsNone(s.pending_plan_category)
            self.assertEqual(s.plans[0]['decision_id'],3)
            self.assertEqual(r['decisions']['failed_calls'],1)
            self.assertEqual(r['decisions']['validated_responses'],2)
            self.assertEqual(r['decisions']['ordinary_input_events'],0)

    def test_changed_observation_invalidates_pending_category_before_new_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            s,e=native_session(directory,fail_target=True)
            with self.assertRaises(TransportError):s._unit_plan()
            data=bytearray((e.directory/'initial.sav').read_bytes());data[2264+1396+2]+=1
            state=parse_save(bytes(data));artifact=s.journal.artifact('saves/new.sav',bytes(data))
            s.journal.append('checkpoint',artifact=artifact,turn=state['turn'],year=state['year_raw'])
            s.state=state;s._unit_plan();s.journal.close();r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['decisions']['invalidated_planning_categories'],[1])
            self.assertEqual(r['decisions']['planning_category_decisions'],2)
            self.assertEqual([list(q['questions'])[0] for q in s.client.requests],
                             ['task_category','task_choice','task_category','task_choice'])

    def test_pending_category_permits_verified_pointer_motion_but_no_click(self):
        for click in (False,True):
            with self.subTest(click=click),tempfile.TemporaryDirectory() as directory:
                s,e=native_session(directory,fail_target=True)
                with self.assertRaises(TransportError):s._unit_plan()
                ordinary=(dict(type='mouse',event='mousedown',x=2,y=1,button=0,sequence=1) if click else
                          dict(type='relativeMouse',dx=1,dy=1,emulate=True,dispatched=True,
                               via='DOSBox Mouse_CursorMoved',sequence=1))
                s.journal.append('pointer_park_for_observation',before=e.screen['sha256'],
                    receipt=dict(issued=False,target=[2,1],inputs=[ordinary]))
                s.journal.close()
                if click:
                    with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)
                else:
                    r=verify_run(e.directory,ffprobe=None)
                    self.assertTrue(r['completeness']['pending_planning_category'])
                    self.assertEqual(r['decisions']['ordinary_input_events'],1)
                    self.assertEqual(r['decisions']['model_dispatches'],0)

    def test_default_stays_flat_and_enablement_requires_clear_paused_inputs(self):
        s=session();s._unit_plan()
        self.assertEqual([list(q['questions'])[0] for q in s.client.requests],['task_choice'])
        for mode in ('pending','running','held','disabled'):
            s=session();s.game.rpc.return_value=dict(paused=True,heldKeys=[],buttons=0)
            if mode=='pending':s.pending_decisions=[1]
            elif mode=='running':s.game.rpc.return_value['paused']=False
            elif mode=='held':s.game.rpc.return_value['heldKeys']=['Enter']
            else:s.planning=False
            with self.subTest(mode=mode),self.assertRaises(RuntimeError):s.enable_hierarchical_planning()
            self.assertEqual(events(s,'hierarchical_planning_enabled'),[])
        s=session();s.game.rpc.return_value=dict(paused=True,heldKeys=[],buttons=0)
        s.enable_hierarchical_planning();s.enable_hierarchical_planning()
        self.assertEqual(len(events(s,'hierarchical_planning_enabled')),1)

    def test_category_hud_compatibility_never_changes_canonical_stage_or_vector(self):
        with tempfile.TemporaryDirectory() as directory:
            s,e=native_session(directory,category='hold');s.publish=Session.publish.__get__(s)
            s._unit_plan();s.journal.close()
            hud=s.game.state.call_args.args[0]['decision']
            self.assertEqual(hud['stage'],'planning');self.assertEqual(hud['planning_phase'],'category')
            self.assertFalse(hud['authorizes_input']);self.assertFalse(hud['executes_input'])
            self.assertEqual(s.decision['stage'],'planning_category')
            self.assertEqual(hud['answers'],s.decision['answers'])


class HierarchicalAuditTests(unittest.TestCase):
    def test_begin_optin_and_category_response_hash_are_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            s,e=native_session(directory,category='hold');s._unit_plan();s.journal.close()
            def change(rows):
                rows[0]['payload']['hierarchical_planning']='task-category-target-v1'
                rows[:]=[r for r in rows if r['kind']!='hierarchical_planning_enabled']
            e.rewrite(change)
            self.assertEqual(verify_run(e.directory,ffprobe=None)['decisions']['validated_responses'],1)
            path=e.directory/'decisions/000001-response.json'
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_target_cannot_use_category_from_an_older_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            s,e=native_session(directory);s._unit_plan();s.journal.close()
            data=bytearray((e.directory/'initial.sav').read_bytes());data[2264+1396+2]+=1
            path=e.directory/'new.sav';path.write_bytes(data)
            import hashlib
            artifact=dict(path='new.sav',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            def change(rows):
                i=next(i for i,r in enumerate(rows) if r['kind']=='inference_started' and r['payload']['decision']==2)
                rows.insert(i,dict(kind='checkpoint',elapsed_ms=rows[i]['elapsed_ms'],
                                  payload=dict(artifact=artifact,turn=1,year=-4000)))
            e.rewrite(change)
            with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_category_and_target_tampering_rejected(self):
        for mode in ('category_choice','actor','revision','count','partition','sole','input',
                     'prior','target_set','criteria','criteria_label','cross_category','disable','reuse_category'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                s,e=native_session(directory);s._unit_plan();s.journal.close()
                self.assertEqual(verify_run(e.directory,ffprobe=None)['integrity'],'passed')
                if mode in ('prior','target_set','criteria','criteria_label','cross_category'):
                    path='decisions/000002-request.json';value=json.loads((e.directory/path).read_text())
                    p=value['state']['planning']
                    if mode=='prior':p['category_selection']['decision']=99
                    elif mode=='target_set':p['targets'].pop(next(iter(p['targets'])))
                    elif mode=='criteria':value['questions']['task_choice']['criteria'].pop(next(iter(p['targets'])))
                    elif mode=='criteria_label':
                        criteria=value['questions']['task_choice']['criteria'];criteria[next(reversed(criteria))]='TEST changed unchosen target label'
                    else:p['category_selection']['category']['task']='survey'
                    e.change_artifact(path,value)
                else:
                    def change(rows):
                        i=next(i for i,r in enumerate(rows) if r['kind']=='model_plan_category');p=rows[i]['payload'];c=p['category']
                        if mode=='category_choice':c['id']='survey'
                        elif mode=='actor':c['actor']['x']+=2
                        elif mode=='revision':c['preconditions']['save_sha256']='f'*64
                        elif mode=='count':c['target_count']-=1
                        elif mode=='partition':c['target_ids'].pop()
                        elif mode=='sole':p['task']={'id':'TEST invented target'}
                        elif mode=='input':rows.insert(i+1,dict(kind='mechanical_input',elapsed_ms=rows[i]['elapsed_ms'],payload={}))
                        elif mode=='disable':rows[:]=[r for r in rows if r['kind']!='hierarchical_planning_enabled']
                        else:rows.insert(i+1,deepcopy(rows[i]))
                    e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_unchanged_category_cannot_be_invalidated_or_use_failed_id_as_category(self):
        for mode in ('invalidate','failed'):
            with tempfile.TemporaryDirectory() as directory:
                s,e=native_session(directory,fail_target=True)
                with self.assertRaises(TransportError):s._unit_plan()
                s.journal.close()
                def change(rows):
                    if mode=='invalidate':rows.append(dict(kind='planning_category_invalidated',elapsed_ms=rows[-1]['elapsed_ms'],
                        payload=dict(decision=1,current_revision={'save_sha256':e.initial['sha256'],'turn':1},
                                     reason='actor_or_observation_changed',executes_input=False)))
                    else:
                        p=next(r for r in rows if r['kind']=='inference_failed')['payload'];p['decision']=1
                        p['request_sha256']=next(r for r in rows if r['kind']=='inference_started')['payload']['request']['sha256']
                        p['recorded_late']=True
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)


if __name__=='__main__':unittest.main()
