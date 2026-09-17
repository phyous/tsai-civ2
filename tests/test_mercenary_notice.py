"""Original mercenary hut announcement is only source-bound information."""
from copy import deepcopy
from pathlib import Path
import unittest
from civ2.native_events import classify_information
from test_treaty_reminder import row

SOURCE=dict(tag='SURPRISEMERCS',title='Village',width=300,
    body='You have discovered a friendly tribe of skilled mercenaries.',options=[],buttons=[],listbox=False)

class MercenaryNoticeTests(unittest.TestCase):
    def test_complete_source_body_and_sole_ok_are_required(self):
        original=dict(width=640,height=480,sha256='a'*64,lines=[row('Village',290,160,60),
            row('You have discovered a friendly tribe of',160,190,280),
            row('skilled mercenaries.',160,210,150),row('OK',308,260,24)])
        result=classify_information(original,[SOURCE])
        self.assertTrue(result['supported'],result);self.assertFalse(result['requires_model'])
        self.assertEqual(result['mechanical_action'],'acknowledge_information')
        for mode in ('missing','hostile','extra','wrong_source'):
            o=deepcopy(original);source=deepcopy(SOURCE)
            if mode=='missing':o['lines'].pop(2)
            elif mode=='hostile':o['lines'][1]['text']=o['lines'][1]['text'].replace('friendly','hostile')
            elif mode=='extra':o['lines'].append(row('Cancel',390,260,50))
            else:source['tag']='UNKNOWN'
            with self.subTest(mode=mode):self.assertFalse(classify_information(o,[source])['supported'])

    def test_actual_original_012_notice_and_resource_pin(self):
        p=Path('runs/attempt-012/screens/ui-0001246.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame absent')
        from civ2.observe import recognize
        from civ2.dialogs import classify_dialog,dialog_resources
        from civ2.run import game_text
        from civ2.evidence import canonical
        import hashlib
        d=classify_dialog(recognize(p),game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'SURPRISEMERCS')
        self.assertFalse(d['requires_model']);self.assertEqual([x['text'] for x in d['options']],['OK'])
        self.assertNotIn('unit_type',d);self.assertNotIn('unit_id',d)
        source=next(r for r in dialog_resources(game_text()) if r['tag']=='SURPRISEMERCS')
        self.assertEqual(source,SOURCE)
        self.assertEqual(hashlib.sha256(canonical(source)).hexdigest(),'c2385ac58008bbaa30cc7126e827fc322a1c8d9ceb21d7db5697be0740290195')

if __name__=='__main__':unittest.main()
