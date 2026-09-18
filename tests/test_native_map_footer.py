"""Exact original footer blink binding; all non-footer pixels stay immutable."""
from copy import deepcopy
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import footer_pixels
from civ2.native_map import context_for,footer_blink_context,evidence_for,LEFT_MAP_REASON
from civ2.memory import MemoryObservationError
from civ2.run import _native_map_fallback
from civ2.dialogs import classify_dialog
from civ2.verify import verify_run,VerificationError
from test_native_map import fixture
from test_verify_memory import LiveEvidence
from test_verify import picture


def frames():
    a=Image.open(BytesIO(picture())).convert('RGB');b=a.copy()
    a.putpixel((480,452),(255,255,255));b.putpixel((480,452),(134,134,134))
    encoded=[]
    for image in (a,b):
        out=BytesIO();image.save(out,format='PNG');encoded.append(out.getvalue())
    pair=tuple(hashlib.sha256(image.crop(footer_pixels.CROP).tobytes()).hexdigest() for image in (a,b))
    return encoded,pair


class NativeFooterContext(unittest.TestCase):
    def test_only_calibrated_pair_and_identical_other_pixels_can_bind_current(self):
        images,pair=frames()
        from test_memory import capsule,wire
        from test_verify import initial_save
        digest=hashlib.sha256(images[0]).hexdigest()
        data=capsule([wire(initial_save()),wire(initial_save(),nonce='b'*32)],image_sha256=[digest]*3)
        base=context_for(data,digest,7)
        for case in ('valid','uncalibrated','map','status','source','dimensions','footer_other'):
            a,b=images
            if case in ('map','status','dimensions','footer_other'):
                im=Image.open(BytesIO(b)).convert('RGB')
                if case=='dimensions':im=im.crop((0,0,639,480))
                else:im.putpixel({'map':(300,200),'status':(500,220),'footer_other':(490,450)}[case],(80,50,30))
                out=BytesIO();im.save(out,format='PNG');b=out.getvalue()
            if case=='source':a=images[1]
            with patch.object(footer_pixels,'FOOTER_BLINK_CALIBRATIONS',() if case=='uncalibrated' else ((footer_pixels.CROP,*pair),)):
                if case!='valid':
                    with self.assertRaises(MemoryObservationError,msg=case):footer_blink_context(base,a,b)
                else:
                    context=footer_blink_context(base,a,b)
                    o=dict(width=640,height=480,sha256=hashlib.sha256(b).hexdigest())
                    proof=evidence_for(context,o);self.assertEqual(proof['image_sha256'],o['sha256'])
                    self.assertEqual(proof['bracketed_image_sha256'],digest)
                    o['sha256']=digest;self.assertIsNone(evidence_for(context,o))

    def test_runner_archives_current_and_verifier_rechecks_both_pixel_sources(self):
        images,pair=frames()
        with tempfile.TemporaryDirectory() as directory,patch.object(footer_pixels,'FOOTER_BLINK_CALIBRATIONS',((footer_pixels.CROP,*pair),)):
            e=LiveEvidence(directory,decide=False);s=e.session;e.observer.frame=images[0]
            _,o,_=fixture();o['path']=str(e.directory/'screens/memory-000000-0.png')
            original=classify_dialog(o,state=s.state)
            s.game.rpc.return_value=dict(paused=True,inputSequence=7,heldKeys=[],buttons=0)
            s.game.request.return_value=images[1]
            def recognize(path):
                value=deepcopy(o);value['sha256']=hashlib.sha256(Path(path).read_bytes()).hexdigest();return value
            with patch('civ2.observe.recognize',side_effect=recognize):
                current,result=_native_map_fallback(s,o,original,'')
            self.assertTrue(result['supported'],result)
            self.assertEqual(current['sha256'],hashlib.sha256(images[1]).hexdigest())
            s.ui.key.assert_not_called();s.game.click.assert_not_called()
            e.finish(checkpoint=False)
            self.assertEqual(verify_run(e.directory,ffprobe=None)['decisions']['native_map_observations'],1)
            def mutate(events):
                payload=next(v['payload'] for v in events if v['kind']=='native_map_observed')
                payload['current_image']=payload['receipt']['images'][1]
            e.rewrite(mutate)
            with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_actual_012_map_changes_only_calibrated_footer(self):
        paths=list(Path('runs/attempt-012/screens').glob('native-map-003126-*-1.png'))
        current=list(Path('runs/attempt-012/screens').glob('native-map-current-003126-*.png'))
        capsules=list(Path('runs/attempt-012/observations').glob('native-map-003126-*.json'))
        if len(paths)!=1 or len(current)!=1 or len(capsules)!=1:self.skipTest('Private native proof unavailable')
        import json
        data=capsules[0].read_bytes();proof=json.loads(data)['proof']
        base=context_for(data,proof['image_sha256'][1],proof['input_sequence_after'])
        context=footer_blink_context(base,paths[0].read_bytes(),current[0].read_bytes())
        from civ2.observe import recognize
        from civ2.memory import parse_memory
        o=recognize(current[0]);d=classify_dialog(o,state=parse_memory(data),native_map_context=context)
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'end_turn')

if __name__=='__main__':unittest.main()
