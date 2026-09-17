"""Synthetic TEST city-title correction requires two distinct OCR scales."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class ProductionCityPixels(unittest.TestCase):
    def test_one_pair_or_different_city_cannot_change_suffix(self):
        old=prepared('What shall we bodkd in TEST Antion?',190,130,260,16)
        good=prepared('What shall me bukd in TEST Antiom?',190,130,260,16)
        controls=[prepared('Auto',130,330,30,16),prepared('Help',310,330,30,16),prepared('OK',470,330,20,16)]
        for case in ('valid','one_pair','different_city','disagreement'):
            rows=[deepcopy(old),*deepcopy(controls)];peer=deepcopy(good)
            if case=='different_city':peer['text']=peer['text'].replace('Antiom','Rome')
            if case=='disagreement':peer['text']=peer['text'].replace('Antiom','Antios')
            second=[] if case=='one_pair' else [peer]
            with patch.object(observe,'_crop_text',side_effect=[[good],[good],second,second,[],[]]),patch.object(observe,'_production_names',return_value=set()):
                observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],good['text'] if case=='valid' else old['text'],case)
            if case=='valid':self.assertEqual(rows[0]['production_title_identity_consensus']['independent_scales'],2)

    def test_optional_original_010_all_production_choices_remain_observed(self):
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-010/screens/ui-0000363.png'
        if not path.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original production frame unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        before=path.read_bytes();o=observe.recognize(path)
        d=classify_dialog(o,rules=parse_rules(original_rules()),state={'cities':[],'observed_city_names':['Antium']})
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_choice')
        self.assertEqual(len(d['options']),9)
        self.assertEqual({x['text'] for x in d['options']},{'Settlers','Warriors','Phalanx','Diplomat','Barracks','Library','Courthouse','Colossus','Great Library'})
        row=next(r for r in o['lines'] if r['text'].startswith('What shall me bukd'))
        self.assertEqual(row['provenance'][0]['text'],'What shall we bodkd in Antion?')
        self.assertEqual(row['production_title_identity_consensus']['city_text'],'Antiom')
        self.assertEqual(path.read_bytes(),before)

    def test_later_native_city_read_does_not_claim_suffix_consensus(self):
        old=prepared('What shall we bodkd in TEST Antion?',190,130,260,16)
        alternate=prepared('What shall me bukd in TEST Antiom?',190,130,260,16)
        native=prepared('What shall me bukd in TEST Antion?',190,130,260,16)
        rows=[old,prepared('Auto',130,330,30,16),prepared('Help',310,330,30,16),prepared('OK',470,330,20,16)]
        with patch.object(observe,'_crop_text',side_effect=[[alternate],[alternate],[native],[native]]),patch.object(observe,'_production_names',return_value=set()):
            observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
        self.assertEqual(rows[0]['text'],native['text'])
        self.assertNotIn('production_title_identity_consensus',rows[0])


if __name__=='__main__':unittest.main()
