"""Synthetic TEST notice body plus optional original no-CD calibration."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from civ2.dialogs import classify_dialog,dialog_resources
from tests.test_dialogs import observation,row

SOURCE='''@CDROMNOTFOUND
@width=320
@title=Please Note
@button=Repeat Search
TEST optional Civilization II CD-ROM media unavailable. Continue this TEST session.
'''

class CDROMNotice(unittest.TestCase):
    def test_full_pinned_notice_only_exposes_default_ok(self):
        source_hash=hashlib.sha256(json.dumps(dialog_resources(SOURCE)[0],sort_keys=True).encode()).hexdigest()
        o=observation(row('Please Lfote',y=140,w=90),
            row('TEST optional Civilization I CD-ROM',y=168,w=300),
            row('media unavailable. Continue this TEST session.',y=190,w=310),
            row('Repeat Search',x=238,y=338,w=90),row('OK',x=403,y=338,w=24))
        with patch('civ2.dialogs.CDROM_TEMPLATE_SHA256',source_hash):
            d=classify_dialog(o,game_text=SOURCE)
            self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'CDROMNOTFOUND')
            self.assertEqual(d['mechanical_action'],'acknowledge_information');self.assertIsNone(d['outcome'])
            self.assertFalse(d['requires_model']);self.assertEqual([r['text'] for r in d['options']],['OK'])
            self.assertIn('Civilization I CD-ROM',d['visible_text'])
            for case in ('extra_body','missing_button','extra_control','changed_source'):
                from copy import deepcopy
                altered=deepcopy(o);source=SOURCE
                if case=='extra_body':altered['lines'][2]['text']+=' TEST erase city?'
                elif case=='missing_button':altered['lines'].pop(3)
                elif case=='extra_control':altered['lines'].append(row('Cancel',x=500,y=338,w=40))
                else:source=source.replace('Continue','Delete')
                self.assertFalse(classify_dialog(altered,game_text=source)['supported'],case)

    def test_optional_original_009_no_cd_notice(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-009/screens/ui-0000589.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original no-CD frame unavailable')
        d=classify_dialog(recognize(p),game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'CDROMNOTFOUND')
        self.assertFalse(d['requires_model']);self.assertIsNone(d['outcome'])
        self.assertEqual(d['options'][0]['text'],'OK');self.assertEqual(d['options'][0]['center'],[403,337])

if __name__=='__main__':unittest.main()
