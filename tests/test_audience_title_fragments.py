"""A title crop can join observed fragments but cannot invent audience terms."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.dialogs import classify_dialog
from tests.test_herald import prepared


SOURCE='''@EMISSARY
@width=320
@title=%STRING0 Emissary
An emissary from %STRING1 %STRING2 of the %STRING3 wishes to speak with you.  Will you receive %STRING4?

"Yes. I will grant an audience."
"No. Send %STRING4 away."
'''


class AudienceTitleFragments(unittest.TestCase):
    def fixture(self):
        return [prepared('Uncooperative',228,160,94,14),prepared('TEST Emissary',320,158,96,17),
            prepared('An emissary from Chief TEST of the TEST',158,182,324,16),
            prepared('wishes to speak with you. Will you receive',158,202,284,16),
            prepared('him?',156,222,38,16),prepared('"Yes. I will grant an audience."',194,248,214,18),
            prepared('O "No. Send him away."',170,272,178,18),prepared('OK',308,308,24,14)]

    def fresh(self):
        return prepared('Uncooperative TEST Emissary',225,159,189,16)

    def recover(self,rows,first=None,second=None):
        first=self.fresh() if first is None else first
        second=deepcopy(first) if second is None else second
        with patch.object(observe,'_crop_text',side_effect=[[first],[second]]) as crop:
            observe._recover_audience_title_fragments(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
        return crop

    def test_complete_pair_preserves_original_fragments_and_requires_model(self):
        for reversed_headings in (False,True):
            rows=self.fixture();unchanged=deepcopy(rows[2:])
            if reversed_headings:rows[:2]=reversed(rows[:2])
            self.recover(rows)
            self.assertEqual(rows[1:],unchanged)
            self.assertEqual([p['text'] for p in rows[0]['provenance'][:2]],['Uncooperative','TEST Emissary'])
            self.assertEqual(len(rows[0]['provenance']),4)
            o=dict(width=640,height=480,sha256='a'*64,lines=rows)
            d=classify_dialog(o,game_text=SOURCE)
            self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EMISSARY')
            self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
            self.assertEqual(len(d['options']),2)
            self.assertFalse(classify_dialog(o,game_text=SOURCE.replace('grant an audience','give you gold'))['supported'])

    def test_crop_disagreement_changed_words_confidence_or_geometry_reject(self):
        for case in ('disagree','changed_words','weak','geometry'):
            rows=self.fixture();before=deepcopy(rows);a=self.fresh();b=deepcopy(a)
            if case=='disagree':b['text']='Uncooperative OTHER Emissary'
            elif case=='changed_words':a['text']=b['text']='Enthusiastic TEST Emissary'
            elif case=='weak':b['confidence']=.79
            else:b['bounds'][0]+=80;b['center'][0]+=80
            self.recover(rows,a,b)
            with self.subTest(case=case):self.assertEqual(rows,before)

    def test_missing_extra_or_changed_control_body_and_fragments_cannot_trigger(self):
        for case in ('missing_choice','extra_choice','extra_button','extra_heading','gap','body','gender'):
            rows=self.fixture()
            if case=='missing_choice':rows.pop(6)
            elif case=='extra_choice':rows.insert(7,prepared('"Give us gold."',194,290,200,14))
            elif case=='extra_button':rows.append(prepared('Cancel',400,308,40,14))
            elif case=='extra_heading':rows.append(prepared('Other',420,160,40,14))
            elif case=='gap':rows[1]['bounds'][0]+=20;rows[1]['center'][0]+=20
            elif case=='body':rows[3]['text']='wishes to threaten you. Will you receive'
            else:rows[4]['text']='her?'
            before=deepcopy(rows);crop=self.recover(rows)
            with self.subTest(case=case):
                crop.assert_not_called();self.assertEqual(rows,before)

    def test_actual_sioux_audience_preserves_observed_spelling_and_two_choices(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-012/screens/ui-0001773.png'
        if not p.exists() or not (root/'.runtime/ocr').exists():self.skipTest('Private original audience unavailable')
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EMISSARY')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text'] for r in d['options']],['"Yes. I will grant an audience."','O "No. Send him away."'])
        title=next(r for r in o['lines'] if r['text']=='Uncooperative Siouz Emissary')
        self.assertEqual([r['text'] for r in title['provenance'][:2]],['Uncooperative','Siouz Emissary'])
        self.assertEqual([r['scale'] for r in title['provenance'][2:]],[4,4])


if __name__=='__main__':unittest.main()
