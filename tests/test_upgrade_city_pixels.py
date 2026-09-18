from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared

class UpgradeCityPixels(unittest.TestCase):
    def test_city_change_requires_two_scales_and_unchanged_full_original_template(self):
        base=[prepared('Domestic Advisor',260,168,120,16),
            prepared('Production orders in TESTI upgraded from',230,192,294,16),
            prepared('Warriors to Pikemen.',230,212,150,16),
            prepared('Zoom to City',266,238,85,16),prepared('Continue',266,262,70,16),prepared('OK',310,298,24,16)]
        for case in ('valid','one_scale','different_city','wrong_verb','disagree','choice'):
            rows=deepcopy(base)
            if case=='choice':rows.pop(3)
            def crop(*args,**kwargs):
                if case=='one_scale' and kwargs['scale']==2:return []
                text='Production orders in TEST upgraded from'
                if case=='different_city':text=text.replace('TEST','ELSE')
                if case=='wrong_verb':text=text.replace('upgraded','downgraded')
                if case=='disagree' and kwargs.get('grayscale'):text=text.replace('TEST','TESTI')
                return [prepared(text,230,192,294,16)]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_production_upgrade_city(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[1]['text'],base[1]['text'])
            self.assertEqual('production_upgrade_city_reading' in rows[1],case=='valid')
            if case=='valid':self.assertEqual(rows[1]['production_upgrade_city_reading']['text'],'Production orders in TEST upgraded from')
            self.assertEqual(rows[1]['provenance'][0]['text'],base[1]['text'])

    def test_upgrade_boundary_repairs_are_atomic_and_preserve_unit_names(self):
        base=[prepared('Domestic Advisor',260,168,120,16),
            prepared('Production orders in TEST upgraded from',230,192,294,16),
            prepared('Warriors to Pikemen,',230,212,150,16),
            prepared('©) Zoom to City',238,238,114,16),prepared('O Continue',238,262,96,16),prepared('OK',310,298,24,16)]
        for case in ('valid','unit','radio','weak','extra'):
            rows=deepcopy(base)
            if case=='extra':rows.append(prepared('Pay gold',238,283,100,12))
            def crop(image,row,name,*args,**kwargs):
                text='Warriors to Pikemen.' if 'tail' in name else ('Continue' if 'continue' in name else 'Zoom to City')
                if case=='unit' and 'tail' in name:text='Warriors to Knights.'
                if case=='radio' and kwargs.get('grayscale') and 'zoom' in name:text='No'
                r=prepared(text,230 if 'tail' in name else 262,212 if 'tail' in name else (262 if 'continue' in name else 238),150 if 'tail' in name else 91,16)
                if case=='weak':r['confidence']=.5
                return [r]
            conflict={'text':'Continue','bounds':[261,264,65,12],'reason':'contradictory overlapping native text'}
            unrelated={'text':'No','bounds':[270,244,30,12],'reason':'contradictory overlapping native text'}
            evidence={'conflicts':[deepcopy(conflict),deepcopy(unrelated)]}
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_upgrade_boundaries(Image.new('RGB',(640,480)),rows,None,None,evidence)
            self.assertIn(unrelated,evidence['conflicts'])
            if case=='valid':
                self.assertNotIn(conflict,evidence['conflicts'])
                self.assertEqual(evidence['resolved_control_conflicts'],[conflict])
            else:self.assertIn(conflict,evidence['conflicts'])
            self.assertEqual(rows[2]['text'],'Warriors to Pikemen.' if case=='valid' else base[2]['text'])
            self.assertEqual(rows[3]['text'],'Zoom to City' if case=='valid' else base[3]['text'])

    def test_actual_antium_upgrade_keeps_both_real_choices(self):
        p=Path('runs/attempt-010/screens/ui-0002830.png')
        if not p.exists():self.skipTest('Private original calibration unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        o=observe.recognize(p)
        d=classify_dialog(o,game_text=game_text(),labels_text=labels_text(),rules=parse_rules(original_rules()),
            state={'player':{'id':1},'cities':[{'name':'Antium','owner':1}]})
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_upgrade_notice')
        self.assertEqual([r['text'] for r in d['options']],['Zoom to City','Continue'])
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        tail=next(r for r in o['lines'] if r['text']=='Warriors to Pikemen.')
        self.assertEqual(tail['provenance'][0]['text'],'Warriors to Pikemen,')
        zoom=next(r for r in o['lines'] if r['text']=='Zoom to City')
        self.assertEqual(zoom['provenance'][0]['text'],'©) Zoom to City')

    def test_actual_pompeii_notice_requires_model_for_both_options(self):
        p=Path('runs/attempt-010/screens/ui-0002813.png')
        if not p.exists():self.skipTest('Private original calibration unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        o=observe.recognize(p)
        d=classify_dialog(o,game_text=game_text(),labels_text=labels_text(),rules=parse_rules(original_rules()),
            state={'player':{'id':1},'cities':[{'name':'Pompeii','owner':1}]})
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_upgrade_notice')
        self.assertEqual([r['text'] for r in d['options']],['Zoom to City','Continue'])
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        r=next(r for r in o['lines'] if r['text'].startswith('Production orders'))
        self.assertEqual(r['text'],'Production orders in Pompei upgraded from')
        self.assertEqual(r['production_upgrade_city_reading']['text'],'Production orders in Pompeii upgraded from')
        self.assertEqual(r['provenance'][0]['text'],'Production orders in Pompei upgraded from')
        self.assertEqual([p['scale'] for p in r['production_upgrade_city_reading']['readings']],[3,3,2,2])

    def test_original_correct_ravenna_survives_wrong_agreeing_crop_readings(self):
        p=Path('runs/attempt-010/screens/ui-0002863.png')
        if not p.exists():self.skipTest('Private original calibration unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        o=observe.recognize(p)
        d=classify_dialog(o,game_text=game_text(),labels_text=labels_text(),rules=parse_rules(original_rules()),
            state={'player':{'id':1},'cities':[{'name':'Ravenna','owner':1}]})
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_upgrade_notice')
        r=next(r for r in o['lines'] if r['text'].startswith('Production orders'))
        self.assertEqual(r['text'],'Production orders in Ravenna upgraded from')
        self.assertEqual(r['production_upgrade_city_reading']['text'],'Production orders in Raverna upgraded from')
        self.assertEqual(d['evidence']['city_name'],'Ravenna')

if __name__=='__main__':unittest.main()
