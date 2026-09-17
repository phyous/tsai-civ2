"""TEST suffix consensus remains conditional on independent founding evidence."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class FoundedProductionPixels(unittest.TestCase):
    def test_secondary_read_corroborates_suffix_but_does_not_supply_verb(self):
        old=prepared('What shall me bokl in TEST Cumse?',200,78,250,18)
        first=prepared('What shall me bold in TEST Comae?',200,78,250,18)
        second=prepared('What shall me bookd in TEST Comae?',200,78,250,18)
        for case in ('valid','different_city','changed_words','missing_caption'):
            rows=[deepcopy(old),prepared('Cisy of TEST Cumne, 2150 B.C., Population TEST',100,38,430,18),
                  prepared('Auto',130,388,30,16),prepared('Help',310,388,30,16),prepared('OK',470,388,20,16)]
            a=deepcopy(first);b=deepcopy(second)
            if case=='different_city':b['text']=b['text'].replace('Comae','Comoe')
            elif case=='changed_words':a['text']=a['text'].replace('bold','sell')
            elif case=='missing_caption':rows.pop(1)
            original=deepcopy(rows)
            with patch.object(observe,'_crop_text',side_effect=[[deepcopy(a)],[deepcopy(a)],[deepcopy(b)],[deepcopy(b)]]) as crop:
                observe._recover_founded_production_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(rows[0]['text'],first['text'])
                self.assertTrue(rows[0]['production_title_identity_consensus']['requires_founding_notice'])
                self.assertEqual(rows[0]['production_title_identity_consensus']['observed_year'],'2150 B.C.')
                self.assertEqual(len(rows[0]['provenance']),5)
            else:self.assertEqual(rows,original)
            if case=='missing_caption':crop.assert_not_called()

    def test_optional_original_010_requires_unique_same_year_founding(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-010/screens/ui-0000786.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original production absent')
        from civ2.dialogs import classify_dialog
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        o=observe.recognize(p);rules=parse_rules(original_rules())
        notice={'name':'Cumae','year_text':'2150 b.c','source_tag':'FOUNDED','image_sha256':'a'*64}
        state={'cities':[],'observed_city_names':['Cumae'],'recent_founding_notices':[notice]}
        for case in ('valid','different_city','wrong_year','ambiguous','missing'):
            current=deepcopy(state)
            if case=='different_city':current['recent_founding_notices'][0]['name']='Veii'
            elif case=='wrong_year':current['recent_founding_notices'][0]['year_text']='2200 b.c'
            elif case=='ambiguous':current['recent_founding_notices'].append({**notice,'name':'Comae','image_sha256':'b'*64})
            elif case=='missing':current['recent_founding_notices']=[]
            d=classify_dialog(o,rules=rules,state=current)
            self.assertEqual(d['supported'],case=='valid',case)
            if case=='valid':
                self.assertEqual(d['kind'],'production_choice');self.assertEqual(len(d['options']),16)
                self.assertEqual(d['observed_city_name'],'Cumae');self.assertTrue(d['requires_model'])
        title=next(r for r in o['lines'] if 'shall' in r['text'])
        self.assertEqual(title['text'],'What shall me bold in Comae?')
        self.assertEqual(title['provenance'][0]['text'],'What shall me bokl in Cumse?')
