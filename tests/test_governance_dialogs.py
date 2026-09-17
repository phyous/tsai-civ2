"""Synthetic TEST governance controls and optional original screenshots."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.dialogs import classify_dialog


def row(text,x,y,w=160,h=16):
    return observe._prepare_rows([dict(text=text,confidence=1,x=x/640,y=y/480,width=w/640,height=h/480)],640,480,'TEST')[0]


def observation(rows):return dict(width=640,height=480,sha256='a'*64,lines=rows)


COUNCIL='''@COUNCILTIME
@title=The High Council: %STRING2
@width=320
The High Council of the %STRING0 is meeting in %STRING1. If you wish, you may take this opportunity to consult your advisors and hear their views on the state of your realm.

Consult High Council.
No thanks, too busy.
'''

AUTOREV='''@AUTOREV
@title=Civ Rules: Governments
@width=320
You have just acquired knowledge of a new government form, %STRING0. Your current government is a %STRING1. Do you wish to begin a revolution in order to switch government types?

No, %STRING1 is working out fine.
Begin revolution.
'''


class GovernanceTests(unittest.TestCase):
    def test_government_offer_title_needs_complete_original_body_and_both_options(self):
        o=observation([row('Cir Roles: Governnents',248,140,148,12),
            row('You have just acquired knowledge of a new',180,163,288,16),
            row('government form, TEST Republic. Your current',182,183,305,18),
            row('government is a TEST Monarchy. Do you wish to',182,203,305,16),
            row('begin a revolution in order to switch',180,224,241,15),row('government types?',182,243,128,16),
            row('No, TEST Monarchy is working out fine.',217,269,231,19),row('Begin revolution.',217,294,117,17),
            row('OK',308,326,24,16),row('People',510,204,40,12)])
        r=classify_dialog(o,game_text=AUTOREV)
        self.assertTrue(r['supported'],r);self.assertTrue(r['requires_model']);self.assertIsNone(r['mechanical_action'])
        for case in ('body','missing','title'):
            bad=copy.deepcopy(o)
            if case=='body':bad['lines'][3]['text']='Pay TEST gold to continue.'
            elif case=='missing':bad['lines'].pop(7)
            else:bad['lines'][0]['text']='TEST different government warning'
            self.assertFalse(classify_dialog(bad,game_text=AUTOREV)['supported'],case)

    def test_optional_original_republic_offer(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-005/screens/ui-0001381.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original Republic offer unavailable')
        from civ2.run import game_text
        o=observe.recognize(p);r=classify_dialog(o,game_text=game_text())
        self.assertTrue(r['supported'],r);self.assertTrue(r['requires_model'])
        self.assertEqual([x['text'] for x in r['options']],['No, Monarchy is working out fine.','Begin revolution.'])
        self.assertTrue(any('goverument' in p['text'] for x in o['lines'] for p in x.get('provenance',[])))
    def test_two_actual_crop_reads_required_for_government_title(self):
        native=row('Select Tope of Goweroment',238,190,168)
        good=row('Select Type of Government',238,190,168)
        for peer,accepted in [(good,True),(row('Select Different Government',238,190,168),False)]:
            rows=[copy.deepcopy(native),row('OK',310,276,22)]
            with patch.object(observe,'_crop_text',side_effect=[[good],[peer]]):
                observe._recover_governance_labels(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],good['text'] if accepted else native['text'])

    def test_government_radio_prefix_remains_actual_model_option(self):
        o=observation([row('Select Type of Government',238,190,168),row('Despotism',236,218,74),
                       row('• Monarchy',210,241,98),row('OK',310,276,22)])
        r=classify_dialog(o)
        self.assertEqual(r['kind'],'government_choice');self.assertTrue(r['requires_model'])
        self.assertEqual(r['options'][1]['text'],'• Monarchy')
        for label in ('Do Monarchy','• TEST unknown'):
            altered=copy.deepcopy(o);altered['lines'][2]['text']=label
            self.assertFalse(classify_dialog(altered)['supported'])

    def test_council_needs_complete_source_body_and_both_actual_choices(self):
        o=observation([row('The Hligh Comcl: 1500 B.C.',232,14,176),
            row('The High Council of the TEST Romans is meeting in',180,38,300),
            row('TEST Rome. If you wish, you may take this',180,58,270),
            row('opportunity to consult your advisors and hear',180,78,300),
            row('their views on the state of your realm.',180,98,250),
            row('O Consult High Council.',206,122,172),row('• No thanks, too busy.',206,148,168),row('OK',308,182,26)])
        r=classify_dialog(o,game_text=COUNCIL)
        self.assertTrue(r['supported'],r);self.assertTrue(r['requires_model'])
        self.assertIsNone(r['mechanical_action']);self.assertEqual(r['resource_tag'],'COUNCILTIME')
        self.assertEqual(r['options'][0]['text'],'O Consult High Council.')
        compact=copy.deepcopy(o);compact['lines'][2]['text']=compact['lines'][2]['text'].replace('wish, you','wish,you')
        compact_result=classify_dialog(compact,game_text=COUNCIL)
        self.assertEqual(compact_result['kind'],'high_council');self.assertTrue(compact_result['requires_model'])
        self.assertIn('wish,you',compact_result['visible_text'],'original spacing remains evidence')
        missing_comma=copy.deepcopy(compact);missing_comma['lines'][2]['text']=missing_comma['lines'][2]['text'].replace('wish,you','wish you')
        self.assertFalse(classify_dialog(missing_comma,game_text=COUNCIL)['supported'])
        for change in ('missing','body','heading','extra'):
            bad=copy.deepcopy(o)
            if change=='missing':bad['lines'].pop(6)
            elif change=='body':bad['lines'][4]['text']='Pay TEST gold to proceed.'
            elif change=='heading':bad['lines'][0]['text']='TEST unknown warning: 1500 B.C.'
            else:bad['lines'].insert(5,row('Pay TEST gold.',206,114,140,8))
            self.assertFalse(classify_dialog(bad,game_text=COUNCIL)['supported'],change)
        self.assertFalse(classify_dialog(o)['supported'])

    def test_optional_original_council_and_government_selection(self):
        root=Path(__file__).resolve().parents[1]
        cases=[('005',1164,'high_council'),('004',776,'government_choice'),('006',1092,'high_council')]
        paths=[root/f'runs/attempt-{a}/screens/ui-{n:07d}.png' for a,n,_ in cases]
        if not all(p.exists() for p in paths) or not(root/'.runtime/ocr').exists():self.skipTest('Private original governance frames unavailable')
        from civ2.run import game_text
        for p,(_,_,kind) in zip(paths,cases):
            before=p.read_bytes();r=classify_dialog(observe.recognize(p),game_text=game_text())
            self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],kind)
            self.assertTrue(r['requires_model']);self.assertEqual(len(r['options']),2)
            self.assertEqual(p.read_bytes(),before)


if __name__=='__main__':unittest.main()
