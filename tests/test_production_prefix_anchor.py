"""An exact literal prefix enables pixel rereads, never a canonical title."""
from copy import deepcopy
import json
from pathlib import Path
from unittest import TestCase,mock
from PIL import Image
from civ2.gdi_titles import annotate_production_crop_anchor
from tests.test_herald import prepared


class ProductionPrefixAnchor(TestCase):
    def test_exact_prefix_only_and_raw_caption_unchanged(self):
        base=[prepared('TEST damaged caption?',220,80,196,14),
              prepared('Auto',144,390,32,14),prepared('Help',304,390,32,14),prepared('OK',458,390,24,14)]
        black=[21,10,21];gray=[10,21,10]
        for mode in ('valid','missing_black','extra_black','missing_gray','color','no_control','two_headings','no_atlas'):
            with self.subTest(mode=mode):
                rows=deepcopy(base);image=Image.new('RGB',(640,480),(207,207,207))
                for y in range(3):
                    for x in range(5):image.putpixel((220+x,80+y),(0,0,0) if black[y]&(1<<x) else (134,134,134))
                if mode=='missing_black':image.putpixel((220,80),(207,207,207))
                if mode=='extra_black':image.putpixel((220,78),(0,0,0))
                if mode=='missing_gray':image.putpixel((221,80),(207,207,207))
                if mode=='color':image.putpixel((220,78),(200,207,207))
                if mode=='no_control':rows.pop()
                if mode=='two_headings':rows.append(prepared('TEST other caption?',220,110,196,14))
                before=deepcopy(rows)
                with mock.patch('civ2.gdi_titles._render',return_value=(5,3,black,gray),
                                side_effect=ValueError('unavailable') if mode=='no_atlas' else None):
                    annotate_production_crop_anchor(image,rows)
                if mode=='valid':
                    proof=rows[0].pop('production_crop_anchor')
                    self.assertEqual(proof['literal_prefix'],'What shall we build in')
                    self.assertEqual(proof['bounds'],[220,80,5,3]);self.assertEqual(rows,before)
                else:self.assertEqual(rows,before)

    def test_actual_011_damage_keeps_raw_title_and_all_original_choices(self):
        p=Path('runs/attempt-011/screens/ui-0003118.png');events=Path('runs/attempt-011/events.jsonl')
        if not p.exists() or not events.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame absent')
        from civ2.observe import recognize
        from civ2.memory import parse_memory
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        checkpoint=None
        for line in events.read_text().splitlines():
            e=json.loads(line)
            if e['kind']=='checkpoint':checkpoint=e['payload']['artifact']['path']
            if e['kind']=='screen_observed' and e['payload'].get('path')=='screens/ui-0003118.png':break
        state=parse_memory((events.parent/checkpoint).read_bytes(),rules_text=original_rules())
        o=recognize(p);o['path']=str(p)
        d=classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['title'],'What shall we build in Ravenna?')
        self.assertEqual([r['text'] for r in d['options']],['Settlers','Archers','Legion','Pikemen','Horsemen','Elephant','Trireme','Diplomat','Caravan','Palace','Barracks','Granary','Temple','MarketPlace','Library','Courthouse'])
        anchor=next(r for r in o['lines'] if r.get('production_crop_anchor'))
        self.assertEqual(anchor['text'],'Shat shall pe buddmn Ravenna?')
        self.assertEqual(anchor['production_crop_anchor']['bounds'],[222,79,134,12])
        self.assertIn('exact_production_title',d['evidence']);self.assertTrue(d['requires_model'])
        self.assertIsNone(d['mechanical_action'])
