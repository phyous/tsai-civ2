"""Synthetic and optional actual INTRUDER pixels; no inferred troop movement."""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase,mock
from PIL import Image
from civ2 import observe

GAME='''@INTRUDER
@title=%STRING0 Emissary
@width=320
"Your troops have violated the territory of our city of %STRING1.  By the terms of our peace treaty, you must withdraw immediately or face the consequences!"

'''

def row(text,x,y,w=312,h=18):
    return dict(text=text,bounds=[x,y,w,h],center=[x+w//2,y+h//2],confidence=1,
                provenance=[{'text':text,'preprocessing':'native'}])


def notice():
    return [row('TEST German Emissary',230,174,180),
            row('"Your troops have violated the territory of ou',194,198),
            row('city of TEST Hamburg. By the terms of our peace',194,218),
            row('treaty, you must withdraw immediately or face',194,238),
            row('the consequences!"',194,258),row('OK',308,288,24)]


class IntruderPixelsTests(TestCase):
    def test_damaged_title_suffix_requires_full_prefix_and_atomic_body_reads(self):
        for mode in ('valid','nation','attitude','suffix','disagree','body'):
            rows=notice();rows[0]['text']='TEST German Emisoary'
            title=deepcopy(rows[0]);title['text']='TEST German Emissary';other=deepcopy(title)
            if mode=='nation':title['text']=other['text']='TEST Zulu Emissary'
            if mode=='attitude':title['text']=other['text']='OTHER German Emissary'
            if mode=='suffix':title['text']=other['text']='TEST German Emisoary'
            if mode=='disagree':other['text']='TEST German Emisoary'
            first=deepcopy(rows[1]);first['text']+='r';second=deepcopy(first)
            if mode=='body':second['text']=second['text'].replace('troops','ships')
            with mock.patch.object(observe,'_crop_text',side_effect=[[title],[other],[first],[second]]):
                observe._recover_intruder_notice(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[0]['text'],'TEST German Emissary' if mode=='valid' else 'TEST German Emisoary')
            self.assertEqual(rows[1]['text'],first['text'] if mode=='valid' else notice()[1]['text'])

    def test_original_011_damaged_suffix_preserves_observed_nation(self):
        path=Path('runs/attempt-011/screens/ui-0003354.png')
        if not path.exists():self.skipTest('Private original calibration unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(path);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'INTRUDER')
        self.assertEqual(d['mechanical_action'],'acknowledge_information');self.assertFalse(d['requires_model'])
        title=next(r for r in o['lines'] if r['text']=='Uncooperative Zuln Emissary')
        self.assertEqual(title['provenance'][0]['text'],'Uncooperative Zuln Emisoary')
        self.assertEqual([p['preprocessing'] for p in title['provenance'][1:]],
                         ['intruder_title_rgb2','intruder_title_gray2'])

    def test_source_bound_warning_can_enter_existing_public_notice_history(self):
        import hashlib,json,tempfile
        from civ2.dialogs import classify_dialog,dialog_resources
        from civ2.evidence import Journal,canonical
        from civ2.verify import PUBLIC_NOTICE_RESOURCES
        from tests.test_session import session
        rows=notice();rows[1]['text']+='r'
        with tempfile.TemporaryDirectory() as directory:
            s=session();s.journal=Journal(Path(directory)/'TEST-run');s.checkpoints=1
            p=s.journal.directory/'screens/TEST.png';p.parent.mkdir();Image.new('RGB',(640,480),'gray').save(p)
            o=dict(width=640,height=480,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),path=str(p),lines=rows)
            d=classify_dialog(o,game_text=GAME)
            self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'information')
            captured=s.remember_public_notice(o,d,GAME)
            self.assertEqual(captured['resource_tag'],'INTRUDER')
            self.assertIn('TEST Hamburg',captured['observed_text'])
            self.assertEqual(hashlib.sha256(canonical(dialog_resources(GAME)[0])).hexdigest(),PUBLIC_NOTICE_RESOURCES['INTRUDER'])
            s.game.rpc.assert_not_called();s.journal.close()

    def test_complete_notice_needs_two_unchanged_source_word_readings(self):
        for bad in (False,True):
            rows=notice();a=deepcopy(rows[1]);a['text']+='r';b=deepcopy(a)
            if bad:b['text']=b['text'].replace('troops','ships')
            with mock.patch.object(observe,'_crop_text',side_effect=[[a],[b]]):
                observe._recover_intruder_notice(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[1]['text'],notice()[1]['text'] if bad else a['text'])

    def test_missing_warning_or_additional_choice_rejects_before_crop(self):
        for mode in ('body','choice','title'):
            rows=notice()
            if mode=='body':rows.pop(3)
            elif mode=='choice':rows.append(row('Cancel',340,288,50))
            else:rows[0]['text']='TEST Domestic Advisor'
            with mock.patch.object(observe,'_crop_text') as crop:
                observe._recover_intruder_notice(Image.new('RGB',(640,480)),rows,None,None,{})
            crop.assert_not_called()

    def test_original_010_notice_remains_source_matched_information(self):
        path=Path('runs/attempt-010/screens/ui-0001883.png')
        if not path.exists():self.skipTest('Private original calibration unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(path);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'INTRUDER')
        self.assertEqual(d['kind'],'information')
        self.assertEqual(d['evidence']['source_tag'],'INTRUDER')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        first=next(r for r in o['lines'] if r['text'].startswith('"Your troops'))
        self.assertEqual(first['provenance'][0]['text'],'"Your troops have violated the territory of ou')
        self.assertEqual(len(first['provenance']),3)
