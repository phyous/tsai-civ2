"""Original category penalty requires a fresh model choice, never auto-OK."""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
from civ2.production_change import SOURCE,classify_production_change
from civ2.dialogs import _rows,classify_dialog


def fixture():
    def row(text,x,y,w=300,h=16):
        return dict(text=text,confidence=1.,bounds=[x,y,w,h],center=[x+w//2,y+h//2])
    rows=[row('Civ Rules: Change of Production',220,150,200),
        row('Sire, if we change our production between items',158,172,324),
        row('of different general types (Units, City',158,194,252),
        row('Improvements, Wonders of the World), there is',158,214,320),
        row('a 50% production penalty.',158,234,180),
        row('• Continue producing TEST Settlers.',170,258,250,18),
        row('Switch to TEST Granary at 50% penalty.',194,284,280,20),
        row('OK',310,318,22,12),row('Exit',570,445,40)]
    return dict(width=640,height=480,sha256='a'*64,lines=rows),{'units':[{'name':'TEST Settlers'}],'improvements':[{'name':'TEST Granary'}]}


class ProductionChangeTests(TestCase):
    def test_complete_source_terms_expose_both_actual_choices(self):
        o,rules=fixture();r=classify_production_change(o,_rows(o),[SOURCE],rules)
        self.assertEqual(r['kind'],'production_change_choice')
        self.assertEqual(r['production_change'],dict(current_item='TEST Settlers',proposed_item='TEST Granary',penalty_percent=50,executed=False))
        self.assertEqual(len(r['options']),2)
        self.assertEqual([r['control'] for r in r['options']],['option','option'])
        self.assertEqual(r['buttons'][0]['text'],'OK')

    def test_partial_terms_unknown_items_number_mismatch_or_extra_control_refuse(self):
        for mode in ('body','item','percent','extra','source','option','geometry'):
            with self.subTest(mode=mode):
                o,rules=fixture();source=deepcopy(SOURCE)
                if mode=='body':o['lines'][1]['text']='TEST partial warning'
                elif mode=='item':rules['improvements']=[]
                elif mode=='percent':o['lines'][6]['text']='Switch to TEST Granary at 25% penalty.'
                elif mode=='extra':o['lines'].insert(-2,dict(o['lines'][4],text='Cancel'))
                elif mode=='source':source['options']=[]
                elif mode=='option':o['lines'].pop(5)
                else:o['lines'][6]['center'][1]=460;o['lines'][6]['bounds'][1]=450
                self.assertIsNone(classify_production_change(o,_rows(o),[source],rules))

    def test_actual_original_confirmation_retains_cost_and_both_choices(self):
        p=Path('runs/attempt-011/screens/ui-0001068.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original production warning unavailable')
        from civ2.observe import recognize
        from civ2.run import game_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        o=recognize(p);r=classify_dialog(o,game_text=game_text(),rules=parse_rules(original_rules()))
        self.assertTrue(r['supported'],r);self.assertTrue(r['requires_model'])
        self.assertIsNone(r['mechanical_action']);self.assertEqual(r['resource_tag'],'PRODCHANGE')
        self.assertEqual(r['production_change']['penalty_percent'],50)
        self.assertEqual([x['text'] for x in r['options']],['• Continue producing Settlers.','Switch to Granary at 50% penalty.'])
        line=next(x for x in o['lines'] if x['text']=='Sire, if we change our production between items')
        self.assertIn('Sire, if we change ou production between items',[x['text'] for x in line['provenance']])
