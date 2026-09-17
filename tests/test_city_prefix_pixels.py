"""Synthetic TEST caption evidence; optional retained original pixels."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class CityPrefixPixels(unittest.TestCase):
    def test_fallback_still_requires_distinct_scales_and_unchanged_identity(self):
        original=prepared('Cicy of TEST Vei, 3450 B.C.',128,40,386,16)
        good=prepared('City of TEST Vei, 3450 B.C.',128,40,386,16)
        for case in ('valid','single_scale','different_name','different_date'):
            final=copy.deepcopy(good)
            if case=='different_name':final['text']=final['text'].replace('Vei','Rome')
            if case=='different_date':final['text']=final['text'].replace('3450','3400')
            rows=[copy.deepcopy(original)]
            readings=[[],[],[],[],[good],[good],[good],[good]]
            readings += [[],[],[],[]] if case=='single_scale' else [[final],[final],[],[]]
            with patch.object(observe,'_crop_text',side_effect=readings):
                observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],good['text'] if case=='valid' else original['text'],case)
            if case=='valid':self.assertEqual(rows[0]['caption_identity_consensus']['independent_scales'],2)

    def test_optional_original_010_city_caption_preserves_date_and_raw_text(self):
        root=Path(__file__).resolve().parents[1]
        path=root/'runs/attempt-010/screens/ui-0000172.png'
        if not path.exists() or not(root/'.runtime/ocr').exists():
            self.skipTest('Private original city frame unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import observed_city_identity
        image=path.read_bytes();o=observe.recognize(path)
        d=classify_dialog(o,state={'player':{'id':1},'cities':[{'id':5,'owner':1,'name':'Veii','x':56,'y':8}],
                                   'evidence':{'kind':'live_memory','observation_sha256':'a'*64}})
        self.assertEqual(observed_city_identity(d),('Veii','3450BC'))
        row=next(r for r in o['lines'] if r['text'].startswith('City of Vei,'))
        self.assertTrue(row['provenance'][0]['text'].startswith('Cicy of Vei,'))
        self.assertEqual(row['caption_identity_consensus']['independent_scales'],2)
        self.assertTrue({2,4}<={p.get('scale') for p in row['provenance']})
        self.assertEqual(path.read_bytes(),image)


if __name__=='__main__':unittest.main()
