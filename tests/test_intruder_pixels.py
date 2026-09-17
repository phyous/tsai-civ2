"""Synthetic and optional actual INTRUDER pixels; no inferred troop movement."""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase,mock
from PIL import Image
from civ2 import observe


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
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        first=next(r for r in o['lines'] if r['text'].startswith('"Your troops'))
        self.assertEqual(first['provenance'][0]['text'],'"Your troops have violated the territory of ou')
        self.assertEqual(len(first['provenance']),3)
