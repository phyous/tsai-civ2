"""Demand recognition preserves both original strategic responses."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('ientral Siou Emisoary',398,306,144,16),
            prepared('"We know you have knowledge of Literacy.',310,332,294,16),
            prepared('Give us the secret at once, or face the',310,352,282,16),
            prepared('consequences!"',310,372,115,16),
            prepared('("Consequences, schmonsequences!"',338,390,254,27),
            prepared('Give secret of Literacy.',345,419,176,16),prepared('OK',458,453,22,16)]


class TechDemandPixels(unittest.TestCase):
    def test_complete_terms_and_two_scale_title_plus_actual_option_are_required(self):
        for case in ('valid','scale_disagrees','changed_attitude','changed_nation','changed_option','changed_technology','missing_choice'):
            values=rows()
            if case=='changed_technology':values[-2]['text']='Give secret of Writing.'
            if case=='missing_choice':values.pop(-2)
            def crop(image,old,name,*args,**kwargs):
                if name.startswith('tech_demand_radio'):
                    text='"Consequences, schmonsequences!"' if case!='changed_option' else '"Give us knowledge!"'
                    return [prepared(text,343,394,250,19)]
                text='Neutral Siouz Emissary'
                if case=='scale_disagrees' and kwargs['scale']==3:text='Neutral Sioux Emissary'
                if case=='changed_attitude':text='Hostile Siouz Emissary'
                if case=='changed_nation':text='Neutral German Emissary'
                return [prepared(text,395,306,147,16)]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_tech_demand_title(Image.new('RGB',(640,480)),values,None,None,{})
            self.assertEqual(values[0]['text'],'Neutral Siouz Emissary' if case=='valid' else 'ientral Siou Emisoary',case)
            if case=='valid':
                self.assertEqual(values[-3]['text'],'"Consequences, schmonsequences!"')
                self.assertEqual(len(values[0]['provenance']),5)
                self.assertEqual(values[0]['provenance'][0]['text'],'ientral Siou Emisoary')

    def test_original_literacy_demand_requires_model_and_retains_both_choices(self):
        path=Path('runs/attempt-010/screens/ui-0002497.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(path);o['path']=str(path.resolve())
        d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['resource_tag'],'TAKECIV2')
        self.assertEqual([r['text'] for r in d['options']],['"Consequences, schmonsequences!"','Give secret of Literacy.'])
        self.assertIsNone(d['mechanical_action'])
        self.assertEqual(o['lines'][0]['provenance'][0]['text'],'ientral Siou Emisoary')


if __name__=='__main__':unittest.main()
