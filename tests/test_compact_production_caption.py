from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class CompactProductionCaption(unittest.TestCase):
    def test_changed_city_requires_two_scales_and_paired_actual_text(self):
        original=prepared('Whait shallme boddin TESTI',226,80,192,14)
        for case in ('valid','disagree','one_scale','different_city','moved','missing_button'):
            rows=[deepcopy(original),*[prepared(t,x,390,30,16) for t,x in [('Auto',155),('Help',305),('OK',455)]]]
            if case=='missing_button':rows.pop()
            def crop(image,row,name,*args,**kwargs):
                scale=kwargs.get('scale')
                if (scale,kwargs.get('padding')) not in ((3,(3,3)),(4,(4,3))):return []
                if case=='one_scale' and scale==4:return []
                text='What shall we boold in TEST?' if scale==3 else 'What shallme bold in TEST?'
                if case=='disagree' and kwargs.get('grayscale'):text=text.replace('TEST','TEZT')
                if case=='different_city' and scale==4:text=text.replace('TEST','TEZT')
                r=prepared(text,226,80,192,14)
                if case=='moved':r['center'][1]+=40;r['bounds'][1]+=40
                return [r]
            with patch.object(observe,'_crop_text',side_effect=crop),patch.object(observe,'_production_names',return_value=set()):
                observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'What shall we boold in TEST?' if case=='valid' else original['text'],case)
            if case=='valid':
                self.assertEqual(rows[0]['provenance'][0]['text'],original['text'])
                self.assertEqual(rows[0]['production_title_identity_consensus']['independent_scales'],2)

    def test_original_pompeii_retains_all_sixteen_choices(self):
        p=Path('runs/attempt-012/screens/ui-0001664.png')
        if not p.exists():self.skipTest('Private original frame unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        before=p.read_bytes();o=observe.recognize(p)
        state={'cities':[{'name':'Pompei'}],'recent_founding_notices':[dict(name='Pompei',year_text='A.D. 60',source_tag='FOUNDED',
            image_sha256='9f19b0707806434b2fbd561399878a212056840dd77aabda8ac3aa670cf6a5e8')]}
        d=classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_choice')
        self.assertEqual([v['text'] for v in d['options']],['Settlers','Warriors','Phalanx','Horsemen','Trireme','Diplomat',
            'Caravan','Palace','Barracks','Temple','MarketPlace','Library','Courthouse','City Walls','Pyramids','Colossus'])
        title=next(r for r in o['lines'] if r['text']=='What shall we boold in Pompeu?')
        self.assertEqual(title['provenance'][0]['text'],'Whait shallme boddin Pompeul')
        self.assertEqual(p.read_bytes(),before)


if __name__=='__main__':unittest.main()
