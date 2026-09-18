"""Complete original informational prose, with synthetic and private-frame checks."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from zipfile import ZipFile

from civ2.dialogs import classify_dialog, dialog_resources
from civ2.evidence import canonical
from civ2.native_events import classify_information, PHILOSOPHY_NOTICE_RESOURCES
from test_native_events import notice, row


SOURCE = dict(tag='GOLDENAGE',title='Golden Age of Philosophy',width=320,
    body='The Golden Age of Philosophy begins in the %STRING0 city of %STRING1! Great %STRING0 thinkers articulate scientific, moral, and metaphysical systems which endure for centuries to come.',
    options=[],buttons=[],listbox=False)
BODY = ['The Golden Age of Philosophy begins in the',
        'Sioux city of Little Bighorn! Great Sioux',
        'thinkers articulate scientific, moral, and',
        'metaphysical systems which endure for', 'centuries to come.']
GAME = '@GOLDENAGE\n@width=320\n@title=Golden Age of Philosophy\n'+SOURCE['body']+'\n\n'


class GoldenAgeNotice(unittest.TestCase):
    def screen(self):
        # Real wrap count, synthetic pixel coordinates; the optional live test
        # below reads the original captured image without controlling a game.
        return notice(*BODY,title=SOURCE['title'])

    def test_complete_foreign_notice_preserves_text_and_only_acknowledges(self):
        screen=self.screen();before=deepcopy(screen)
        result=classify_dialog(screen,game_text=GAME)
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['kind'],'information')
        self.assertEqual(result['resource_tag'],'GOLDENAGE')
        self.assertFalse(result['requires_model'])
        self.assertEqual(result['mechanical_action'],'acknowledge_information')
        self.assertEqual([r['text'] for r in result['options']],['OK'])
        self.assertEqual(result['evidence']['observed_body'],'\n'.join(BODY))
        self.assertIsNone(result['outcome'])
        self.assertEqual(before,screen)

    def test_title_partial_prose_repeated_identity_and_extra_controls_fail_closed(self):
        for mode in ('title_only','partial','period','repeated_identity','extra_prose','cancel','second_ok','confidence','geometry','second_heading'):
            screen=self.screen()
            if mode=='title_only':screen['lines']=screen['lines'][::len(screen['lines'])-1]
            elif mode=='partial':screen['lines'].pop(3)
            elif mode=='period':screen['lines'][-2]['text']='centuries to come'
            elif mode=='repeated_identity':screen['lines'][2]['text']='Sioux city of Little Bighorn! Great Roman'
            elif mode=='extra_prose':screen['lines'].insert(-1,row('Choose the next scientific advance.',y=230))
            elif mode=='cancel':screen['lines'][-1]['text']='Cancel'
            elif mode=='second_ok':screen['lines'].append(row('OK',y=280,width=25))
            elif mode=='confidence':screen['lines'][2]['confidence']=.7
            elif mode=='geometry':screen['lines'][-1]=row('OK',x=540,y=240,width=25)
            else:screen['lines'].append(row('Domestic Advisor',y=30))
            with self.subTest(mode=mode):
                result=classify_information(screen,[SOURCE])
                self.assertFalse(result['supported'],result)
                self.assertIsNone(result['mechanical_action'])

    def test_source_changes_cannot_turn_information_into_strategic_choice(self):
        for delta in ({'options':['Choose science','Refuse']},{'buttons':['OK','Cancel']},
                      {'listbox':True},{'width':340},{'body':SOURCE['body']+' Choose a reward.'}):
            self.assertFalse(classify_information(self.screen(),[{**SOURCE,**delta}])['supported'])

    def test_exact_original_source_and_portable_verifier_pin(self):
        from civ2.verify import PUBLIC_NOTICE_RESOURCES
        self.assertEqual(dialog_resources(GAME),[SOURCE])
        digest=hashlib.sha256(canonical(SOURCE)).hexdigest()
        self.assertEqual(PHILOSOPHY_NOTICE_RESOURCES['GOLDENAGE'],digest)
        self.assertEqual(PUBLIC_NOTICE_RESOURCES['GOLDENAGE'],digest)
        path=Path('engine/game/civ2-win31.zip')
        if not path.exists():self.skipTest('Private original source unavailable')
        with ZipFile(path) as z:records=dialog_resources(z.read('civ2/GAME.TXT').decode('cp1252'))
        self.assertEqual([r for r in records if r['tag']=='GOLDENAGE'],[SOURCE])

    def test_actual_010_sioux_notice_is_complete_without_ocr_replacement(self):
        path=Path('runs/attempt-010/screens/ui-0002898.png')
        if not path.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame/OCR unavailable')
        from civ2.observe import recognize
        from civ2.run import game_text
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         'fac1c82c3c4d3bb8aabed7f787a24b8226dfa9ea9eeae68fc9e977376f844ac3')
        observation=recognize(path);before=deepcopy(observation)
        result=classify_dialog(observation,game_text=game_text())
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['resource_tag'],'GOLDENAGE')
        self.assertEqual(result['evidence']['title_match'],'exact')
        self.assertEqual(result['evidence']['observed_body'],'\n'.join(BODY))
        self.assertEqual([r['text'] for r in result['options']],['OK'])
        self.assertFalse(result['requires_model']);self.assertIsNone(result['outcome'])
        self.assertEqual(observation,before)


if __name__=='__main__':unittest.main()
