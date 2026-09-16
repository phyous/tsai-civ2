"""Synthetic TEST technology trade plus optional actual-image regression."""
import copy
from pathlib import Path
import unittest
from civ2.dialogs import classify_dialog
from tests.test_herald import prepared

SOURCE='''@EXCHANGE0
@width=320
@title=%STRING0 Emissary
"We note that your primitive civilization has not even discovered %STRING1. We desire the secret of %STRING3. Do you care to exchange knowledge with us?"

"No. We do not need %STRING1."
"Okay, let's exchange knowledge."
'''
LABELS='"Will you accept %STRING4 instead?"'

def fixture():
    lines=[prepared('TEST Emissary',394,260,150,16),
      prepared('"We note that your primitive civilization has not',308,284,322,20),
      prepared('even discovered TEST Masonry. We desire the',308,306,300,16),
      prepared('secret of TEST Burial. Do you care to',308,326,292,16),
      prepared('exchange knowledge with us?"',308,344,208,16),
      prepared('"No. We do not need TEST Masonry."',338,370,240,18),
      prepared('"Okay, let\'s exchange knowledge."',344,394,240,18),
      prepared('"Will you accept TEST Writing instead?"',344,420,270,18),
      prepared('OK',456,454,26,16)]
    return dict(width=640,height=480,sha256='a'*64,lines=lines)

class ExchangeTests(unittest.TestCase):
    def test_counteroffer_needs_original_labels_and_stays_model_choice(self):
        o=fixture();r=classify_dialog(o,game_text=SOURCE,labels_text=LABELS)
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'EXCHANGE0')
        self.assertTrue(r['requires_model']);self.assertIsNone(r['mechanical_action'])
        self.assertEqual([x['text'] for x in r['options']],[x['text'] for x in o['lines'][5:8]])
        self.assertEqual(r['options'][2]['center'],[479,429])
        for labels in (None,'TEST unrelated labels',LABELS+'\n'+LABELS):
            self.assertFalse(classify_dialog(o,game_text=SOURCE,labels_text=labels)['supported'])
    def test_two_option_original_and_incomplete_or_changed_choices(self):
        o=fixture();o['lines'].pop(7)
        self.assertTrue(classify_dialog(o,game_text=SOURCE)['supported'])
        for case in ('missing','duplicate','body','counteroffer'):
            b=fixture()
            if case=='missing':b['lines'].pop(6)
            elif case=='duplicate':b['lines'][6]['text']=b['lines'][5]['text']
            elif case=='body':b['lines'][2]['text']='Pay TEST tribute or face war.'
            else:b['lines'][7]['text']='"Will you accept TEST gold instead of knowledge?"'
            self.assertFalse(classify_dialog(b,game_text=SOURCE,labels_text=LABELS)['supported'],case)
    def test_optional_actual_exchange_body_pixels_and_raw_provenance(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-006/screens/ui-0000962.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original exchange frame unavailable')
        from civ2.observe import recognize
        from civ2.run import game_text,labels_text
        o=recognize(p);r=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(r['supported'],r);self.assertTrue(r['requires_model'])
        self.assertEqual(len(r['options']),3);self.assertEqual(r['options'][2]['center'],[463,429])
        row=next(x for x in o['lines'] if 'We desire' in x['text'])
        self.assertTrue(any('deswe' in v['text'] for v in row['provenance']))
        self.assertEqual({v['preprocessing'] for v in row['provenance']},{'native','exchange_body_3x','exchange_body_gray_3x'})

if __name__=='__main__':unittest.main()
