from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class SplitCompleteProduction(unittest.TestCase):
    def test_two_scales_and_complete_adjacent_source_fragments(self):
        base=[prepared('What snall',226,80,64,12),prepared('me budd in TESTI',288,80,130,14),
              *[prepared(t,x,390,30,16) for t,x in [('Auto',155),('Help',305),('OK',455)]]]
        for case in ('valid','disagree','one_scale','different_city','moved','missing_button','distant','duplicate'):
            rows=deepcopy(base)
            if case=='missing_button':rows.pop()
            if case=='distant':rows[1]['bounds'][0]+=20
            if case=='duplicate':rows.append(deepcopy(rows[1]))
            def crop(image,row,name,*args,**kwargs):
                scale=kwargs.get('scale')
                if case=='one_scale' and scale==4:return []
                text='What shall we boold in TEST?' if scale==3 else 'What shallme bold in TEST?'
                if case=='disagree' and kwargs.get('grayscale'):text=text.replace('TEST','TEZT')
                if case=='different_city' and scale==4:text=text.replace('TEST','TESTI')
                r=prepared(text,226,80,192,14)
                if case=='moved':r['center'][1]+=40;r['bounds'][1]+=40
                return [r]
            with patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_split_production_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],'What shall we boold in TEST?' if case=='valid' else base[0]['text'],case)
            if case=='valid':self.assertEqual([p['text'] for p in rows[0]['provenance'][:2]],[r['text'] for r in base[:2]])

    def test_original_split_pompeii_retains_sixteen_choices(self):
        p=Path('runs/attempt-011/screens/ui-0002118.png')
        if not p.exists():self.skipTest('Private original frame unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        original=p.read_bytes();o=observe.recognize(p)
        state={'cities':[], 'observed_city_names':['Pompei'], 'recent_founding_notices':[dict(name='Pompei',year_text='375 B.C.',source_tag='FOUNDED',
            image_sha256='81435359ff897f4df8832ca9964ad6931a4cc631ef7903bf3c1687389586cba2')]}
        d=classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_choice')
        self.assertEqual([v['text'] for v in d['options']],['Settlers','Archers','Legion','Pikemen','Trireme','Diplomat',
            'Caravan','Barracks','Granary','Temple','MarketPlace','Library','Courthouse','Hanging Gardens','Colossus','Lighthouse'])
        title=next(r for r in o['lines'] if r['text']=='What shall we boold in Pompeu?')
        self.assertEqual([r['text'] for r in title['provenance'][:2]],['What snall','me budd in Pompeut'])
        self.assertEqual(p.read_bytes(),original)


if __name__=='__main__':unittest.main()
