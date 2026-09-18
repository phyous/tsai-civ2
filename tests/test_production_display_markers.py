from copy import deepcopy
from pathlib import Path
import unittest
from civ2 import observe
from civ2.dialogs import classify_dialog,_production_stat
from tests.test_herald import prepared


class ProductionDisplayMarkers(unittest.TestCase):
    def test_damaged_first_word_is_only_a_bounded_pixel_locator(self):
        for first in ('What','Whait','Whkat','Sohat'):
            self.assertIsNotNone(observe._production_heading_read_locator(first+' shall te bold in TEST?'))
        for text in ('No shall te bold in TEST?','Cancel shall te bold in TEST?',
                     'What will te bold in TEST?','What shall cancel bold in TEST?'):
            self.assertIsNone(observe._production_heading_read_locator(text))

    def test_display_suffix_never_changes_numeric_values_or_supplies_meaning(self):
        for marker in ('*','%'):
            raw=f'(20 Tums, ADM: 1/2{marker}/1 HP: 1/1),'
            self.assertEqual(observe._stat_reading(raw),raw)
            self.assertTrue(_production_stat(raw.casefold()))
            self.assertFalse(observe._stat_numbers_compatible(raw,'(20 Turns, ADM: 1/2/1 HP: 1/1)'))
        for raw in ('(20 Turns, ADM: 1%/2/1 HP: 1/1)',
                    '(20 Turns, ADM: 1/2/1% HP: 1/1)',
                    '(20 Turns, ADM: 1/2%%/1 HP: 1/1)',
                    '(20 Turns, ADM: 1/2%/1 HP: 1/1) Cancel'):
            self.assertIsNone(observe._stat_reading(raw));self.assertFalse(_production_stat(raw.casefold()))

    def test_unicode_vertical_art_requires_measured_color_and_complete_peer_rows(self):
        names=('Settlers','Archers','Pikemen','Horsemen')
        rows=[prepared('What shall we build in TEST City?',220,80,220,14)]
        for i,name in enumerate(names):
            stat='(20 Tums, ADM: 1/2%/1 HP: 1/1),' if name=='Pikemen' else '(20 Turns)'
            rows += [prepared(name,178,104+i*17,60,12),prepared(stat,326,104+i*17,196,14)]
        art=prepared('béN2',115,101,21,56);art['confidence']=.3
        art['map_patch_colors']={'source_sha256':'a'*64,'bounds':art['bounds'][:],
            'rgb_spread_threshold':24,'pixel_count':1176,'chromatic_pixels':228}
        rows += [art,prepared('Auto',150,390,30,16),prepared('Help',300,390,30,16),prepared('OK',465,390,24,16)]
        base={'width':640,'height':480,'sha256':'a'*64,'lines':rows}
        rs={'units':[{'name':n}for n in names],'improvements':[]}
        for case in ('valid','gray','control','placement','missing_stat'):
            o=deepcopy(base);a=o['lines'][9]
            if case=='gray':a['map_patch_colors']['chromatic_pixels']=220
            if case=='control':a['text']='Cancel'
            if case=='placement':a['bounds'][0]=170;a['center'][0]=180;a['map_patch_colors']['bounds']=a['bounds'][:]
            if case=='missing_stat':o['lines'].pop(6)
            d=classify_dialog(o,rules=rs)
            self.assertEqual(d['supported'],case=='valid',(case,d))
            if case=='valid':
                self.assertEqual([r['text']for r in d['options']],list(names))
                unresolved=d['evidence']['unresolved_displayed_stat_suffixes']
                self.assertIn('1/2%/1',unresolved['rows'][0]['raw_text'])
                from civ2.policy import dialog_request_for
                from test_policy import fixture,rules
                req,actions=dialog_request_for(fixture(),d,rules())
                self.assertEqual(req['state']['mandatory_dialog']['unresolved_displayed_stat_suffixes'],unresolved)
                self.assertEqual(len(actions),4)
                req['state']['mandatory_dialog']['unresolved_displayed_stat_suffixes']['rows'].clear()
                self.assertTrue(unresolved['rows'])

    def test_actual_lutetia_and_ravenna_keep_every_original_option(self):
        cases=[('010',3097,'Lutetia','A.D. 500','489eb41fa0c2fcc7301eb120a8344bb22648583ea663fec2ae0d2f4b65aa9b46',
            ['Settlers','Archers','Pikemen','Horsemen','Catapult','Trireme','Diplomat','Caravan','Explorer','Palace','Barracks','Granary','Temple','MarketPlace','Library','Courthouse']),
            ('011',3014,'Ravenna','A.D. 340','55730e44655afb84ef8b07f97852a8874d069e8baacde2018b0c60cf4f13c303',
            ['Settlers','Archers','Legion','Pikemen','Horsemen','Elephant','Trireme','Diplomat','Caravan','Palace','Barracks','Granary','Temple','MarketPlace','Library','Courthouse'])]
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        for attempt,number,name,year,digest,names in cases:
            with self.subTest(attempt=attempt):
                path=Path(f'runs/attempt-{attempt}/screens/ui-{number:07d}.png')
                if not path.exists():continue
                original=path.read_bytes();o=observe.recognize(path);o['path']=str(path.resolve())
                state={'cities':[{'name':name}],'recent_founding_notices':[dict(name=name,year_text=year,source_tag='FOUNDED',image_sha256=digest)]}
                d=classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
                self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model']);self.assertEqual(d['kind'],'production_choice')
                self.assertEqual([r['text']for r in d['options']],names);self.assertIsNone(d['mechanical_action'])
                self.assertEqual(path.read_bytes(),original)
                if attempt=='010':
                    raw=next(r for r in o['lines']if '1/2%' in r['text'])
                    self.assertEqual(raw['text'],raw['provenance'][0]['text'])
                    self.assertIn('unresolved_displayed_stat_suffixes',d['evidence'])
                    self.assertIn('béN2',[r['text']for r in d['evidence']['production_artwork']])
                else:self.assertIn('Ane ael 3',[r['text']for r in d['evidence']['production_artwork']])

if __name__=='__main__':unittest.main()
