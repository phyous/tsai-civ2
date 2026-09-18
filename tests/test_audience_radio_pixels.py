"""Synthetic TEST audience crop agreement and optional original image."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class AudienceRadioPixels(unittest.TestCase):
    def test_radio_apostrophe_only_locates_two_complete_fourfold_reads(self):
        for case in ('valid','different','weak','extra_terms'):
            old=prepared('O "\'Yes. I will grant an audience."',170,236,238,20)
            if case=='extra_terms':old['text']='O "\'Yes. I will grant an audience and pay gold."'
            values=[prepared('Uncooperative TEST Emissary',230,167,180,16),prepared('An emissary from TEST Leader',161,193,280,16),old,
                prepared('"No. Send her away."',196,263,180,16),prepared('OK',310,307,20,16)]
            before=deepcopy(values);a=prepared('"Yes. I will grant an audience."',196,240,208,16);b=deepcopy(a)
            if case=='different':b['text']='"Yes. I will grant an audience!"'
            if case=='weak':b['confidence']=.5
            with patch.object(observe,'_crop_text',side_effect=[[a],[b]]) as crop:
                observe._recover_audience_radio(Image.new('RGB',(640,480)),values,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(values[2]['text'],a['text']);self.assertEqual([c.kwargs['scale']for c in crop.call_args_list],[4,4])
            else:self.assertEqual(values,before,case)

    def test_actual_0113418_keeps_both_model_choices(self):
        p=Path('runs/attempt-011/screens/ui-0003418.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EMISSARY')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text']for r in d['options']],['"Yes. I will grant an audience."','• "No. Send her away."'])
        row=next(r for r in o['lines']if r['text']=='"Yes. I will grant an audience."')
        self.assertEqual(row['provenance'][0]['text'],'O "\'Yes. I will grant an audience."')
        self.assertEqual([p['scale']for p in row['provenance'][-2:]],[4,4])

    def test_exact_pair_and_complete_context_required(self):
        old=prepared('(\"Yes. I will grant an audience.\"',190,246,218,20)
        fresh=prepared('\"Yes. I will grant an audience.\"',194,246,215,21)
        for case in ('valid','disagreement','missing_body','extra_button','wrong_geometry','different_terms'):
            rows=[prepared('Cordial TEST Emissary',230,157,180,16),
                  prepared('An emissary from TEST Leader',161,183,280,16),deepcopy(old),
                  prepared('• \"No. Send him away.\"',196,273,180,16),prepared('OK',310,307,20,16)]
            second=deepcopy(fresh)
            if case=='disagreement':second['text']='\"Yes. I will grant an audience!\"'
            elif case=='missing_body':rows.pop(1)
            elif case=='extra_button':rows.append(prepared('Cancel',400,307,40,16))
            elif case=='wrong_geometry':second.update(bounds=[20,80,215,21],center=[127,90])
            elif case=='different_terms':rows[2]['text']='(\"Yes. Give TEST gold.\"'
            before=deepcopy(rows)
            with patch.object(observe,'_crop_text',side_effect=[[deepcopy(fresh)],[second]]) as crop:
                observe._recover_audience_radio(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(rows[2]['text'],fresh['text'])
                self.assertEqual(len(rows[2]['provenance']),3)
            else:self.assertEqual(rows,before)
            if case in ('missing_body','extra_button','different_terms'):crop.assert_not_called()

    def test_optional_original_010_audience_still_requires_model(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-010/screens/ui-0000479.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original audience absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EMISSARY')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text'] for r in d['options']],['\"Yes. I will grant an audience.\"','• \"No. Send him away.\"'])
        r=next(r for r in o['lines'] if r['text']=='\"Yes. I will grant an audience.\"')
        self.assertEqual(r['provenance'][0]['text'],'(\"Yes. I will grant an audience.\"')


if __name__=='__main__':unittest.main()
