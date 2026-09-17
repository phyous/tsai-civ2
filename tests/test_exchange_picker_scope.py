"""TEST bounded original-window scope; background cannot hide overlapping rows."""
from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from PIL import Image,ImageDraw
from civ2.dialogs import _rows,dialog_resources
from civ2.exchange_picker import classify_exchange_picker
from tests.test_exchange_picker import fixture


class ExchangePickerScope(TestCase):
    def test_only_wholly_outside_rows_with_complete_outer_frame_are_excluded(self):
        for case in ('outside','inside','overlap','broken_frame'):
            with self.subTest(case=case),TemporaryDirectory() as directory:
                o,rules,resources=fixture(directory);p=Path(o['path'])
                image=Image.open(p).convert('RGB');draw=ImageDraw.Draw(image)
                draw.rectangle((298,137,639,478),outline=(0,0,0))
                if case=='broken_frame':image.putpixel((298,200),(255,255,255))
                image.save(p);o['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
                extra={'text':'TEST ART','bounds':[518,56,44,40],'center':[540,76],'confidence':1}
                if case=='inside':extra.update(bounds=[518,220,44,40],center=[540,240])
                elif case=='overlap':extra.update(bounds=[518,125,44,40],center=[540,145])
                o['lines'].append(extra)
                result=classify_exchange_picker(o,_rows(o),resources,rules)
                if case=='outside':
                    self.assertIsNotNone(result);self.assertEqual(result['options'][0]['text'],'TEST Advance')
                    self.assertEqual(result['evidence']['outside_picker_rows'][0]['text'],'TEST ART')
                else:self.assertIsNone(result)

    def test_optional_original_two_choices_do_not_include_background_omega(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        p=Path('runs/attempt-010/screens/ui-0000534.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original screenshot absent')
        o=recognize(p);o['path']=str(p)
        result=classify_exchange_picker(o,_rows(o),dialog_resources(game_text()),parse_rules(original_rules()))
        self.assertIsNotNone(result)
        self.assertEqual([x['text'] for x in result['options']],['Pottery','Warrior Code'])
        self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
        self.assertEqual(result['evidence']['outside_picker_rows'][0]['text'],'Q')
