"""Native Buy quotes authorize choices only from complete calibrated evidence."""
import copy
from pathlib import Path
import unittest
from civ2.dialogs import classify_dialog
from tests.test_dialogs import observation,row

RULES={'units':[{'id':2,'name':'TEST Warriors'}],'improvements':[]}
GAME='''@COMPLETE0
@title=Buy %STRING0
^Cost to complete %STRING0: %NUMBER0 gold.
^Treasury: %NUMBER1 gold.
@COMPLETE1
@title=Buy %STRING0
^Cost to complete %STRING0: %NUMBER0 gold.
^Treasury: %NUMBER1 gold.

Complete it.
Never mind.
'''

def quote(affordable=True):
    rows=[row('Buy TEST Warriors',y=176,w=140),
          row(f'Cost to complete TEST Warriors: {2 if affordable else 110} gold.',x=300,y=200,w=280),
          row('Treasury: 9 gold.',x=227,y=220,w=118)]
    if affordable:rows += [row('Complete it.',x=247,y=246,w=82),row('Never mind.',x=245,y=271,w=82)]
    return observation(*rows,row('OK',y=306,w=24))

class BuyQuoteTests(unittest.TestCase):
    def test_affordable_quote_is_separate_model_choice_never_a_purchase_receipt(self):
        o=quote();result=classify_dialog(o,rules=RULES,game_text=GAME)
        self.assertTrue(result['supported'],result);self.assertEqual(result['kind'],'buy_quote')
        self.assertEqual(result['resource_tag'],'COMPLETE1');self.assertTrue(result['requires_model'])
        self.assertIsNone(result['mechanical_action'])
        self.assertEqual([r['text'] for r in result['options']],['Complete it.','Never mind.'])
        self.assertEqual([r['center'] for r in result['options']],[[247,246],[245,271]])
        self.assertEqual([r['text'] for r in result['buttons']],['OK'])
        self.assertEqual(result['quote']['cost'],2);self.assertEqual(result['quote']['treasury'],9)
        self.assertIs(result['quote']['purchase_executed'],False)
        self.assertEqual(result['evidence']['quote']['body_source_lines'],[1,2])
        self.assertEqual(result['sha256'],o['sha256'])

    def test_unaffordable_quote_only_acknowledges_exact_original_single_ok(self):
        result=classify_dialog(quote(False),rules=RULES,game_text=GAME)
        self.assertTrue(result['supported'],result);self.assertFalse(result['requires_model'])
        self.assertEqual(result['resource_tag'],'COMPLETE0')
        self.assertEqual(result['mechanical_action'],'acknowledge_information')
        self.assertEqual([r['text'] for r in result['options']],['OK'])
        self.assertEqual(result['quote']['cost'],110)

    def test_missing_choice_never_becomes_mechanical_confirmation(self):
        for missing in ([3],[4],[3,4]):
            o=quote();o['lines']=[r for i,r in enumerate(o['lines']) if i not in missing]
            result=classify_dialog(o,rules=RULES,game_text=GAME)
            self.assertFalse(result['supported']);self.assertIsNone(result['mechanical_action'])
        o=quote(False);o['lines'].insert(-1,row('Complete it.',y=270,w=100))
        self.assertFalse(classify_dialog(o,rules=RULES,game_text=GAME)['supported'])

    def test_full_body_item_resource_and_affordability_are_bound(self):
        for mutate in (lambda o:o['lines'].pop(1),lambda o:o['lines'].pop(2),
            lambda o:o['lines'][1].update(text='Cost to complete Other: 2 gold.'),
            lambda o:o['lines'][1].update(text='Cost to complete TEST Warriors: -2 gold.'),
            lambda o:o['lines'][1].update(text='Cost to complete TEST Warriors: 20 gold.'),
            lambda o:o['lines'][2].update(text='Treasury: 9 gold. Additional fee 20 gold.'),
            lambda o:o['lines'].insert(3,row('CIVIL DISORDER.',y=232,w=150)),
            lambda o:o['lines'].append(row('Buy TEST Warriors',y=80,w=150))):
            o=quote();mutate(o)
            with self.subTest(o=o):self.assertFalse(classify_dialog(o,rules=RULES,game_text=GAME)['supported'])
        for bad_game in (None,GAME.replace('Treasury:','Fee:'),GAME.replace('Never mind.','Confirm it.')):
            self.assertFalse(classify_dialog(quote(),rules=RULES,game_text=bad_game)['supported'])
        self.assertFalse(classify_dialog(quote(),rules={'units':[]},game_text=GAME)['supported'])

    def test_duplicates_unaligned_controls_low_confidence_or_ocr_conflicts_fail(self):
        for mutate in (lambda o:o['lines'].append(row('OK',x=500,y=306,w=24)),
            lambda o:o['lines'].__setitem__(-1,row('OK',x=420,y=306,w=24)),
            lambda o:o['lines'].append(row('Cancel',x=410,y=306,w=45)),
            lambda o:o['lines'][1].update(confidence=.6),
            lambda o:o.update(ocr={'conflicts':[{'text':'Other','bounds':[180,192,70,16]}]})):
            o=quote();mutate(o)
            self.assertFalse(classify_dialog(o,rules=RULES,game_text=GAME)['supported'])

    def test_optional_original_both_calibrated_quotes(self):
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.run import game_text
        root=Path(__file__).resolve().parents[1]
        paths=[root/f'.runtime/city-calibration/ui-{n:07d}.png' for n in (44,52)]
        if not all(p.exists() for p in paths) or not (root/'.runtime/ocr').exists():self.skipTest('private calibration images unavailable')
        for path,tag,cost in zip(paths,('COMPLETE0','COMPLETE1'),(110,2)):
            result=classify_dialog(recognize(path),rules=parse_rules(original_rules()),game_text=game_text())
            self.assertTrue(result['supported'],result);self.assertEqual(result['resource_tag'],tag)
            self.assertEqual(result['quote']['cost'],cost);self.assertEqual(result['quote']['treasury'],9)

if __name__=='__main__':unittest.main()
