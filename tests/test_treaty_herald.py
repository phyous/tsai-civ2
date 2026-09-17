"""The wider original herald notice requires actual paired pixel readings."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from civ2.observe import _prepare_rows,_recover_herald_panel,recognize
from civ2.dialogs import classify_dialog

SOURCE='''@TREATY
@width=320
@title=%STRING0 Emissary
"We affirm this treaty of eternal friendship and goodwill between the people of the %STRING1 and %STRING2 civilizations.  We shall withdraw our forces from your territory at once."
'''


class TreatyHeraldTests(unittest.TestCase):
    def test_actual_wide_notice_body_button_and_raw_provenance(self):
        p=Path('runs/attempt-006/screens/ui-0000995.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original capture unavailable')
        original=p.read_bytes();o=recognize(p)
        result=classify_dialog(o,game_text=SOURCE)
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['resource_tag'],'TREATY')
        self.assertEqual(result['mechanical_action'],'acknowledge_information')
        self.assertFalse(result['requires_model'])
        self.assertEqual([b['text'] for b in result['buttons']],['OK'])
        between=next(r for r in o['lines'] if r['text'].startswith('goodwill between'))
        readings=[r['text'] for r in between['provenance']]
        self.assertTrue(any('hetween' in r for r in readings))
        self.assertGreaterEqual(readings.count(between['text']),2)
        self.assertEqual(p.read_bytes(),original)

    def test_missing_ok_or_disagreeing_panel_never_rewrites_rows(self):
        def line(text,x,y,w,h):return dict(text=text,x=x/640,y=y/480,width=w/640,height=h/480,confidence=1.)
        original=_prepare_rows([line('Receptine Wiking Emnissary',354,340,166,18),
            line('old original body',312,362,300,18),line('OK',425,454,24,13)],640,480,'native')
        panel=[dict(text='Receptive Viking Emissary',x=.30,y=.06,width=.50,height=.12,confidence=1.),
               dict(text='new body one',x=.18,y=.25,width=.60,height=.12,confidence=1.),
               dict(text='new body two',x=.18,y=.44,width=.60,height=.12,confidence=1.)]
        for mode in ('missing_ok','disagree'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                rows=deepcopy(original[:-1] if mode=='missing_ok' else original);before=deepcopy(rows)
                answers=[deepcopy(panel),deepcopy(panel)]
                if mode=='disagree':answers[1][1]['text']='different body'
                with patch('civ2.observe._run_ocr',side_effect=answers):
                    _recover_herald_panel(Image.new('RGB',(640,480)),rows,'unused',directory,{'passes':[]})
                self.assertEqual(rows,before)


if __name__=='__main__':unittest.main()
