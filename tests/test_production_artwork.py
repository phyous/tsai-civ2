"""Synthetic TEST production layouts; optional private original screenshot."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.dialogs import classify_dialog
from tests.test_herald import prepared


class ProductionArtworkTests(unittest.TestCase):
    def test_damaged_first_word_requires_two_actual_title_reads(self):
        original=prepared('Whait shall me bood in TEST?',226,96,188,16)
        good=prepared('What shall me buokd in TEST?',226,96,188,16)
        for peer,accepted in ((good,True),(prepared('What shall me buokd in ELSE?',226,96,188,16),False)):
            rows=[copy.deepcopy(original),prepared('Auto',150,370,30,16),
                  prepared('Help',300,370,30,16),prepared('OK',465,370,24,16)]
            with patch.object(observe,'_crop_text',side_effect=[[good],[peer],[good],[peer],[good],[peer]]):
                observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],good['text'] if accepted else original['text'])

    def test_colored_icon_cannot_supply_or_hide_a_choice(self):
        rows=[prepared('What shall we build in TEST City?',220,90,220,16),
              prepared('Warriors',180,126,60,16),prepared('(10 Turns)',340,126,90,16),
              prepared('Settlers',180,146,60,16),prepared('(40 Turns)',340,146,90,16),
              prepared('artglyph',126,146,30,10),prepared('Auto',150,370,30,16),
              prepared('Help',300,370,30,16),prepared('OK',465,370,24,16)]
        icon=rows[5];icon['confidence']=.3
        icon['map_patch_colors']={'source_sha256':'a'*64,'bounds':icon['bounds'],
            'rgb_spread_threshold':24,'pixel_count':300,'chromatic_pixels':170}
        base={'width':640,'height':480,'sha256':'a'*64,'lines':rows}
        rules={'units':[{'name':'Warriors'},{'name':'Settlers'}],'improvements':[]}
        for case in ('valid','wrong_hash','gray','strong_text','missing_stat','option_word','over_label'):
            o=copy.deepcopy(base);r=o['lines'][5]
            if case=='wrong_hash':r['map_patch_colors']['source_sha256']='b'*64
            if case=='gray':r['map_patch_colors']['chromatic_pixels']=0
            if case=='strong_text':r['confidence']=.9
            if case=='missing_stat':o['lines'].pop(4)
            if case=='option_word':r['text']='Cancel'
            if case=='over_label':
                r['bounds'][0]=180;r['center'][0]=195
            result=classify_dialog(o,rules=rules)
            self.assertEqual(result['supported'],case=='valid',(case,result))
            if case=='valid':
                self.assertEqual([x['text'] for x in result['options']],['Warriors','Settlers'])
                self.assertEqual(result['evidence']['production_artwork'][0]['text'],'artglyph')

    def test_optional_original_cumae_menu_retains_all_thirteen_choices(self):
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-005/screens/ui-0001457.png'
        if not path.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original production frame unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        state={'cities':[{'name':'Cumae'},{'name':'Curae'}], 'recent_founding_notices':[
            {'name':'Cumae','year_text':'1150 b.c','source_tag':'FOUNDED','image_sha256':'a'*64}]}
        o=observe.recognize(path);rules=parse_rules(original_rules())
        result=classify_dialog(o,state=state,rules=rules)
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['observed_city_name'],'Cumae')
        self.assertEqual(len(result['options']),13)
        self.assertEqual(result['options'][-1]['text'],"Marco Polo's Embassy")
        self.assertEqual(result['evidence']['production_artwork'][0]['text'],'mlinimu')
        title=next(r for r in o['lines'] if r['text'].startswith('What shall'))
        self.assertEqual(title['provenance'][0]['text'],'Whait shall me bood in Comae?')
        state['cities'].append({'name':'Comae'})
        self.assertFalse(classify_dialog(o,state=state,rules=rules)['supported'])

    def test_optional_original_pompeii_menu_preserves_fourteen_choices(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-005/screens/ui-0001860.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original Pompeii menu unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        # Pompei is the retained original founding-notice reading, not a
        # replacement inferred from an unseen city record.
        o=observe.recognize(p);d=classify_dialog(o,state={'cities':[{'name':'Pompei'}]},rules=parse_rules(original_rules()))
        self.assertTrue(d['supported'],d);self.assertEqual(len(d['options']),14)
        self.assertEqual(d['title'],'What shall me bold in Pompeu?')
        self.assertEqual(d['options'][3]['text'],'Horsemen')
        self.assertEqual(d['options'][-1]['text'],"Marco Polo's Embassy")
        r=next(r for r in o['lines'] if r['text']==d['title'])
        self.assertEqual(r['provenance'][0]['text'],'Whait shall me boold in Pompeu?')


if __name__=='__main__':unittest.main()
