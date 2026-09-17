"""Fragment joining is only a crop anchor; exact pixels still authorize titles."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from test_dialogs import row

class CaptionFragments(unittest.TestCase):
    def rows(self):
        values=[row('Soheit s',x=252,y=154,w=40,h=12),
                row('me boikd in Rome?',x=355,y=153,w=114,h=14),
                row('Auto',x=172,y=326,w=30),row('Help',x=321,y=327,w=30),row('OK',x=470,y=326,w=24)]
        for r in values:r['provenance']=[{'text':r['text'],'preprocessing':'TEST native'}]
        return values
    def apply(self,rows):
        with patch.object(observe,'_crop_text',return_value=[]),patch.object(observe,'_production_names',return_value=set()):
            observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
    def test_preserves_both_raw_fragments_without_claiming_canonical_text(self):
        rows=self.rows();self.apply(rows)
        joined=[r for r in rows if r.get('production_caption_fragments')]
        self.assertEqual(len(joined),1)
        self.assertEqual(joined[0]['text'],'Soheit s me boikd in Rome?')
        self.assertEqual([p['text'] for p in joined[0]['provenance']],['Soheit s','me boikd in Rome?'])
        self.assertNotIn('gdi_title_pixels',joined[0])
    def test_ambiguous_displaced_or_missing_controls_do_not_join(self):
        for mode in ('extra','shift','controls'):
            rows=self.rows()
            if mode=='extra':rows.append(deepcopy(rows[0]))
            elif mode=='shift':rows[0]['center'][1]+=10
            else:rows.pop()
            self.apply(rows)
            self.assertFalse(any(r.get('production_caption_fragments') for r in rows),mode)
    def test_actual_original_frame_requires_exact_title_and_preserves_five_choices(self):
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        p=Path(__file__).resolve().parents[1]/'runs/attempt-012/screens/ui-0000169.png'
        if not p.exists():self.skipTest('Private original frame unavailable')
        o=observe.recognize(p)
        state={'evidence':{'kind':'live_memory','observation_sha256':'a'*64},'player':{'id':1},
               'cities':[{'id':0,'owner':1,'name':'Rome','x':59,'y':33}]}
        d=classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d)
        self.assertEqual(d['title'],'What shall we build in Rome?')
        self.assertEqual([x['text'] for x in d['options']],['Settlers','Warriors','Diplomat','Barracks','Library'])
        self.assertEqual(d['evidence']['exact_production_title']['black_missing'],0)
        self.assertIn('Soheit s me boikd in Rome?',d['visible_text'])

if __name__=='__main__':unittest.main()
