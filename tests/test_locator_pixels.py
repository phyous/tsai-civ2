"""Synthetic TEST paired title/name OCR; optional private originals."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.dialogs import classify_dialog
from tests.test_herald import prepared

class LocatorPixels(unittest.TestCase):
    def test_caption_date_requires_agreement_across_two_scales(self):
        original=prepared('City of TEST Rome, 3000 B.C.',120,40,400,16)
        wrong=prepared('City of TEST Rome, 3200 B.C.',120,40,400,16)
        correct=prepared('City of TEST Rome, 3800 B.C.',120,40,400,16)
        rows=[original]
        with patch.object(observe,'_crop_text',side_effect=[[wrong],[wrong],[correct],[correct],[correct],[correct]]):
            observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
        self.assertIn('3800 B.C.',rows[0]['text'])
        self.assertEqual(rows[0]['caption_identity_consensus']['independent_scales'],2)
    def test_optional_original_city_years_are_read_from_pixels(self):
        root=Path(__file__).resolve().parents[1]
        cases=[(68,'3950','3950'),(91,'3900','3900')]
        if not all((root/f'runs/attempt-007/screens/ui-{n:07}.png').exists() for n,_,_ in cases) or not(root/'.runtime/ocr').exists():self.skipTest('Private city-year frames unavailable')
        for n,current,raw in cases:
            o=observe.recognize(root/f'runs/attempt-007/screens/ui-{n:07}.png')
            r=next(x for x in o['lines'] if x['text'].startswith('City of Rome'))
            self.assertIn(current+' B.C.',r['text'])
            self.assertIn(raw+' B.C.',r['provenance'][0]['text'])
            self.assertTrue({'city_caption_2x','city_caption_gray_2x'}<={p['preprocessing'] for p in r['provenance']})
    def test_moving_status_masks_must_both_read_exact_phrase(self):
        original=prepared('Morng Uhits',514,252,72,15)
        good=prepared('Moving Units',515,250,72,17)
        for peer,accepted in ((good,True),(prepared('Moving Units?',515,250,72,17),False)):
            rows=[copy.deepcopy(original)]
            with patch.object(observe,'_crop_text',side_effect=[[],[],[good],[peer]]):
                observe._recover_moving_status(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'Moving Units' if accepted else 'Morng Uhits')

    def test_optional_original_warrior_status(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-007/screens/ui-0000327.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original Warrior status unavailable')
        o=observe.recognize(p);r=next(x for x in o['lines'] if x['text']=='Moving Units')
        self.assertEqual(r['provenance'][0]['text'],'Morng Uhits')
        self.assertTrue({'moving_status_white190_3x','moving_status_white230_3x'}<={x['preprocessing'] for x in r['provenance']})
    def test_lower_scale_title_still_requires_same_city_and_paired_pixels(self):
        original=prepared('What shall me bood in Antiom?',226,96,188,16)
        wrong=prepared('What shall me boikd in Antion?',226,96,188,16)
        good=prepared('What shall me boikd in Antiom?',226,96,188,16)
        for peer,accepted in ((good,True),(wrong,False)):
            rows=[copy.deepcopy(original),prepared('Auto',150,368,30,16),prepared('Help',300,368,30,16),prepared('OK',465,368,24,16)]
            with patch.object(observe,'_crop_text',side_effect=[[wrong],[wrong],[good],[peer]]),patch.object(observe,'_production_names',return_value={}):
                observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],good['text'] if accepted else original['text'])
    def test_locator_recovery_requires_independent_agreement_and_controls(self):
        name=prepared('Anium',142,138,48,12);correct=prepared('Antium',143,138,46,13)
        base=[prepared('Where in the heck is . . .',246,78,138,16),name,
              prepared('Zoom To City',152,386,88,17),prepared('Cancel',424,386,42,15),prepared('OK',308,387,24,13)]
        for case in ('good','different','weak','no_controls'):
            rows=copy.deepcopy(base);second=copy.deepcopy(correct)
            if case=='different':second['text']='TEST unknown'
            if case=='weak':second['confidence']=.5
            if case=='no_controls':rows.pop(2)
            with patch.object(observe,'_crop_text',side_effect=[[correct],[second]]):
                observe._recover_locator_names(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[1]['text'],'Antium' if case=='good' else 'Anium')
            if case=='good':self.assertEqual(rows[1]['provenance'][0]['text'],'Anium')
    def test_domestic_title_pixels_do_not_authorize_partial_body(self):
        raw=prepared('Domestic Adrisor',266,184,112,14);exact=prepared('Domestic Advisor',266,184,112,14)
        rows=[raw,prepared('TEST incomplete population notice',146,226,280,16),prepared('OK',309,282,24,13)]
        with patch.object(observe,'_crop_text',side_effect=[[exact],[exact]]):
            observe._recover_domestic_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
        self.assertEqual(rows[0]['text'],'Domestic Advisor')
        self.assertFalse(classify_dialog(dict(width=640,height=480,sha256='a'*64,lines=rows),game_text='')['supported'])
    def test_optional_original_selected_city_and_population_notice(self):
        root=Path(__file__).resolve().parents[1]
        locator=root/'runs/attempt-005/screens/ui-0001296.png';notice=root/'runs/attempt-004/screens/ui-0000834.png'
        save=root/'runs/attempt-005/saves/d000087.sav'
        if not all(p.exists() for p in (locator,notice,save)) or not(root/'.runtime/ocr').exists():self.skipTest('Private original frames unavailable')
        from civ2.run import game_text
        from civ2.boot import original_rules
        from civ2.save import parse_save
        state=parse_save(save.read_bytes(),rules_text=original_rules())
        o=observe.recognize(locator);r=classify_dialog(o,state=state)
        self.assertEqual(r['kind'],'city_locator',r);self.assertTrue(r['supported'])
        n=next(x for x in o['lines'] if x['text']=='Antium')
        self.assertEqual(n['provenance'][0]['text'],'Anium')
        r=classify_dialog(observe.recognize(notice),game_text=game_text())
        self.assertEqual(r['resource_tag'],'FERTILE');self.assertEqual(r['mechanical_action'],'acknowledge_information')

    def test_optional_original_dense_production_menu_keeps_all_13_choices(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-005/screens/ui-0001329.png';save=root/'runs/attempt-005/saves/d000088.sav'
        if not p.exists() or not save.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original dense production menu unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_save,parse_rules
        o=observe.recognize(p);r=classify_dialog(o,state=parse_save(save.read_bytes(),rules_text=original_rules()),rules=parse_rules(original_rules()))
        self.assertEqual(r['kind'],'production_choice',r);self.assertTrue(r['requires_model'])
        self.assertEqual(len(r['options']),13);self.assertEqual(r['options'][0]['text'],'Settlers')
        self.assertEqual(r['options'][-1]['text'],"Marco Polo's Embassy")
        title=next(x for x in o['lines'] if x['text'].startswith('What shall'))
        self.assertEqual(title['text'],'What shall me boikd in Antiom?')
        self.assertEqual(title['provenance'][0]['text'],'What shall me bood in Antiom?')

if __name__=='__main__':unittest.main()
