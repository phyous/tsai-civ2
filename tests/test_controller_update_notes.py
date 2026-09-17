"""Both historical note forms remain diagnostics with no input authority."""
from copy import deepcopy
import tempfile
import unittest
from civ2.verify import verify_run,VerificationError
from test_verify import Evidence,city_evidence


def append_note(e,payload):
    def change(rows):
        i=next((i for i,r in enumerate(rows) if r['kind']=='session_stopped'),len(rows))
        rows.insert(i,dict(kind='controller_update',elapsed_ms=rows[i-1]['elapsed_ms'],payload=deepcopy(payload)))
    e.rewrite(change)


class ControllerNotes(unittest.TestCase):
    def test_reason_only_and_scoped_note_never_dispatch_or_close_pending_city(self):
        for payload in ({'reason':'TEST historical observation repair'},
                        {'reason':'TEST observation repair','scope':'TEST diagnostics only'}):
            with self.subTest(payload=payload),tempfile.TemporaryDirectory() as directory:
                e,_,_=city_evidence(directory);before=verify_run(e.directory,ffprobe=None)
                append_note(e,payload);after=verify_run(e.directory,ffprobe=None)
                self.assertEqual(after['decisions']['controller_update_notes'],1)
                for key in ('model_dispatches','ordinary_input_events','completed_city_reviews'):
                    self.assertEqual(after['decisions'][key],before['decisions'][key])
                self.assertTrue(after['completeness']['pending_city_control'])

    def test_note_preserves_pending_trade_instead_of_authorizing_or_cancelling_it(self):
        from test_verify_trade import TradeEvidenceTests
        for scope in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                e=TradeEvidenceTests().make(directory)
                e.rewrite(lambda rows:rows.__setitem__(slice(None),rows[:next(i for i,r in enumerate(rows) if r['kind']=='trade_followup_pending')+1]))
                append_note(e,{'reason':'TEST observation only',**({'scope':'TEST diagnostics'} if scope else {})})
                r=verify_run(e.directory,ffprobe=None)
                self.assertTrue(r['completeness']['pending_trade_continuation'])
                self.assertEqual(r['decisions']['accepted_trade_continuations'],0)
                self.assertEqual(r['decisions']['ordinary_input_events'],2)

    def test_empty_long_missing_or_extra_authority_fields_rejected(self):
        for payload in ({},{'scope':'TEST'}, {'reason':''}, {'reason':'x'*513}, {'reason':'TEST','scope':''},
                        {'reason':'TEST','scope':2}, {'reason':'TEST','inputs':[]},
                        {'reason':'TEST','decision':1},{'reason':'TEST','clears_pending':True}):
            with self.subTest(payload=payload),tempfile.TemporaryDirectory() as directory:
                e=Evidence(directory);append_note(e,payload)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)


if __name__=='__main__':unittest.main()
