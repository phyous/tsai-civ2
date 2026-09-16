"""Reviewed informational-only civilization-destruction notice; no strategic choice."""
from copy import deepcopy
from pathlib import Path
import unittest

from civ2.dialogs import classify_dialog,dialog_resources
from civ2.native_events import classify_information


SOURCE='@DESTROYED\n@title=Defense Minister\n%STRING0 civilization destroyed by %STRING1.\n'


def fixture():
    def row(text,x,y,w):
        return {'text':text,'center':[x,y],'bounds':[x-w//2,y-7,w,14],'confidence':1}
    rows=[row('Detense ifinister',320,190,106),
          row('TEST Egyptian civilization destroyed by TEST Americans.',310,220,400),
          row('OK',320,289,24)]
    return {'width':640,'height':480,'sha256':'a'*64,'lines':rows,'text':'\n'.join(r['text'] for r in rows)}


class DestroyedNoticeTests(unittest.TestCase):
    def test_full_original_information_preserves_raw_title_and_never_requests_model(self):
        result=classify_information(fixture(),dialog_resources(SOURCE))
        self.assertTrue(result['supported']);self.assertEqual(result['resource_tag'],'DESTROYED')
        self.assertEqual(result['kind'],'information');self.assertFalse(result['requires_model'])
        self.assertEqual(result['mechanical_action'],'acknowledge_information')
        self.assertEqual(result['title'],'Detense ifinister')
        self.assertIn('TEST Egyptian',result['evidence']['observed_body'])

    def test_partial_body_extra_option_unknown_title_or_different_resource_rejected(self):
        for mutation in ('missing_body','strategic_option','wrong_title','missing_ok','different_body','two_titles'):
            o=fixture()
            if mutation=='missing_body':o['lines'].pop(1)
            elif mutation=='strategic_option':o['lines'].insert(2,{'text':'Declare War','center':[320,250],'bounds':[270,243,100,14],'confidence':1})
            elif mutation=='wrong_title':o['lines'][0]['text']='Defense options'
            elif mutation=='missing_ok':o['lines'].pop()
            elif mutation=='different_body':o['lines'][1]['text']='TEST Egyptian demands tribute.'
            else:o['lines'].append({'text':'Defense Minister','center':[320,90],'bounds':[260,83,120,14],'confidence':1})
            with self.subTest(mutation=mutation):self.assertFalse(classify_information(o,dialog_resources(SOURCE))['supported'])
        self.assertFalse(classify_information(fixture(),dialog_resources(SOURCE+'\nAccept treaty.\n'))['supported'])

    def test_only_sentence_final_period_is_optional_and_raw_body_is_retained(self):
        o=fixture();o['lines'][1]['text']=o['lines'][1]['text'].rstrip('.')
        result=classify_information(o,dialog_resources(SOURCE))
        self.assertTrue(result['supported']);self.assertFalse(result['evidence']['observed_body'].endswith('.'))
        for text in ('TEST Egyptian civilization destroyed by', 'TEST Egyptian destroyed by TEST Americans',
                     'TEST Egyptian civilization destroyed by TEST Americans?',
                     'TEST Egyptian civilization destroyed by TEST Americans. Declare war.'):
            bad=deepcopy(o);bad['lines'][1]['text']=text
            self.assertFalse(classify_information(bad,dialog_resources(SOURCE))['supported'],text)

    def test_optional_original006_notice(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        root=Path(__file__).resolve().parents[1]
        for name in ('ui-0000608.png','ui-0000734.png'):
            p=root/'runs/attempt-006/screens'/name
            if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original notice unavailable')
            result=classify_dialog(recognize(p),game_text=game_text())
            self.assertTrue(result['supported'],result);self.assertEqual(result['resource_tag'],'DESTROYED')
            self.assertEqual(result['kind'],'information')
