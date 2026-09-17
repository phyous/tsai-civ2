"""TEST greeting punctuation consensus; no diplomatic terms are inferred."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class GreetingBodyPixels(unittest.TestCase):
    def rows(self):
        return [prepared('Cordial TEST Emissary',391,381,157,16),
                prepared('"T hear a message from our most wise',307,403,255,19),
                prepared('Emperor: TEST of the TEST people.',308,425,251,16),
                prepared('OK',455,454,25,13)]

    def test_two_prose_reads_and_two_punctuation_reads_preserve_words(self):
        intro=prepared('"I bear a message from our most wise',307,403,257,20)
        tail=dict(text='Emperor: TEST of the TEST people ..."',confidence=1,x=.01,y=.06,width=.94,height=.77)
        for case in ('valid','intro_disagrees','tail_disagrees','tail_changes_name','no_quote','extra_choice'):
            rows=self.rows();second_intro=deepcopy(intro);second_tail=deepcopy(tail)
            if case=='intro_disagrees':second_intro['text']='"I hear a message from our most wise'
            elif case=='tail_disagrees':second_tail['text']='Emperor: TEST of the TEST people..."'
            elif case=='tail_changes_name':second_tail['text']='Emperor: OTHER of the TEST people ..."'
            elif case=='no_quote':second_tail['text']='Emperor: TEST of the TEST people ...'
            elif case=='extra_choice':rows.insert(3,prepared('Pay TEST gold.',308,440,200,12))
            original_tail=deepcopy(rows[-2])
            with tempfile.TemporaryDirectory() as directory,patch.object(observe,'_crop_text',side_effect=[[deepcopy(intro)],[second_intro]]) as crop,patch.object(observe,'_run_ocr',side_effect=[[deepcopy(tail)],[second_tail]]):
                observe._recover_greeting_body(Image.new('RGB',(640,480)),rows,None,directory,{'passes':[]})
            if case=='valid':
                self.assertEqual(rows[1]['text'],intro['text'])
                self.assertEqual(rows[2]['text'],tail['text']);self.assertEqual(len(rows[2]['provenance']),3)
            elif case=='extra_choice':crop.assert_not_called()
            else:self.assertEqual(rows[-2],original_tail)

    def test_optional_original_010_is_only_source_bound_greeting(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-010/screens/ui-0000492.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original herald absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'GREETINGS02')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertEqual(o['lines'][2]['text'],'Emperor: Frederick of the Germans ..."')
        self.assertIn('Emperor: Frederick of the Germans.',[x['text'] for x in o['lines'][2]['provenance']])

    def test_original_greetings00_preserves_variable_leader_and_closing_words(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-011/screens/ui-0001162.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original herald absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'GREETINGS00')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertIn('"Greetings from the most exalted Isabella:',[r['text'] for r in o['lines']])
        tail=next(r for r in o['lines'] if r['text'].startswith('Empress of the Spanish'))
        self.assertTrue(tail['text'].endswith('..."'))
        self.assertEqual(tail['provenance'][0]['text'],'Empress of the Spanish..')

    def test_greetings00_requires_two_tail_reads_and_keeps_leader(self):
        rows=self.rows();rows[1]['text']='"Greetings from the most exalted TEST:'
        rows[2]=prepared('Empress of the TEST...',308,425,251,16)
        tail=dict(text='Empress of the TEST ..."',confidence=1,x=.01,y=.06,width=.94,height=.77)
        with tempfile.TemporaryDirectory() as directory,patch.object(observe,'_crop_text') as crop,patch.object(
                observe,'_run_ocr',side_effect=[[deepcopy(tail)],[deepcopy(tail)]]):
            observe._recover_greeting_body(Image.new('RGB',(640,480)),rows,None,directory,{'passes':[]})
        crop.assert_not_called();self.assertEqual(rows[1]['text'],'"Greetings from the most exalted TEST:')
        self.assertEqual(rows[2]['text'],tail['text'])

    def test_greetings01_keeps_observed_leader_and_requires_two_exact_tail_reads(self):
        for changed in (False,True):
            rows=self.rows();rows[1]['text']='"I bring tidings from TEST King, ruler and'
            rows[2]=prepared('Emperor of the TEST..',308,425,251,16)
            tail=dict(text='Emperor of the TEST ..."',confidence=1,x=.01,y=.06,width=.94,height=.77)
            second=deepcopy(tail)
            if changed:second['text']='Emperor of the OTHER ..."'
            before=deepcopy(rows)
            with tempfile.TemporaryDirectory() as directory,patch.object(observe,'_crop_text') as crop,patch.object(
                    observe,'_run_ocr',side_effect=[[tail],[second]]):
                observe._recover_greeting_body(Image.new('RGB',(640,480)),rows,None,directory,{'passes':[]})
            crop.assert_not_called();self.assertEqual(rows[1],before[1])
            if changed:self.assertEqual(rows,before)
            else:
                self.assertEqual(rows[2]['text'],tail['text'])
                self.assertEqual(rows[2]['provenance'][-1]['scale'],2)

    def test_original_greetings01_retains_every_word_and_has_no_strategic_choice(self):
        p=Path('runs/attempt-010/screens/ui-0001762.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original herald absent')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'GREETINGS01')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertIn('"I bring tidings from Frederick, ruler and',[r['text'] for r in o['lines']])
        tail=next(r for r in o['lines'] if r['text'].startswith('Emperor'))
        self.assertEqual(tail['text'],'Emperor of the Germans ..."')
        self.assertIn(tail['provenance'][0]['text'],('Emperor of the Germans.','Emperor of the Germans..'))


if __name__=='__main__':unittest.main()
