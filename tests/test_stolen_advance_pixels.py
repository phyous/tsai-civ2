from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('Ciadization Advance Sbolen!',232,206,176,16),
            prepared('Sioux take Literacyl',182,230,138,16),prepared('OK',309,258,22,16)]


class StolenAdvancePixels(unittest.TestCase):
    def test_atomic_pair_preserves_nation_and_advance(self):
        for case in ('valid','disagree','changed_nation','changed_advance','changed_title','low','extra_choice'):
            values=rows()
            if case=='extra_choice':values.append(prepared('Cancel',220,258,40,16))
            def crop(image,old,name,*args,**kwargs):
                if '_title_' in name:
                    text='Cialization Advance Stolen!' if case!='changed_title' else 'Civilization Advance'
                    result=prepared(text,232,206,176,16)
                else:
                    text='Sioux take Literacy!'
                    if case=='disagree' and kwargs.get('grayscale'):text='Sioux take Literacyl'
                    if case=='changed_nation':text='Germans take Literacy!'
                    if case=='changed_advance':text='Sioux take Writing!'
                    result=prepared(text,182,230,138,16)
                if case=='low':result['confidence']=.5
                return [result]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_stolen_advance_notice(Image.new('RGB',(640,480)),values,None,None,{})
            self.assertEqual(values[0]['text'],'Cialization Advance Stolen!' if case=='valid' else rows()[0]['text'],case)
            self.assertEqual(values[1]['text'],'Sioux take Literacy!' if case=='valid' else rows()[1]['text'],case)

    def test_actual_source_bound_stolen_advance_notice(self):
        path=Path('runs/attempt-010/screens/ui-0002533.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(path);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'TOOKCIV')
        self.assertEqual(d['evidence']['observed_body'],'Sioux take Literacy!')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        body=next(r for r in o['lines'] if r['text']=='Sioux take Literacy!')
        self.assertEqual([p['text'] for p in body['provenance']],['Sioux take Literacyl','Sioux take Literacy!','Sioux take Literacy!'])


if __name__=='__main__':unittest.main()
