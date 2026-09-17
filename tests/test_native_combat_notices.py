"""Source-bound synthetic combat notices; no live calibration or game inputs."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from zipfile import ZipFile

from civ2.dialogs import classify_dialog, dialog_resources
from civ2.evidence import canonical
from civ2.native_events import classify_information, COMBAT_NOTICE_RESOURCES
from civ2.verify import PUBLIC_NOTICE_RESOURCES
from tests.test_native_events import notice, row


def source(tag, title, body, width=300):
    return dict(tag=tag,title=title,body=body,width=width,options=[],buttons=[],listbox=False)


SOURCES = {
    'CITYCAPTURE':source('CITYCAPTURE','Defense Minister',
        '%STRING1 %STRING3 %STRING0.  %NUMBER0 gold pieces plundered.'),
    'MULTIPLEWIN':source('MULTIPLEWIN','Defense Minister','%NUMBER0 units destroyed.'),
    'MULTIPLELOSE':source('MULTIPLELOSE','Defense Minister','%NUMBER0 units were lost.'),
    'TOOKCIV':source('TOOKCIV','Civilization Advance Stolen!','%STRING0 take %STRING1!',320),
}
BODIES = {
    'CITYCAPTURE':['TEST Romans capture TEST Hamburg.', '25 gold pieces plundered.'],
    'MULTIPLEWIN':['3 units destroyed.'],
    'MULTIPLELOSE':['2 units were lost.'],
    'TOOKCIV':['TEST Romans take Masonry!'],
}
GAME = ''.join(f"@{s['tag']}\n@width={s['width']}\n@title={s['title']}\n{s['body']}\n\n"
               for s in SOURCES.values())


class CombatNotices(unittest.TestCase):
    def test_complete_reports_only_offer_the_actual_acknowledgement(self):
        self.assertEqual(dialog_resources(GAME),list(SOURCES.values()))
        for tag,body in BODIES.items():
            with self.subTest(tag=tag):
                screen=notice(*body,title=SOURCES[tag]['title']);before=deepcopy(screen)
                result=classify_dialog(screen,game_text=GAME)
                self.assertTrue(result['supported'],result)
                self.assertEqual(result['resource_tag'],tag)
                self.assertEqual(result['kind'],'information')
                self.assertEqual(result['mechanical_action'],'acknowledge_information')
                self.assertFalse(result['requires_model'])
                self.assertEqual([o['text'] for o in result['options']],['OK'])
                self.assertEqual(result['evidence']['observed_body'],'\n'.join(body))
                self.assertIsNone(result['outcome'])
                self.assertEqual(screen,before)

    def test_missing_body_punctuation_and_extra_foreground_choices_fail_closed(self):
        for tag,body in BODIES.items():
            base=notice(*body,title=SOURCES[tag]['title'])
            for mode in ('missing','punctuation','terms','option','second_ok','misaligned','low','conflict'):
                with self.subTest(tag=tag,mode=mode):
                    screen=deepcopy(base)
                    if mode=='missing':screen['lines'].pop(1)
                    elif mode=='punctuation':screen['lines'][-2]['text']=screen['lines'][-2]['text'][:-1]
                    elif mode=='terms':screen['lines'].insert(-1,row('Pay 25 gold to continue.',y=195))
                    elif mode=='option':screen['lines'].insert(-1,row('Keep the city.',y=195))
                    elif mode=='second_ok':screen['lines'].append(row('OK',y=275,width=25))
                    elif mode=='misaligned':screen['lines'][-1]=row('OK',x=520,y=240,width=25)
                    elif mode=='low':screen['lines'][1]['confidence']=.7
                    else:screen['ocr']={'conflicts':[dict(text='Cancel',bounds=[300,170,35,14])]}
                    result=classify_information(screen,list(SOURCES.values()))
                    self.assertFalse(result['supported'],result)
                    self.assertIsNone(result['mechanical_action'])
                    self.assertEqual(result['options'],[])

    def test_original_template_is_pinned_and_never_drops_native_alternatives(self):
        for tag,body in BODIES.items():
            screen=notice(*body,title=SOURCES[tag]['title'])
            self.assertFalse(classify_information(screen,[])['supported'])
            for updates in (dict(width=440),dict(body=SOURCES[tag]['body']+' Continue.'),
                            dict(title='TEST altered title'),dict(options=['Accept','Refuse']),
                            dict(buttons=['OK','Cancel']),dict(listbox=True)):
                with self.subTest(tag=tag,updates=updates):
                    record={**SOURCES[tag],**updates}
                    self.assertFalse(classify_information(screen,[record])['supported'])

    def test_capture_verb_is_from_original_label_catalog_not_an_unbounded_placeholder(self):
        record=SOURCES['CITYCAPTURE']
        for verb in ('capture','liberate','captured','liberated','choose','surrender','pay'):
            screen=notice(f'TEST Romans {verb} TEST Hamburg.','25 gold pieces plundered.',title=record['title'])
            result=classify_information(screen,[record],placeholder_values={'CITYCAPTURE':{'STRING3':['choose']}})
            self.assertEqual(result['supported'],verb in ('capture','liberate','captured','liberated'))

    def test_numeric_report_and_technology_report_cannot_be_swapped_or_shortened(self):
        for tag,body in (('MULTIPLEWIN','Units destroyed.'),('MULTIPLEWIN','3 units were lost.'),
                         ('MULTIPLELOSE','2 units destroyed.'),('CITYCAPTURE','25 gold pieces plundered.'),
                         ('TOOKCIV','TEST Romans take!'),('TOOKCIV','TEST Romans give Masonry!')):
            with self.subTest(tag=tag,body=body):
                record=SOURCES[tag]
                self.assertFalse(classify_information(notice(body,title=record['title']),[record])['supported'])

    def test_classifier_and_independent_verifier_pin_exact_resource_records(self):
        for tag,record in SOURCES.items():
            digest=hashlib.sha256(canonical(record)).hexdigest()
            self.assertEqual(COMBAT_NOTICE_RESOURCES[tag],digest)
            self.assertEqual(PUBLIC_NOTICE_RESOURCES[tag],digest)

    def test_private_original_records_and_capture_verb_labels_match_reviewed_sources(self):
        path=Path(__file__).resolve().parents[1]/'engine/game/civ2-win31.zip'
        if not path.is_file():self.skipTest('Private original source unavailable')
        with ZipFile(path) as archive:
            originals=dialog_resources(archive.read('civ2/GAME.TXT').decode('cp1252'))
            labels=archive.read('civ2/LABELS.TXT').decode('cp1252').splitlines()
        for tag,record in SOURCES.items():
            self.assertEqual([r for r in originals if r['tag']==tag],[record])
        self.assertEqual(labels[190:194],['capture','liberate','captured','liberated'])


if __name__=='__main__':unittest.main()
