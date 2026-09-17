"""Declared missing mechanical receipts remain an explicit incomplete audit."""
from copy import deepcopy
import hashlib
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from civ2.verify import verify_run,VerificationError
from test_verify import Evidence,city_evidence


def gap(e,start=2,end=4):
    return dict(label='acknowledge_information',before=deepcopy(e.screen),after=deepcopy(e.screen),
        input_sequence_before=start,input_sequence_after=end,
        reason='post_input_ocr_failed_receipts_unavailable')


def insert(e,payload):
    def change(rows):
        stop=next(i for i,r in enumerate(rows) if r['kind']=='session_stopped')
        rows.insert(stop,dict(kind='mechanical_input_gap',elapsed_ms=rows[stop]['elapsed_ms'],payload=payload))
    e.rewrite(change)


class MechanicalGapTests(unittest.TestCase):
    def test_gap_is_separate_from_model_decisions_and_prevents_release(self):
        with tempfile.TemporaryDirectory() as directory:
            e=Evidence(directory,recording=True)
            recording={'ffprobe':{'status':'passed'}}
            review=e.terminal()
            with patch('civ2.verify._recording',return_value=recording):
                baseline=verify_run(e.directory,ffprobe=None,terminal_review=review)
            self.assertTrue(baseline['completeness']['release_review_ready'])
            insert(e,gap(e));review=e.terminal()
            with patch('civ2.verify._recording',return_value=recording):
                result=verify_run(e.directory,ffprobe=None,terminal_review=review)
            self.assertEqual(result['integrity'],'passed')
            self.assertEqual(result['decisions']['input_coverage'],'incomplete')
            self.assertFalse(result['completeness']['release_review_ready'])
            self.assertEqual(result['decisions']['unverified_input_gaps'],[])
            actual=result['decisions']['unverified_mechanical_input_gaps']
            self.assertEqual(len(actual),1);self.assertNotIn('decision',actual[0])
            self.assertEqual(actual[0]['input_sequence_before'],2)
            self.assertEqual(actual[0]['input_sequence_after'],4)
            self.assertEqual(actual[0]['before'],e.screen)
            self.assertEqual(result['decisions']['ordinary_input_events'],baseline['decisions']['ordinary_input_events'])
            self.assertEqual(result['decisions']['model_dispatches'],baseline['decisions']['model_dispatches'])
            self.assertEqual(result['completeness']['uninterpreted_event_counts'],{})
            self.assertTrue(any('Mechanical input receipts are unavailable' in s for s in result['limitations']))

    def test_gap_does_not_dispatch_a_waiting_model_choice_or_close_city_review(self):
        with tempfile.TemporaryDirectory() as directory:
            e=Evidence(directory,dispatch=False);insert(e,gap(e,0,2))
            result=verify_run(e.directory,ffprobe=None)
            self.assertEqual(result['decisions']['undispatched_decisions'],[1])
            self.assertEqual(result['decisions']['model_dispatches'],0)
            self.assertEqual(result['decisions']['ordinary_input_events'],0)
        with tempfile.TemporaryDirectory() as directory:
            e,_,_=city_evidence(directory);insert(e,gap(e))
            result=verify_run(e.directory,ffprobe=None)
            self.assertTrue(result['completeness']['pending_city_control'])
            self.assertEqual(result['decisions']['completed_city_reviews'],0)

    def test_gap_preserves_pending_trade_without_supplying_confirmation(self):
        from test_verify_trade import TradeEvidenceTests
        with tempfile.TemporaryDirectory() as directory:
            e=TradeEvidenceTests().make(directory)
            def change(rows):
                i=next(i for i,r in enumerate(rows) if r['kind']=='trade_followup_pending')
                rows[:]=rows[:i+1]
                rows.append(dict(kind='mechanical_input_gap',elapsed_ms=rows[-1]['elapsed_ms'],payload=gap(e)))
            e.rewrite(change);result=verify_run(e.directory,ffprobe=None)
            self.assertTrue(result['completeness']['pending_trade_continuation'])
            self.assertEqual(result['decisions']['accepted_trade_continuations'],0)
            self.assertEqual(result['decisions']['ordinary_input_events'],2)

    def test_schema_and_sequence_reject_receipt_invention_or_backward_ranges(self):
        for mode in ('label','reason','decision','action','inputs','missing','backward','equal','boolean','overflow','repeat'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=Evidence(directory);p=gap(e)
                if mode=='label':p['label']='accept_observed_default_name'
                elif mode=='reason':p['reason']='TEST inferred completion'
                elif mode in ('decision','action','inputs'):p[mode]=1 if mode=='decision' else []
                elif mode=='missing':p.pop('input_sequence_before')
                elif mode=='backward':p['input_sequence_before']=1
                elif mode=='equal':p['input_sequence_after']=2
                elif mode=='boolean':p['input_sequence_before']=True
                elif mode=='overflow':p['input_sequence_after']=2**53
                insert(e,p)
                if mode=='repeat':insert(e,p)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_images_require_exact_descriptors_and_decodable_original_png(self):
        for mode in ('wrong_hash','wrong_bytes','extra_field','missing_bytes','outside','size','format','truncated'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=Evidence(directory);p=gap(e)
                if mode=='wrong_hash':p['after']['sha256']='a'*64
                elif mode=='wrong_bytes':p['after']['bytes']+=1
                elif mode=='extra_field':p['after']['inferred_success']=True
                elif mode=='missing_bytes':p['after'].pop('bytes')
                else:
                    relative='outside.png' if mode=='outside' else 'screens/gap.png'
                    path=e.directory/relative
                    if mode=='size':Image.new('RGB',(639,480)).save(path)
                    elif mode=='format':Image.new('RGB',(640,480)).save(path,format='BMP')
                    elif mode=='truncated':path.write_bytes((e.directory/e.screen['path']).read_bytes()[:60])
                    else:path.write_bytes((e.directory/e.screen['path']).read_bytes())
                    data=path.read_bytes();p['after']={'path':relative,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                insert(e,p)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)


if __name__=='__main__':unittest.main()
