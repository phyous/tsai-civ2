from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('Detense Binister',270,186,104,14),
            prepared('The TEST empire is swept by Civil War triggered by the fall',120,208,392,18),
            prepared('of their capital! When the dust settles the empire has been',120,230,390,16),
            prepared('split into loyal (EST) and rebel (OTHER) factions.',118,250,322,20),
            prepared('OK',308,280,24,14)]


class CivilWarPixels(unittest.TestCase):
    def test_atomic_same_nation_and_full_source_prose_required(self):
        for case in ('valid','disagree','weak','moved','title','loyal','rebel','prose','extra','missing'):
            values=rows()
            if case=='prose':values[2]['text']=values[2]['text'].replace('capital!','capital?')
            if case=='extra':values.append(prepared('Cancel',450,280,50,14))
            if case=='missing':values.pop(2)
            before=deepcopy(values)
            def crop(image,old,name,*args,**kwargs):
                r=deepcopy(old)
                if '_title_' in name:r['text']='Foreign Minister' if case=='title' else 'Defense Bfinister'
                else:
                    r['text']='split into loyal (TEST) and rebel (OTHER) factions.'
                    if case=='loyal':r['text']=r['text'].replace('TEST','WEST')
                    if case=='rebel':r['text']=r['text'].replace('OTHER','ELSE')
                    if case=='disagree' and kwargs.get('grayscale'):r['text']=old['text']
                    if case=='weak':r['confidence']=.5
                    if case=='moved':r['bounds'][0]+=120;r['center'][0]+=120;r['x']+=120/640
                return [r]
            with self.subTest(case=case),patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_civil_war_notice(Image.new('RGB',(640,480)),values,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(values[0]['text'],'Defense Bfinister')
                self.assertEqual(values[3]['text'],'split into loyal (TEST) and rebel (OTHER) factions.')
                self.assertEqual(values[1:3],before[1:3]);self.assertEqual(len(values[3]['provenance']),3)
            else:self.assertEqual(values,before,case)

    def test_correct_native_row_is_preserved(self):
        values=rows();values[0]['text']='Defense Minister';values[3]['text']='split into loyal (TEST) and rebel (OTHER) factions.'
        before=deepcopy(values)
        with patch.object(observe,'_crop_text',side_effect=AssertionError('No reread required')):
            observe._recover_civil_war_notice(Image.new('RGB',(640,480)),values,None,None,{'passes':[]})
        self.assertEqual(values,before)

    def test_actual_zulu_schism_preserves_both_observed_nations(self):
        p=Path('runs/attempt-010/screens/ui-0003142.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        o=observe.recognize(p)
        title=next(r for r in o['lines'] if r['text']=='Defense Bfinister')
        tail=next(r for r in o['lines'] if r['text'].startswith('split into loyal'))
        self.assertEqual([v['text']for v in title['provenance']],['Detense Binister','Defense Bfinister','Defense Bfinister'])
        self.assertEqual(tail['text'],'split into loyal (Zulu) and rebel (Greek) factions.')
        self.assertIn('(ulu)',tail['provenance'][0]['text'])
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'SCHISM')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')


if __name__=='__main__':unittest.main()
