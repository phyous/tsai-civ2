from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('Nentral TESTI Emisoary',360,306,150,16),
        prepared('"We invite you to join our crusade to rid the',312,330,294,16),
        prepared('world of the evil OTHER. We will sign an',312,350,282,16),
        prepared('alliance for the duration of the hostilities."',312,368,284,16),
        prepared('"No, not interested."',346,392,148,22),
        prepared('• Yes, declare war on OTHER.',324,420,228,18),prepared('OK',424,454,26,16)]


class CrusadeTitlePixels(unittest.TestCase):
    def test_complete_matching_target_and_paired_near_heading_required(self):
        for case in ('valid','target','missing_terms','distant_name','peer','weak','extra_choice','changed_choice'):
            values=rows();a=prepared('Neutral TEST Emissary',360,306,150,16);b=deepcopy(a)
            if case=='target':values[5]['text']='• Yes, declare war on ELSE.'
            if case=='missing_terms':values[3]['text']='alliance.'
            if case=='distant_name':a['text']=b['text']='Neutral ELSE Emissary'
            if case=='peer':b['text']='Neutral TESTI Emissary'
            if case=='weak':b['confidence']=.5
            if case=='extra_choice':values.append(prepared('Pay gold',340,440,100,12))
            before=deepcopy(values)
            yes=prepared('Yes, declare war on OTHER.',348,422,203,18);peer=deepcopy(yes)
            if case=='changed_choice':peer['text']='Yes, declare war on ELSE.'
            with self.subTest(case=case),patch.object(observe,'_crop_text',side_effect=[[a],[b],[yes],[peer]]):
                observe._recover_crusade_title(Image.new('RGB',(640,480)),values,None,None,{})
            if case=='valid':
                self.assertEqual(values[0]['text'],'Neutral TEST Emissary');self.assertEqual(len(values[0]['provenance']),3)
                self.assertEqual(values[1:5],before[1:5]);self.assertEqual(values[5]['text'],'Yes, declare war on OTHER.')
            else:self.assertEqual(values,before)

    def test_actual_sioux_alliance_requires_fresh_model_choice(self):
        p=Path('runs/attempt-010/screens/ui-0003061.png')
        if not p.exists():self.skipTest('Private original capture unavailable')
        from civ2.run import game_text
        from civ2.dialogs import classify_dialog
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'CRUSADE')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text']for r in d['options']],['"No, not interested."','Yes, declare war on Germans.'])
        title=next(r for r in o['lines']if r['text']=='Neutral Sioux Emissary')
        self.assertEqual([r['text']for r in title['provenance']],['Nentral Siou Emisoary','Neutral Sioux Emissary','Neutral Sioux Emissary'])

if __name__=='__main__':unittest.main()
