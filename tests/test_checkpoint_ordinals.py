"""Synthetic TEST read failures retain distinct successful counts and ordinals."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from civ2.evidence import canonical
from civ2.verify import verify_run, VerificationError, PUBLIC_NOTICE_GAME_SHA256, PUBLIC_NOTICE_RESOURCES
from test_verify_memory import LiveEvidence


class CheckpointOrdinalTests(unittest.TestCase):
    def evidence(self,directory):
        e=LiveEvidence(directory,decide=False);s=e.session
        screen=dict(kind='end_turn',supported=True,title='End of Turn',options=[],
            sha256=hashlib.sha256(e.frame).hexdigest(),width=640,height=480)
        s.choose_empire(screen,{'turn':1,'actions':[]});e.finish()
        source=e.directory/'observations/d000001.json';target=source.with_name('d000003.json')
        source.rename(target)
        def change(rows):
            event=next(r for r in rows if r['kind']=='checkpoint');p=event['payload']
            p.pop('checkpoint');p['artifact']['path']='observations/d000003.json'
            digest=p['artifact']['sha256'];elapsed=rows[-1]['elapsed_ms']
            additions=[dict(kind='screen_observed',elapsed_ms=elapsed,payload=dict(
                screen=screen['sha256'],classification='end_turn',supported=True)),
                dict(kind='checkpoint_reused',elapsed_ms=elapsed,payload=dict(
                    checkpoint=3,observation_sha256=digest,turn=2,year=-3950,screen=screen['sha256'],
                    ordinary_inputs_since_checkpoint=False,reason='TEST reuse after failed-read ordinal gaps'))]
            # A public notice binds the actual retained checkpoint ordinal too.
            notice=dict(kind='information',resource_tag='SNEAK',title='Defense Minister',
                observed_text='Defense Minister\nTEST ONLY public notice\nOK',image_sha256=screen['sha256'],
                observed_at_utc='2026-09-17T00:00:00+00:00',observation_elapsed_ms=elapsed,
                last_checkpoint=dict(index=3,turn=2,year_raw=-3950,observation_sha256=digest),
                source=dict(game_text_sha256=PUBLIC_NOTICE_GAME_SHA256,resource_sha256=PUBLIC_NOTICE_RESOURCES['SNEAK']))
            notice['id']=hashlib.sha256(canonical(notice)).hexdigest()
            additions.extend([dict(kind='screen_observed',elapsed_ms=elapsed,payload=dict(
                screen=screen['sha256'],classification='information',supported=True)),
                dict(kind='observed_public_notice',elapsed_ms=elapsed,payload=dict(notice=notice,
                    source_image=dict(path='screens/memory-000000-0.png',sha256=screen['sha256'],bytes=len(e.frame))))])
            rows[-1:-1]=additions
        e.rewrite(change);return e

    def test_retained_ordinal_gap_does_not_invent_successful_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            e=self.evidence(directory);r=verify_run(e.directory,ffprobe=None)['decisions']
            self.assertEqual(r['successful_native_checkpoints'],1)
            self.assertEqual(r['last_native_checkpoint_ordinal'],3)
            self.assertEqual(r['reused_native_checkpoints'],1)
            self.assertEqual(r['observed_public_notices'],1)

    def test_wrong_reuse_notice_payload_and_repeated_artifact_ordinal_fail(self):
        for mode in ('reuse','notice','explicit','repeat'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                e=self.evidence(directory)
                def change(rows):
                    cp=next(r for r in rows if r['kind']=='checkpoint')
                    if mode=='reuse':next(r for r in rows if r['kind']=='checkpoint_reused')['payload']['checkpoint']=1
                    elif mode=='explicit':cp['payload']['checkpoint']=1
                    elif mode=='repeat':rows.insert(rows.index(cp)+1,deepcopy(cp))
                    else:
                        n=next(r for r in rows if r['kind']=='observed_public_notice')['payload']['notice']
                        n['last_checkpoint']['index']=1;n.pop('id');n['id']=hashlib.sha256(canonical(n)).hexdigest()
                e.rewrite(change)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_failed_live_read_does_not_consume_next_successful_ordinal(self):
        with tempfile.TemporaryDirectory() as directory:
            e=LiveEvidence(directory,decide=False);s=e.session
            e.observer.failure=RuntimeError('TEST unresolved native modal')
            with self.assertRaises(RuntimeError):s.checkpoint()
            self.assertEqual(s.checkpoints,0)
            e.observer.failure=None;e.finish()
            r=verify_run(e.directory,ffprobe=None)['decisions']
            self.assertEqual(r['successful_native_checkpoints'],1)
            self.assertEqual(r['last_native_checkpoint_ordinal'],1)
            self.assertTrue((e.directory/'observations/d000001.json').is_file())
            e.session.ui.save_native.assert_not_called()


if __name__=='__main__':unittest.main()
