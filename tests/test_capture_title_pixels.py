from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('Detense bhnuster',270,122,102,12),
            prepared('Sioux capture Hispalis. 13 gold pieces',302,144,260,18),
            prepared('plundered.',298,165,82,16),prepared('OK',309,342,22,16)]


class CaptureTitlePixels(unittest.TestCase):
    def test_capture_prose_and_both_actual_title_reads_required(self):
        for case in ('valid','disagree','low','moved','other_body','missing_body','extra_choice'):
            values=rows();a=prepared('Defense Mfinister',270,122,102,12);b=deepcopy(a)
            if case=='disagree':b['text']='Defense Minister'
            if case=='low':b['confidence']=.5
            if case=='moved':b['bounds'][0]+=80;b['center'][0]+=80
            if case=='other_body':values[1]['text']='Sioux capture Hispalis. 13 gold bars'
            if case=='missing_body':values.pop(2)
            if case=='extra_choice':values.append(prepared('Cancel',200,342,40,16))
            with patch.object(observe,'_crop_text',side_effect=[[a],[b]]):
                observe._recover_capture_notice_title(Image.new('RGB',(640,480)),values,None,None,{})
            self.assertEqual(values[0]['text'],'Defense Mfinister' if case=='valid' else 'Detense bhnuster',case)
            self.assertEqual(values[1]['text'],rows()[1]['text'] if case!='other_body' else 'Sioux capture Hispalis. 13 gold bars')

    def test_actual_hispalis_loss_preserves_full_source_notice_and_numbers(self):
        path=Path('runs/attempt-010/screens/ui-0002521.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(path);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'information')
        self.assertEqual(d['resource_tag'],'CITYCAPTURE')
        self.assertEqual(d['evidence']['observed_body'],'Sioux capture Hispalis. 13 gold pieces\nplundered.')
        title=next(r for r in o['lines'] if r['text']=='Defense Mfinister')
        self.assertEqual([p['text'] for p in title['provenance']],['Detense bhnuster','Defense Mfinister','Defense Mfinister'])
        self.assertEqual(d['mechanical_action'],'acknowledge_information')


if __name__=='__main__':unittest.main()
