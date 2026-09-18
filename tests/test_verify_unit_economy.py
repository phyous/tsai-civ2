"""Synthetic TEST ledgers prove request/confirmation separation, not gameplay."""
from copy import deepcopy
import hashlib
import tempfile
import unittest
from civ2.evidence import canonical
from civ2.save import parse_save
from civ2.policy import unit_candidates,dialog_request_for
from civ2.dialogs import classify_dialog
from civ2.unit_economy import request_context
from civ2.verify import verify_run,VerificationError
from test_verify import Evidence,initial_save
from test_unit_economy import warning,GAME


class EconomyLedgerTests(unittest.TestCase):
    def make(self,parent,choice='option_0'):
        e=Evidence(parent,unit_type=2);state=parse_save(initial_save(2));u=state['units'][0]
        spec=dict(id=2,name='Warriors',max_hp=10,domain=0,role=1,attack=1)
        u.update(type='Warriors',hp=10,specification=spec)
        action=unit_candidates(state,rules={'units':[spec]})['request_disband']
        first=dict(state=dict(turn=1,selected_unit=deepcopy(u)),questions={'unit_action':{
            'type':'choice','instructions':'TEST choose a command',
            'criteria':{'request_disband':action['label'],'skip':'TEST skip'}}})
        response=deepcopy(e.response);response['answers']['unit_action'].update(choice='request_disband',
            probabilities={'request_disband':.7,'skip':.3})
        e.change_artifact('decisions/request.json',first);e.change_artifact('decisions/response.json',response)
        _,o=warning(__import__('test_unit_economy').state());o['sha256']=e.screen['sha256']
        state['pending_disband']=request_context(action,state,1)
        d=classify_dialog(o,game_text=GAME,state=state)
        full,actions=dialog_request_for(state,d,{'units':[spec]})
        request=dict(state={k:full['state'][k]for k in ('turn','selected_unit','mandatory_dialog')},
            questions={'dialog_action':full['questions']['dialog_action']})
        confirm=actions[choice];second=deepcopy(e.response);second['answers']={'dialog_action':{
            'type':'choice','choice':choice,'probabilities':{k:.8 if k==choice else .2 for k in actions},'confidence':.8}}
        def artifact(name,value):
            data=canonical(value);(e.directory/name).write_bytes(data)
            return dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        rd=artifact('decisions/confirm-request.json',request);sd=artifact('decisions/confirm-response.json',second)
        def change(events):
            for row in events:
                p=row['payload']
                if row['kind']=='model_decision':p['action']=action
                if row['kind']=='command_dispatched':
                    p['action']=action;p['inputs']=[dict(type='key',code=key,down=down,repeat=False,sequence=i+1)
                        for i,(key,down)in enumerate([('ShiftLeft',True),('KeyD',True),('KeyD',False),('ShiftLeft',False)])]
            stop=events.pop();stop['payload'].update(decisions=2,api_requests=2,input_tokens=200,output_tokens=20)
            x,y=confirm['parameters']['center']
            rows=[('screen_observed',dict(path=e.screen['path'],screen=e.screen['sha256'],classification='disband_confirmation',supported=True)),
                ('inference_started',dict(decision=2,request=rd)),
                ('model_decision',dict(decision=2,selected_question='dialog_action',action=confirm,response=sd)),
                ('dialog_dispatched',dict(decision=2,action=confirm,after=e.screen['sha256'],receipt=dict(
                    target=confirm['label'],point=[x,y],before=e.screen['sha256'],inputs=[
                        dict(type='mouse',event=event,x=x,y=y,button=0,sequence=i+5)for i,event in enumerate(('mousedown','mouseup'))]+[
                        dict(type='key',code='Enter',down=down,repeat=False,sequence=i+7)for i,down in enumerate((True,False))])))]
            events.extend(dict(kind=k,elapsed_ms=stop['elapsed_ms'],payload=p)for k,p in rows);events.append(stop)
        e.rewrite(change);return e

    def test_no_and_yes_each_have_two_real_responses_and_exact_distinct_inputs(self):
        for choice in ('option_0','option_1'):
            with self.subTest(choice=choice),tempfile.TemporaryDirectory() as directory:
                e=self.make(directory,choice);result=verify_run(e.directory,ffprobe='skip')
                self.assertEqual(result['integrity'],'passed',result)
                self.assertEqual(result['decisions']['model_dispatches'],2)
                self.assertEqual(result['decisions']['disband_warning_requests'],[1])
                self.assertEqual(result['decisions']['disband_confirmation_choices'],[
                    dict(decision=2,request_decision=1,choice='No' if choice=='option_0' else 'Yes')])
                self.assertFalse(result['completeness']['pending_disband_confirmation'])

    def test_unissued_wrong_or_reused_authorization_fails(self):
        for mode in ('missing_dispatch','modified_chord','intervening_screen','reused_confirmation',
                     'wrong_actor','wrong_revision','missing_proof','only_yes','different_body','downgrade'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=self.make(directory)
                if mode in ('wrong_actor','wrong_revision','missing_proof','only_yes','different_body','downgrade'):
                    import json
                    req=json.loads((e.directory/'decisions/confirm-request.json').read_text());dialog=req['state']['mandatory_dialog']
                    if mode=='wrong_actor':dialog['disband_confirmation']['request']['actor']['id']=9
                    elif mode=='wrong_revision':dialog['disband_confirmation']['request']['revision']['turn']=2
                    elif mode in ('missing_proof','downgrade'):dialog.pop('disband_confirmation')
                    elif mode=='only_yes':dialog['options']=['Yes']
                    else:dialog['disband_confirmation']['observed_body']='Really disband Settlers?'
                    e.change_artifact('decisions/confirm-request.json',req)
                    if mode=='downgrade':
                        def downgrade(events):
                            for row in events:
                                p=row['payload']
                                if p.get('decision')==2 and 'action' in p:p['action']['actor']['id']='generic_warning'
                        e.rewrite(downgrade)
                else:
                    def change(events):
                        dispatched=next(r for r in events if r['kind']=='command_dispatched')
                        if mode=='missing_dispatch':events.remove(dispatched)
                        elif mode=='modified_chord':
                            dispatched['payload']['inputs'][0]['code']='ControlLeft';dispatched['payload']['inputs'][-1]['code']='ControlLeft'
                        elif mode=='intervening_screen':
                            screen=deepcopy(next(r for r in events if r['kind']=='screen_observed'))
                            screen['payload']['classification']='information';events.insert(events.index(dispatched)+1,screen)
                        else:events.insert(-1,deepcopy(next(r for r in events if r['kind']=='dialog_dispatched')))
                    e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe='skip')


if __name__=='__main__':unittest.main()
