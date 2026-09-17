"""Transport failure records contain no remote text, response or input claim."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from civ2.evidence import Journal,canonical
from civ2.typesafe import TransportError,RequestLimitError,ResponseValidationError
from civ2.verify import verify_run,VerificationError
from test_session import session
from test_verify import Evidence,city_evidence


def failure_payload(digest,identifier=2,*,late=False):
    return dict(decision=identifier,request_sha256=digest,http_status=400,
                category='context_or_token_limit',error_type='TransportError',
                usage='unavailable',recorded_late=late)


def insert_failure(e,*,late=False,unresolved=False):
    def change(rows):
        original=next(r for r in rows if r['kind']=='inference_started')
        start=deepcopy(original);start['payload']['decision']=2
        p=failure_payload(start['payload']['request']['sha256'],late=late)
        stop=next((i for i,r in enumerate(rows) if r['kind']=='session_stopped'),len(rows))
        start['elapsed_ms']=rows[stop-1]['elapsed_ms']
        additions=[start]
        if late:
            marker=deepcopy(next(r for r in rows if r['kind']=='screen_observed'))
            marker['elapsed_ms']=start['elapsed_ms'];additions.append(marker)
        if not unresolved:additions.append(dict(kind='inference_failed',elapsed_ms=start['elapsed_ms'],payload=p))
        rows[stop:stop]=additions
    e.rewrite(change)


class SessionInferenceFailureTests(unittest.TestCase):
    def evaluate(self,error):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        s=session();s.journal=Journal(Path(temporary.name)/'evidence');self.addCleanup(s.journal.close)
        s.client=Mock();s.client.evaluate.side_effect=error
        s.pending_decisions=[17];s.controller={'pending_city_control':{'decision':17},'pending_labor_refresh':{'phase':'await_map'}}
        request={'state':{'turn':1},'questions':{'action':{'type':'choice','instructions':'TEST',
                   'criteria':{'one':'TEST one','two':'TEST two'}}}}
        with self.assertRaises(type(error)) as caught:s._evaluate(request,{},'action')
        self.assertIs(caught.exception,error)
        s.game.click.assert_not_called();s.ui.key.assert_not_called()
        s.game.rpc.assert_called_once_with('pause')
        self.assertEqual(s.pending_decisions,[17])
        self.assertEqual(s.controller['pending_city_control'],{'decision':17})
        self.assertEqual(s.controller['pending_labor_refresh'],{'phase':'await_map'})
        text=(s.journal.directory/'events.jsonl').read_text()
        return s,text,[json.loads(x) for x in text.splitlines()]

    def test_only_safe_diagnostics_and_actual_request_hash_are_journaled(self):
        secret='SECRET REMOTE BODY AND CREDENTIAL'
        error=TransportError(secret,{'http_status':400,'category':'context_or_token_limit',
                'message':secret,'error_body_bytes':200,'truncated':False},{'message':secret})
        s,text,events=self.evaluate(error)
        self.assertNotIn(secret,text)
        self.assertEqual([e['kind'] for e in events],['inference_started','inference_failed'])
        request=events[0]['payload']['request'];actual=(s.journal.directory/request['path']).read_bytes()
        self.assertEqual(events[1]['payload'],failure_payload(hashlib.sha256(actual).hexdigest()))
        self.assertEqual(list((s.journal.directory/'decisions').glob('*response*')),[])
        self.assertIsNone(s.decision)

    def test_missing_or_invalid_diagnostics_remain_unknown_without_parsing_exception(self):
        for diagnostics in ({},{'http_status':True,'category':['PRIVATE']},
                            {'http_status':700,'category':'PRIVATE'},{'http_status':'400'},['PRIVATE']):
            with self.subTest(diagnostics=diagnostics):
                _,text,events=self.evaluate(TransportError('PRIVATE HTTP 400',diagnostics))
                p=events[-1]['payload'];self.assertIsNone(p['http_status'])
                self.assertEqual(p['category'],'unclassified');self.assertNotIn('PRIVATE',text)

    def test_local_limit_validation_and_unexpected_bugs_do_not_become_transport_failures(self):
        for error in (RequestLimitError('TEST limit'),ResponseValidationError('TEST invalid probabilities'),
                      ValueError('TEST local bug'),RuntimeError('TEST local failure')):
            with self.subTest(type=type(error).__name__):
                _,_,events=self.evaluate(error)
                self.assertEqual([e['kind'] for e in events],['inference_started'])


class VerifyInferenceFailureTests(unittest.TestCase):
    def test_failure_is_accounted_without_a_response_input_or_token_invention(self):
        with tempfile.TemporaryDirectory() as directory:
            e=Evidence(directory,recording=True);insert_failure(e)
            with patch('civ2.verify._recording',return_value={'ffprobe':{'status':'passed'}}):
                r=verify_run(e.directory,ffprobe=None,terminal_review=e.terminal())
            d=r['decisions']
            self.assertEqual(d['inferences_started'],2);self.assertEqual(d['validated_responses'],1)
            self.assertEqual(d['inferences_without_response'],[]);self.assertEqual(d['failed_calls'],1)
            self.assertEqual(d['model_dispatches'],1);self.assertEqual(d['ordinary_input_events'],2)
            self.assertEqual(d['accepted_response_input_tokens'],100)
            self.assertEqual(d['failed_call_usage'],{'calls_with_unavailable_usage':1,'input_tokens':None,'output_tokens':None})
            self.assertTrue(r['completeness']['release_review_ready'])

    def test_explicit_late_failure_and_unresolved_request_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            e=Evidence(directory);insert_failure(e,late=True)
            r=verify_run(e.directory,ffprobe=None)
            self.assertTrue(r['decisions']['failed_inferences'][0]['recorded_late'])
            self.assertEqual(r['decisions']['inferences_without_response'],[])
        with tempfile.TemporaryDirectory() as directory:
            e=Evidence(directory,recording=True);insert_failure(e,unresolved=True)
            with patch('civ2.verify._recording',return_value={'ffprobe':{'status':'passed'}}):
                r=verify_run(e.directory,ffprobe=None,terminal_review=e.terminal())
            self.assertEqual(r['decisions']['inferences_without_response'],[2])
            self.assertEqual(r['decisions']['failed_calls'],0)
            self.assertFalse(r['completeness']['release_review_ready'])

    def test_schema_binding_enum_and_duplicates_reject(self):
        for mode in ('hash','unknown_id','used_id','duplicate','missing','private','status_low','status_high',
                     'status_bool','status_string','category','error_type','usage','late_type','undeclared_late'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=Evidence(directory);insert_failure(e,late=mode=='undeclared_late')
                def change(rows):
                    event=next(r for r in rows if r['kind']=='inference_failed');p=event['payload']
                    if mode=='hash':p['request_sha256']='f'*64
                    elif mode=='unknown_id':p['decision']=9
                    elif mode=='used_id':p['decision']=1
                    elif mode=='duplicate':rows.insert(rows.index(event)+1,deepcopy(event))
                    elif mode=='missing':p.pop('usage')
                    elif mode=='private':p['message']='PRIVATE'
                    elif mode.startswith('status_'):p['http_status']={'status_low':399,'status_high':600,'status_bool':True,'status_string':'400'}[mode]
                    elif mode=='category':p['category']='OTHER'
                    elif mode=='error_type':p['error_type']='RequestLimitError'
                    elif mode=='usage':p['usage']={'input_tokens':0,'output_tokens':0}
                    elif mode=='late_type':p['recorded_late']=1
                    else:p['recorded_late']=False
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_response_plan_or_dispatch_cannot_follow_failed_id(self):
        for kind in ('model_decision','command_dispatched'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                e=Evidence(directory);insert_failure(e)
                def change(rows):
                    failed=next(i for i,r in enumerate(rows) if r['kind']=='inference_failed')
                    source=deepcopy(next(r for r in rows if r['kind']==kind))
                    source['kind']=kind;source['payload']['decision']=2;source['elapsed_ms']=rows[failed]['elapsed_ms']
                    rows.insert(failed+1,source)
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_otherwise_valid_plan_response_cannot_follow_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            e=Evidence(directory);e.add_plan()
            self.assertEqual(verify_run(e.directory,ffprobe=None)['decisions']['planning_decisions'],1)
            def change(rows):
                i=next(i for i,r in enumerate(rows) if r['kind']=='inference_started' and r['payload'].get('stage')=='planning')
                start=rows[i]
                rows.insert(i+1,dict(kind='inference_failed',elapsed_ms=start['elapsed_ms'],
                    payload=failure_payload(start['payload']['request']['sha256'],start['payload']['decision'])))
            e.rewrite(change)
            with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_failed_request_does_not_close_pending_city_or_claim_input(self):
        with tempfile.TemporaryDirectory() as directory:
            e,_,_=city_evidence(directory);insert_failure(e)
            r=verify_run(e.directory,ffprobe=None)
            self.assertTrue(r['completeness']['pending_city_control'])
            self.assertEqual(r['decisions']['completed_city_reviews'],0)
            self.assertEqual(r['decisions']['model_dispatches'],1)

    def test_late_failure_preserves_existing_trade_continuation(self):
        from test_verify_trade import TradeEvidenceTests
        with tempfile.TemporaryDirectory() as directory:
            e=TradeEvidenceTests().make(directory)
            def change(rows):
                # The unresolved failed call precedes the actual latest trade.
                for event in rows:
                    if event['payload'].get('decision')==1:event['payload']['decision']=2
                    prior=event['payload'].get('prior_trade')
                    if prior:
                        prior['decision']=2
                        prior['context_sha256']=hashlib.sha256(canonical({k:v for k,v in prior.items() if k!='context_sha256'})).hexdigest()
                source=deepcopy(next(r for r in rows if r['kind']=='inference_started'))
                source['payload']['decision']=1
                i=next(i for i,r in enumerate(rows) if r['kind']=='inference_started')
                rows.insert(i,source)
                p=next(i for i,r in enumerate(rows) if r['kind']=='trade_followup_pending')
                rows[:]=rows[:p+1]
                rows.append(dict(kind='inference_failed',elapsed_ms=rows[-1]['elapsed_ms'],
                    payload=failure_payload(source['payload']['request']['sha256'],1,late=True)))
            e.rewrite(change);r=verify_run(e.directory,ffprobe=None)
            self.assertTrue(r['completeness']['pending_trade_continuation'])
            self.assertEqual(r['decisions']['accepted_trade_continuations'],0)
            self.assertEqual(r['decisions']['ordinary_input_events'],2)

    def test_late_diagnostic_preserves_blocked_navigation_and_activation(self):
        from test_verify_navigation import fixture,append
        from test_verify_activation import activation_evidence
        for mode in ('navigation','activation'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                if mode=='navigation':
                    e,p=fixture(directory);append(e,p)
                    target='city_navigation_incomplete';pending='pending_city_navigation'
                else:
                    e=activation_evidence(directory)
                    target='unit_activation_started';pending='pending_unit_activation'
                def change(rows):
                    source=deepcopy(next(r for r in rows if r['kind']=='inference_started'))
                    source['payload']['decision']=2
                    i=next(i for i,r in enumerate(rows) if r['kind']=='inference_started')
                    rows.insert(i,source)
                    stop=next(i for i,r in enumerate(rows) if r['kind']==target)
                    rows[:]=rows[:stop+1]
                    rows.append(dict(kind='inference_failed',elapsed_ms=rows[-1]['elapsed_ms'],
                        payload=failure_payload(source['payload']['request']['sha256'],late=True)))
                e.rewrite(change);r=verify_run(e.directory,ffprobe=None)
                self.assertTrue(r['completeness'][pending])
                self.assertEqual(r['decisions']['failed_calls'],1)


if __name__=='__main__':unittest.main()
