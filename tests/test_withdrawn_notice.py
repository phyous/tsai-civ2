"""Completed native withdrawal notices are information, never a withdrawal order."""
from copy import deepcopy
from pathlib import Path
import unittest
from civ2.native_events import classify_information
from test_treaty_reminder import row


def source(plural=False):
    return dict(tag='WITHDRAWN' if plural else 'WITHDRAWN1',title='Foreign Minister',width=320,
        body=('%NUMBER0 offending units have' if plural else 'One offending unit has')+
             ' been withdrawn to our nearest cities.',options=[],buttons=[],listbox=False)


def observation(plural=False):
    return dict(width=640,height=480,sha256='a'*64,lines=[
        row('Foreign Minister' if plural else 'Foreign Ifinister',270,184,102),
        row(('3 offending units have' if plural else 'One offending unit has')+' been withdrawn to our',196,210,304),
        row('nearest cities.',196,230,100),row('OK',308,282,24)])


class WithdrawalNoticeTests(unittest.TestCase):
    def test_complete_singular_and_numeric_plural_are_sole_ok_information(self):
        for plural in (False,True):
            d=classify_information(observation(plural),[source(plural)])
            self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'information')
            self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
            self.assertEqual([r['text'] for r in d['options']],['OK'])

    def test_partial_warning_substituted_quantity_and_extra_choices_fail(self):
        for mode in ('partial','warning','words','choice','wrong_title'):
            o=observation(True)
            if mode=='partial':o['lines'].pop(2)
            elif mode=='warning':o['lines'][1]['text']='3 offending units must withdraw now.'
            elif mode=='words':o['lines'][1]['text']=o['lines'][1]['text'].replace('3','Unknown')
            elif mode=='choice':o['lines'].insert(-1,row('Break treaty.',230,255,100))
            else:o['lines'][0]['text']='Defense Minister'
            with self.subTest(mode=mode):self.assertFalse(classify_information(o,[source(True)])['supported'])

    def test_actual_notice_and_original_resource_hash(self):
        p=Path('runs/attempt-011/screens/ui-0001629.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame absent')
        from civ2.run import game_text
        from civ2.observe import recognize
        from civ2.dialogs import classify_dialog,dialog_resources
        from civ2.evidence import canonical
        import hashlib
        d=classify_dialog(recognize(p),game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'WITHDRAWN1')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        for plural,digest in ((False,'4c421e4792122802c137b96942417f429e650aa44bfddf11044e6fdc9f2ab4e3'),
                             (True,'b0ecb0d1a79f8a79bfa66ff6e1e07cde67476088c1e80908a6cf6f89b4e117ec')):
            r=next(r for r in dialog_resources(game_text()) if r['tag']==source(plural)['tag'])
            self.assertEqual(r,source(plural));self.assertEqual(hashlib.sha256(canonical(r)).hexdigest(),digest)


if __name__=='__main__':unittest.main()
