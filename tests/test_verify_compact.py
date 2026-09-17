"""Original request hashes stay binding while compact facts are decoded offline."""
from copy import deepcopy
import hashlib
import json
import tempfile
import unittest
from civ2.compact import compact_model_state,expand_model_state
from civ2.verify import verify_run,VerificationError
from test_verify import Evidence
import test_verify as fixtures


class VerifyCompact(unittest.TestCase):
    def evidence(self,directory):
        e=Evidence(directory)
        _,retained,request=fixtures.VerifyTests.public_history(self,e,count=5)
        request['state']=compact_model_state(request['state'])
        e.change_artifact('decisions/request.json',request)
        return e,retained,request

    def test_compact_notice_facts_match_full_journal_and_actual_request_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            e,retained,request=self.evidence(directory)
            p=e.directory/'decisions/request.json';before=p.read_bytes()
            report=verify_run(e.directory,ffprobe=None)
            self.assertEqual(report['decisions']['compacted_model_contexts'],1)
            self.assertEqual(report['decisions']['model_dispatches'],1)
            self.assertEqual(report['decisions']['retained_public_notice_ids'],[n['id'] for n in retained])
            self.assertEqual(p.read_bytes(),before)
            event=next(json.loads(s) for s in (e.directory/'events.jsonl').read_text().splitlines()
                       if json.loads(s)['kind']=='inference_started')
            self.assertEqual(event['payload']['request']['sha256'],hashlib.sha256(before).hexdigest())

    def test_unknown_encoding_and_changed_historical_facts_are_rejected(self):
        for mode in ('revision','extra','bad_row','changed_text','missing_notice','changed_turn','note'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e,_,request=self.evidence(directory);changed=deepcopy(request)
                if mode=='revision':changed['state']['model_state_encoding']['revision']='TEST unknown'
                elif mode=='extra':changed['state']['model_state_encoding']['extra']='TEST extra'
                elif mode=='bad_row':changed['state']['recent_observed_events']['rows'][0].pop()
                else:
                    facts=expand_model_state(changed['state'])
                    if mode=='changed_text':facts['recent_observed_events'][0]['observed_text']='Invented enemy location'
                    elif mode=='missing_notice':facts['recent_observed_events'].pop()
                    elif mode=='changed_turn':facts['recent_observed_events'][0]['last_checkpoint']['turn']=99
                    else:facts['recent_observed_events_note']='Historical facts are current facts.'
                    changed['state']=compact_model_state(facts)
                e.change_artifact('decisions/request.json',changed)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_legacy_raw_context_remains_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            e=Evidence(directory);fixtures.VerifyTests.public_history(self,e,count=5)
            self.assertEqual(verify_run(e.directory,ffprobe=None)['decisions']['compacted_model_contexts'],0)


if __name__=='__main__':unittest.main()
