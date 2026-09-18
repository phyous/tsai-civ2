from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('Enraged TEST Emissary',350,326,164,16),
        prepared('*The TEST people grow weary of this endless',302,350,306,16),
        prepared('war. We suggest a cease fire.',302,370,196,16),
        prepared('"We accept-let us end this terrible war."',340,395,279,17),
        prepared('• "Cowards! We shall fight to the bitter end!"',314,420,318,16),
        prepared('OK',418,454,26,16)]


class CeaseProposalPixels(unittest.TestCase):
    def test_complete_proposal_and_all_paired_reads_required_atomically(self):
        for case in ('valid','nation','accept','tail','weak','missing_choice','extra_choice'):
            values=rows()
            if case=='missing_choice':values.pop(4)
            if case=='extra_choice':values.append(prepared('Pay gold.',314,440,100,12))
            before=deepcopy(values)
            def crop(image,old,name,*args,**kwargs):
                fresh=deepcopy(old)
                if '_intro_' in name:
                    fresh['text']='"The TEST people grow weary of this endless'
                    if case=='nation':fresh['text']=fresh['text'].replace('TEST','OTHER')
                elif '_tail_' in name:
                    fresh['text']='war. We suggest a cease fire."'
                    if case=='tail':fresh['text']='war. We suggest a peace treaty."'
                else:
                    fresh['text']='"We accept--let us end this terrible war."'
                    if case=='accept' and kwargs.get('grayscale'):fresh['text']='"We refuse--let us end this terrible war."'
                    if case=='weak':fresh['confidence']=.5
                return [fresh]
            with self.subTest(case=case),patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_cease_proposal(Image.new('RGB',(640,480)),values,None,None,{})
            if case=='valid':
                self.assertEqual(values[1]['text'],'"The TEST people grow weary of this endless')
                self.assertEqual(values[2]['text'],'war. We suggest a cease fire."')
                self.assertEqual(values[3]['text'],'"We accept--let us end this terrible war."')
                self.assertEqual([len(r['provenance'])for r in values[1:4]],[3,3,3])
                self.assertEqual(values[4],before[4])
            else:self.assertEqual(values,before)

    def test_actual_sioux_cease_fire_is_a_real_two_option_model_choice(self):
        p=Path('runs/attempt-010/screens/ui-0002955.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'PROPOSECEASE')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text']for r in d['options']],['"We accept--let us end this terrible war."','• "Cowards! We shall fight to the bitter end!"'])
        first=next(r for r in o['lines']if r['text'].startswith('"The Sioux'))
        self.assertTrue(first['provenance'][0]['text'].startswith('*The Sioux'))
        accepted=next(r for r in o['lines']if r['text'].startswith('"We accept'))
        self.assertIn('accept-let',accepted['provenance'][0]['text'])

if __name__=='__main__':unittest.main()
