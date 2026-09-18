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
            with patch.object(observe,'_crop_text',side_effect=[[good],[peer]]*4):
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

    def test_vertical_icon_column_requires_three_complete_rows_and_pixel_binding(self):
        names=('Warriors','Settlers','Phalanx','Horsemen')
        rows=[prepared('What shall we build in TEST City?',220,80,220,14)]
        for i,name in enumerate(names):
            rows += [prepared(name,180,110+i*17,70,14),prepared('(10 Turns)',340,110+i*17,90,14)]
        icon=prepared('1g- Frt',117,110,16,72);icon['confidence']=.3
        icon['map_patch_colors']={'source_sha256':'a'*64,'bounds':list(icon['bounds']),
            'rgb_spread_threshold':24,'pixel_count':1152,'chromatic_pixels':269}
        rows += [icon,prepared('Auto',150,370,30,16),prepared('Help',300,370,30,16),prepared('OK',465,370,24,16)]
        base={'width':640,'height':480,'sha256':'a'*64,'lines':rows}
        rules={'units':[{'name':name} for name in names],'improvements':[]}
        for case in ('valid','unhashed','gray','strong_text','control','missing_stat','over_label','few_rows'):
            o=copy.deepcopy(base);art=o['lines'][9]
            if case=='unhashed':art['map_patch_colors']['source_sha256']='b'*64
            if case=='gray':art['map_patch_colors']['chromatic_pixels']=0
            if case=='strong_text':art['confidence']=.8
            if case=='control':art['text']='No - Frt'
            if case=='missing_stat':o['lines'].pop(6)
            if case=='over_label':o['lines'][1]['bounds'][0]=150;o['lines'][1]['center'][0]=185
            if case=='few_rows':
                for i in (7,5):del o['lines'][i:i+2]
            d=classify_dialog(o,rules=rules)
            self.assertEqual(d['supported'],case=='valid',(case,d))
            if case=='valid':self.assertEqual([r['text'] for r in d['options']],list(names))

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

    def test_tall_icon_column_needs_six_to_eight_complete_spaced_rows(self):
        names=('Settlers','Archers','Legion','Pikemen','Horsemen','Elephant','Diplomat')
        rows=[prepared('What shall we build in TEST City?',220,80,220,14)]
        for i,name in enumerate(names):
            rows += [prepared(name,180,102+i*17,70,14),prepared('(10 Turns)',340,102+i*17,90,14)]
        icon=prepared('A PE BNLA',115,101,21,125);icon['confidence']=.3
        icon['map_patch_colors']={'source_sha256':'a'*64,'bounds':list(icon['bounds']),
            'rgb_spread_threshold':24,'pixel_count':2625,'chromatic_pixels':563}
        rows += [icon,prepared('Auto',150,390,30,16),prepared('Help',300,390,30,16),prepared('OK',465,390,24,16)]
        base={'width':640,'height':480,'sha256':'a'*64,'lines':rows};rules={'units':[{'name':n} for n in names],'improvements':[]}
        for case in ('valid','gap','missing_stat','few_rows','color','hash','control','long'):
            o=copy.deepcopy(base);art=o['lines'][15]
            if case=='gap':del o['lines'][7:9]
            if case=='missing_stat':o['lines'].pop(8)
            if case=='few_rows':del o['lines'][9:15]
            if case=='color':art['map_patch_colors']['chromatic_pixels']=0
            if case=='hash':art['map_patch_colors']['source_sha256']='b'*64
            if case=='control':art['text']='No PE BNLA'
            if case=='long':art['bounds'][3]=140;art['map_patch_colors'].update(bounds=list(art['bounds']),pixel_count=2940,chromatic_pixels=700)
            d=classify_dialog(o,rules=rules)
            self.assertEqual(d['supported'],case=='valid',(case,d))
            if case=='valid':self.assertEqual([r['text'] for r in d['options']],list(names))

    def test_actual_pisae_keeps_all_sixteen_options_and_source_art(self):
        path=Path('runs/attempt-011/screens/ui-0002562.png')
        if not path.exists():self.skipTest('Private original Pisae production frame unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.run import game_text,labels_text
        state={'cities':[{'name':'Pisae'}],'recent_founding_notices':[dict(name='Pisae',year_text='A.D. 40',source_tag='FOUNDED',
               image_sha256='8356fa9f7d9fe9082e29c7b2dcaafac04129f1fbfc9b69daa072423eb242c05d')]}
        original=path.read_bytes();o=observe.recognize(path)
        d=classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model']);self.assertEqual(len(d['options']),16)
        self.assertEqual(d['options'][0]['text'],'Settlers');self.assertEqual(d['options'][-1]['text'],'Colossus')
        self.assertEqual(d['evidence']['production_artwork'][0]['text'],'A PE BNLA')
        self.assertEqual(path.read_bytes(),original)

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
