"""Offline trade continuations must inherit one actual accepted model choice."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from civ2.evidence import canonical
from civ2.exchange_picker import ACCEPT,accepted_trade_context,classify_exchange_picker
from civ2.dialogs import _rows
from civ2.verify import verify_run,TRADE_SCOPE,VerificationError
from test_verify import Evidence
from test_exchange_picker import fixture


class TradeEvidenceTests(unittest.TestCase):
    def make(self,parent):
        e=Evidence(parent)
        action={'id':'option_1','kind':'dialog_choice','label':ACCEPT,
            'actor':{'kind':'dialog','id':'diplomacy','title':'Neutral TEST Emissary'},
            'parameters':{'option_index':1,'observed_text':ACCEPT,'center':[464,403]},
            'preconditions':{'save_sha256':e.initial['sha256'],'turn':1,'width':640,'height':480,
                             'image_sha256':e.screen['sha256']}}
        labels=['"No. We do not need TEST Advance."',ACCEPT]
        body='"We note that your primitive civilization has not even discovered TEST Advance. We desire the secret of Alphabet. Do you care to exchange knowledge with us?"'
        mandatory={'title':action['actor']['title'],'options':labels,
                   'observed_text':'\n'.join([action['actor']['title'],body,*labels,'OK'])}
        request={'state':{'turn':1,'mandatory_dialog':mandatory},'questions':{'dialog_action':{
            'type':'choice','instructions':'TEST source choice','criteria':{'option_0':labels[0],'option_1':ACCEPT}}}}
        response=deepcopy(e.response);response['answers']={'dialog_action':{'type':'choice','choice':'option_1',
            'probabilities':{'option_0':.1,'option_1':.9},'confidence':.9}}
        e.change_artifact('decisions/request.json',request);e.change_artifact('decisions/response.json',response)
        dialog={'id':'diplomacy','kind':'diplomacy','title':action['actor']['title'],'supported':True,
            'requires_model':True,'resource_tag':'EXCHANGE0','sha256':e.screen['sha256'],
            'options':[{'text':label,'center':action['parameters']['center'] if i else [440,379]}
                       for i,label in enumerate(labels)]}
        o,rules,resources=fixture(e.directory/'screens')
        pending=accepted_trade_context(dialog,action,1,rules)
        picker=classify_exchange_picker(o,_rows(o),resources,rules,{'pending_trade':pending})
        proof=picker['evidence']
        inputs=[dict(type='key',code='Enter',down=down,repeat=False,sequence=i+3) for i,down in enumerate((True,False))]
        advance={'prior_trade':pending,'advance':picker['advance'],'before':o['sha256'],'after':e.screen['sha256'],
            'resource_tag':'TAKECIV','evidence':{'exchange_picker':proof},'inputs':inputs,'scope':TRADE_SCOPE}
        def change(events):
            for row in events:
                payload=row['payload']
                if row['kind']=='screen_observed':payload['classification']='diplomacy'
                if row['kind']=='model_decision':payload.update(action=action,selected_question='dialog_action')
                if row['kind']=='command_dispatched':
                    row['kind']='dialog_dispatched'
                    payload.clear();payload.update(decision=1,action=action,after=e.screen['sha256'],receipt={
                        'before':e.screen['sha256'],'point':[464,403],'target':ACCEPT,'inputs':[
                            dict(type='mouse',event=event,x=464,y=403,button=0,sequence=i+1)
                            for i,event in enumerate(('mousedown','mouseup'))]})
            stop=events.pop()
            events.extend(dict(sequence=0,elapsed_ms=stop['elapsed_ms'],kind=k,previous_sha256='',payload=p)
                for k,p in [('trade_followup_pending',{'prior_trade':pending}),
                            ('screen_observed',{'path':'screens/frame.png','screen':o['sha256'],
                                                'classification':'exchange_picker','supported':True}),
                            ('trade_advance_dispatched',advance)])
            events.append(stop)
        e.rewrite(change);return e

    def test_valid_single_continuation_not_counted_as_new_model_or_effect(self):
        with tempfile.TemporaryDirectory() as parent:
            e=self.make(parent);r=verify_run(e.directory,ffprobe='skip')
            self.assertEqual(r['integrity'],'passed',r)
            self.assertEqual(r['decisions']['accepted_trade_continuations'],1)
            self.assertEqual(r['decisions']['model_dispatches'],1)
            self.assertFalse(r['completeness']['pending_trade_continuation'])
            self.assertIn('not independently inferred',r['decisions']['trade_continuation_note'])

    def test_missing_repeated_or_interrupted_authorization_fails(self):
        for case in ('absent','repeat_context','repeat_enter','input','inference'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as parent:
                e=self.make(parent)
                def change(events):
                    pending=next(x for x in events if x['kind']=='trade_followup_pending')
                    confirm=next(x for x in events if x['kind']=='trade_advance_dispatched')
                    if case=='absent':events.remove(pending)
                    elif case=='repeat_context':events.insert(events.index(confirm),deepcopy(pending))
                    elif case=='repeat_enter':events.insert(events.index(confirm)+1,deepcopy(confirm))
                    elif case=='input':events.insert(events.index(confirm),{**deepcopy(pending),'kind':'mechanical_input','payload':{}})
                    else:
                        inference=deepcopy(next(x for x in events if x['kind']=='inference_started'))
                        inference['payload']['decision']=2;inference['elapsed_ms']=confirm['elapsed_ms']
                        events.insert(events.index(confirm),inference)
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe='skip')

    def test_wrong_advance_source_text_and_keyboard_fail(self):
        for case in ('advance','context','source','extra_key','wrong_tag'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as parent:
                e=self.make(parent)
                if case=='source':
                    q=json.loads((e.directory/'decisions/request.json').read_text())
                    q['state']['mandatory_dialog']['observed_text']=q['state']['mandatory_dialog']['observed_text'].replace('secret of Alphabet','price of Alphabet')
                    e.change_artifact('decisions/request.json',q)
                else:
                    def change(events):
                        p=next(x['payload'] for x in events if x['kind']=='trade_advance_dispatched')
                        if case=='advance':p['advance']={'id':12,'name':'Different'}
                        elif case=='context':p['prior_trade']['action_sha256']='0'*64
                        elif case=='wrong_tag':p['resource_tag']='SELLTECH'
                        else:p['inputs'] += [dict(type='key',code='Space',down=down,repeat=False,sequence=i+5) for i,down in enumerate((True,False))]
                    e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe='skip')

    def test_more_list_content_or_absent_highlight_rejected_even_with_new_hash(self):
        for pixel in ((390,205),(600,175),(628,230)):
            with self.subTest(pixel=pixel),tempfile.TemporaryDirectory() as parent:
                e=self.make(parent);path=e.directory/'screens/frame.png';image=Image.open(path).convert('RGB')
                image.putpixel(pixel,(0,0,0));image.save(path);sha=hashlib.sha256(path.read_bytes()).hexdigest()
                def change(events):
                    for row in events:
                        p=row['payload']
                        if row['kind']=='screen_observed' and p['classification']=='exchange_picker':p['screen']=sha
                        if row['kind']=='trade_advance_dispatched':p['before']=sha;p['evidence']['exchange_picker']['image_sha256']=sha
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe='skip')

    def test_pending_context_is_reported_when_continuation_not_dispatched(self):
        with tempfile.TemporaryDirectory() as parent:
            e=self.make(parent)
            e.rewrite(lambda rows:rows.__setitem__(slice(None),[r for r in rows if r['kind'] not in ('trade_advance_dispatched','session_stopped')]))
            result=verify_run(e.directory,ffprobe='skip')
            self.assertEqual(result['integrity'],'passed',result)
            self.assertTrue(result['completeness']['pending_trade_continuation'])

    def test_exterior_herald_art_requires_complete_frame_and_no_overlap(self):
        from PIL import ImageDraw
        for mode in ('valid','broken_frame','overlap','inside','missing_pair','extra_key','duplicate'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as parent:
                e=self.make(parent);path=e.directory/'screens/frame.png';im=Image.open(path).convert('RGB')
                ImageDraw.Draw(im).rectangle((298,137,639,478),outline=(0,0,0))
                if mode=='broken_frame':im.putpixel((298,220),(1,1,1))
                im.save(path);sha=hashlib.sha256(path.read_bytes()).hexdigest()
                def change(rows):
                    for event in rows:
                        p=event['payload']
                        if event['kind']=='screen_observed' and p['classification']=='exchange_picker':p['screen']=sha
                        if event['kind']!='trade_advance_dispatched':continue
                        p['before']=sha;proof=p['evidence']['exchange_picker'];proof['image_sha256']=sha
                        outside=dict(text='TEST ART',source_line=0,bounds=[518,56,44,40])
                        if mode=='overlap':outside['bounds']=[518,125,44,40]
                        elif mode=='inside':outside['bounds']=[518,220,44,40]
                        proof.update(picker_frame_bounds=[298,137,640,479],outside_picker_rows=[outside])
                        if mode=='missing_pair':proof.pop('picker_frame_bounds')
                        elif mode=='extra_key':proof['inferred_empty']=True
                        elif mode=='duplicate':proof['outside_picker_rows']*=2
                e.rewrite(change)
                if mode=='valid':
                    result=verify_run(e.directory,ffprobe=None)
                    self.assertEqual(result['decisions']['accepted_trade_continuations'],1)
                else:
                    with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)


if __name__=='__main__':unittest.main()
