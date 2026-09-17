"""Synthetic audience crop negatives and an optional retained original frame."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from tests.test_herald import prepared
from civ2.observe import _recover_audience_body


class AudienceBodyPixels(unittest.TestCase):
    def fixture(self):
        return [prepared('Uncooperative TEST Emissary',222,158,200,16),
            prepared('An emissary from Empress TEST of the',158,182,284,16),
            prepared('TEST wishes to speak with you, Will you',158,202,288,16),
            prepared('receive hert',158,224,88,14),
            prepared('O "Yes. I will grant an audience."',170,246,238,20),
            prepared('O "No. Send her away."',170,272,176,18),prepared('OK',308,308,24,14)]

    def test_two_actual_reads_preserve_all_names_and_model_options(self):
        rows=self.fixture();a=deepcopy(rows[2]);b=deepcopy(rows[3])
        a['text']='TEST wishes to speak with you. Will you';b['text']='receive her?'
        a['provenance']=[{'text':a['text'],'preprocessing':'TEST crop'}]
        b['provenance']=[{'text':b['text'],'preprocessing':'TEST crop'}]
        with patch('civ2.observe._crop_text',side_effect=[[a],[deepcopy(a)],[b],[deepcopy(b)]]):
            _recover_audience_body(Image.new('RGB',(640,480)),rows,None,None,{})
        self.assertEqual(rows[2]['text'],a['text']);self.assertEqual(rows[3]['text'],b['text'])
        self.assertEqual(rows[2]['provenance'][0]['text'],'TEST wishes to speak with you, Will you')
        self.assertEqual(rows[4:],[*self.fixture()[4:]])

    def test_disagreement_changed_name_gender_or_geometry_rejects_atomically(self):
        for case in ('name','gender','disagree','geometry'):
            rows=self.fixture();before=deepcopy(rows);a=deepcopy(rows[2]);b=deepcopy(rows[3])
            a['text']='TEST wishes to speak with you. Will you';b['text']='receive her?'
            peer=deepcopy(b)
            if case=='name':a['text']=a['text'].replace('TEST','OTHER')
            elif case=='gender':b['text']=peer['text']='receive him?'
            elif case=='disagree':peer['text']='receive him?'
            elif case=='geometry':peer['center'][0]+=80;peer['bounds'][0]+=80
            with patch('civ2.observe._crop_text',side_effect=[[a],[deepcopy(a)],[b],[peer]]):
                _recover_audience_body(Image.new('RGB',(640,480)),rows,None,None,{})
            with self.subTest(case=case):self.assertEqual(rows,before)

    def test_missing_choice_or_modal_controls_cannot_trigger_recovery(self):
        for case in ('missing','control'):
            rows=self.fixture()
            if case=='missing':rows.pop(5)
            else:rows.append(prepared('Cancel',400,308,35,14))
            with patch('civ2.observe._crop_text') as crop:
                _recover_audience_body(Image.new('RGB',(640,480)),rows,None,None,{})
            crop.assert_not_called()

    def test_actual_spanish_audience_remains_a_model_choice(self):
        from civ2.observe import recognize
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        path=Path(__file__).resolve().parents[1]/'runs/attempt-011/screens/ui-0001140.png'
        if not path.exists():self.skipTest('Private original capture unavailable')
        o=recognize(path);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EMISSARY')
        self.assertTrue(d['requires_model']);self.assertEqual(len(d['options']),2)
        recovered=next(r for r in o['lines'] if r['text']=='receive her?')
        self.assertEqual(recovered['provenance'][0]['text'],'receive hert')


if __name__=='__main__':unittest.main()
