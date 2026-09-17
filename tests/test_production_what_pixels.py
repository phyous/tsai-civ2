"""A damaged initial What is recovered from pixels, without renaming its city."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class ProductionWhatPixels(unittest.TestCase):
    def test_wider_pair_only_repairs_initial_word_with_unchanged_measured_verb_and_city(self):
        original=prepared('Whait shall me bodd in TEST City?',200,78,240,16)
        fresh=prepared('What shall me bodd in TEST City?',200,78,240,16)
        controls=[prepared(t,x,390,30,16) for t,x in [('Auto',155),('Help',305),('OK',455)]]
        for case in ('valid','disagree','city','verb','position','controls'):
            rows=[deepcopy(original),*deepcopy(controls)]
            if case=='controls':rows.pop()
            def crop(image,row,name,*args,**kwargs):
                if kwargs.get('padding')!=(8,6):return []
                value=deepcopy(fresh)
                if case=='disagree' and kwargs.get('grayscale'):value['text']=original['text']
                if case=='city':value['text']=value['text'].replace('TEST City','TEST Citz')
                if case=='verb':value['text']=value['text'].replace('bodd','purchase')
                if case=='position':value['center'][1]+=40;value['bounds'][1]+=40
                return [value]
            with patch.object(observe,'_crop_text',side_effect=crop),patch.object(observe,'_production_names',return_value=set()):
                observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],fresh['text'] if case=='valid' else original['text'],case)
            if case=='valid':
                self.assertEqual(rows[0]['provenance'][0]['text'],original['text'])
                self.assertNotIn('production_title_identity_consensus',rows[0])

    def test_private_neapolis_frame_retains_all_sixteen_choices(self):
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-011/screens/ui-0001823.png'
        if not path.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original frame unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        before=path.read_bytes();o=observe.recognize(path)
        d=classify_dialog(o,state={'cities':[],'observed_city_names':['Neapolis']},
            rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_choice')
        self.assertEqual(d['observed_city_name'],'Neapolis')
        self.assertEqual([v['text'] for v in d['options']],['Settlers','Warriors','Phalanx','Archers','Legion',
            'Trireme','Diplomat','Barracks','Granary','Temple','MarketPlace','Library','Courthouse',
            'Hanging Gardens','Colossus','Lighthouse'])
        row=next(r for r in o['lines'] if r['text'].startswith('What shall'))
        self.assertEqual(row['provenance'][0]['text'],'Whait shall me bodd in Neapolis?')
        self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
