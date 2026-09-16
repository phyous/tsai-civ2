"""Synthetic TEST herald observations; optional private original calibration."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.dialogs import classify_dialog


def prepared(text,x,y,w,h,confidence=1):
    return observe._prepare_rows([dict(text=text,x=x/640,y=y/480,width=w/640,height=h/480,
                                      confidence=confidence)],640,480,'TEST native')[0]


def panel_rows():
    return [dict(text=t,x=x,y=y,width=w,height=h,confidence=c) for t,x,y,w,h,c in [
        ('TEST Emissary',.28,.08,.44,.14,1),
        ('"I bear a message from our most wise TEST:',.03,.28,.9,.17,1),
        ('TEST ruler of the TEST people ..."',.03,.48,.6,.17,1),
        ('ок',.464,.759,.072,.123,.5)]]


class HeraldTests(unittest.TestCase):
    def test_panel_requires_two_matching_reads_and_two_actual_ascii_button_reads(self):
        image=Image.new('RGB',(640,480),'gray')
        native=[prepared('TEST Eimissary',390,380,154,18)]
        button=prepared('OK',458,455,20,12)
        for variant in ('good','body_disagrees','non_ascii_button','weak_button'):
            rows=copy.deepcopy(native);first=panel_rows();second=panel_rows();b=copy.deepcopy(button)
            if variant=='body_disagrees':second[1]['text']='TEST other message'
            if variant=='non_ascii_button':b['text']='OК'
            if variant=='weak_button':b['confidence']=.5
            with tempfile.TemporaryDirectory() as directory,patch.object(observe,'_run_ocr',side_effect=[first,second]),patch.object(observe,'_crop_text',return_value=[b]):
                observe._recover_herald_panel(image,rows,None,directory,{'passes':[]})
            if variant=='good':
                self.assertEqual(rows[-1]['text'],'OK');self.assertEqual(rows[-1]['center'],[468,461])
                self.assertGreaterEqual(len(rows[-1]['provenance']),4)
                self.assertEqual(rows[1]['text'],first[1]['text'])
            else:self.assertEqual(rows,native,variant)

    def test_unrelated_screen_does_not_trigger_panel_reads(self):
        rows=[prepared('TEST Emissary',200,150,154,18)]
        with patch.object(observe,'_run_ocr') as reader:
            observe._recover_herald_panel(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
        reader.assert_not_called()

    def test_complete_wrapped_source_greeting_is_information_but_extra_choice_is_not(self):
        source='@GREETINGS02\n@width=320\n@title=%STRING0 Emissary\n"I bear a message from our most wise %STRING2: %STRING1 of the %STRING3_._._."\n'
        lines=[prepared('TEST Emissary',390,380,154,18),
               prepared('"I bear a message from our most wise TEST:',308,402,318,16),
               prepared('TEST ruler of the TEST people ..."',308,424,260,18),prepared('OK',458,455,20,12)]
        o=dict(width=640,height=480,sha256='a'*64,lines=lines)
        r=classify_dialog(o,game_text=source)
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'GREETINGS02')
        self.assertFalse(r['requires_model']);self.assertEqual(r['mechanical_action'],'acknowledge_information')
        for altered in (source.replace('I bear a message','Give me gold'),source+'\nPay TEST gold.\n'):
            self.assertFalse(classify_dialog(o,game_text=altered)['supported'])
        bad=copy.deepcopy(o);bad['lines'].insert(3,prepared('Pay TEST gold.',320,440,100,10))
        self.assertFalse(classify_dialog(bad,game_text=source)['supported'])

    def test_optional_original_first_viking_herald_pixels(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-006/screens/ui-0000928.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original herald frame unavailable')
        from civ2.run import game_text
        before=p.read_bytes();o=observe.recognize(p);r=classify_dialog(o,game_text=game_text())
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'GREETINGS02')
        self.assertEqual(r['mechanical_action'],'acknowledge_information')
        self.assertEqual(r['options'][0]['center'],[468,461]);self.assertEqual(p.read_bytes(),before)
        button=next(row for row in o['lines'] if row['text']=='OK')
        self.assertEqual(len(button['provenance']),4)


if __name__=='__main__':unittest.main()
