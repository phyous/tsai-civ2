from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class JoinedProductionTitle(unittest.TestCase):
    def test_two_scales_preserve_city_and_read_complete_title(self):
        original=prepared('What shall me buddmn Neapous!',224,80,198,14)
        for case in ('valid','disagree','city','missing_scale','moved','low','no_control','changed_verb'):
            rows=[deepcopy(original),prepared('City of Neapolis, A.D. 40, Population 100,000',80,40,400,14),
                  *[prepared(t,x,390,30,16) for t,x in [('Auto',155),('Help',305),('OK',455)]]]
            if case=='no_control':rows.pop()
            def crop(*args,**kwargs):
                scale=kwargs['scale'];text='Whait shall we bodd in Neapolis?' if scale==3 else 'What shall me bodd in Neapolis?'
                if case=='missing_scale' and scale==4:return []
                if case=='disagree' and kwargs.get('grayscale'):text=text.replace('Neapolis','Neapous')
                if case=='city' and scale==4:text=text.replace('Neapolis','Neapous')
                if case=='changed_verb':text=text.replace('bodd','sell')
                r=prepared(text,224,80,198,14)
                if case=='moved':r['bounds'][1]+=30;r['center'][1]+=30
                if case=='low':r['confidence']=.5
                return [r]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_joined_production_title(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[0]['text'],'What shall me bodd in Neapolis?' if case=='valid' else original['text'],case)
            self.assertEqual(rows[0]['provenance'][0]['text'],original['text'])
            if case=='valid':self.assertEqual(rows[0]['production_title_identity_consensus']['independent_scales'],2)

    def test_original_neapolis_preserves_all_sixteen_model_choices(self):
        p=Path('runs/attempt-010/screens/ui-0002570.png')
        if not p.exists():self.skipTest('Private original calibration unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(p);o['path']=str(p.resolve())
        state={'evidence':{'kind':'live_memory','observation_sha256':'40a794f73d87a836246d485296276e0260c1bc01a51862edb556ac42d950ef8a'},
               'player':{'id':1},'cities':[{'id':15,'owner':1,'name':'Neapolis','x':58,'y':10}]}
        d=classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_choice')
        self.assertEqual([r['text'] for r in d['options']],['Settlers','Warriors','Phalanx','Archers','Horsemen','Catapult',
            'Diplomat','Caravan','Explorer','Palace','Barracks','Granary','Temple','MarketPlace','Library','Courthouse'])
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        title=next(r for r in o['lines'] if r['text']=='What shall me bodd in Neapolis?')
        self.assertEqual(title['provenance'][0]['text'],'What shall me buddmn Neapous!')
        self.assertEqual(title['production_title_identity_consensus']['independent_scales'],2)


if __name__=='__main__':unittest.main()
