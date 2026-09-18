"""Original BUILT2 is a public announcement, with no production decision."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.dialogs import classify_dialog,dialog_resources
from civ2.evidence import canonical
from civ2.native_events import classify_information,FOREIGN_NOTICE_RESOURCES
from civ2.verify import PUBLIC_NOTICE_RESOURCES
from tests.test_herald import prepared


GAME='@BUILT2\n@title=Foreign Advisor\n%STRING0 (%STRING2) %STRING3 %STRING1.\n'


def frame():
    return {'width':640,'height':480,'sha256':'a'*64,'lines':[
        prepared('Foreign Advisor',270,196,100,16),
        prepared('Berlin (German) builds Pyramids.',140,218,235,16),
        prepared('OK',309,270,22,16)]}


class ForeignCompletionTests(unittest.TestCase):
    def test_pinned_original_source_complete_body_and_finite_verb(self):
        r=dialog_resources(GAME)[0]
        self.assertEqual(hashlib.sha256(canonical(r)).hexdigest(),FOREIGN_NOTICE_RESOURCES['BUILT2'])
        self.assertEqual(FOREIGN_NOTICE_RESOURCES['BUILT2'],PUBLIC_NOTICE_RESOURCES['BUILT2'])
        for case in ('valid','changed_source','extra_control','missing_body','unknown_verb','missing_tribe','question'):
            o=frame();game=GAME
            if case=='changed_source':game=game.replace('%STRING0','The %STRING0')
            if case=='extra_control':o['lines'].append(prepared('Cancel',300,290,40,16))
            if case=='missing_body':o['lines'].pop(1)
            if case=='unknown_verb':o['lines'][1]['text']='Berlin (German) destroys Pyramids.'
            if case=='missing_tribe':o['lines'][1]['text']='Berlin builds Pyramids.'
            if case=='question':o['lines'][1]['text']='Berlin (German) builds Pyramids?'
            d=classify_dialog(o,game_text=game)
            self.assertEqual(d['supported'],case=='valid',case)
            if case=='valid':
                self.assertEqual(d['resource_tag'],'BUILT2');self.assertEqual(d['kind'],'information')
                self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertFalse(classify_information(frame(),[r])['supported'])

    def test_title_needs_two_actual_pixel_reads(self):
        for case in ('valid','disagree','moved','missing_body','extra_control'):
            rows=frame()['lines'];rows[0]['text']='Foreign Adrisor'
            rows[0]['provenance'][0]['text']='Foreign Adrisor'
            if case=='missing_body':rows.pop(1)
            if case=='extra_control':rows.append(prepared('Yes',200,270,20,16))
            a=prepared('Foreign Advisor',270,196,100,16);b=deepcopy(a)
            if case=='disagree':b['text']='Foreign Adrisor'
            if case=='moved':b['center'][1]+=20;b['bounds'][1]+=20
            with patch.object(observe,'_crop_text',side_effect=[[a],[b]]):
                observe._recover_foreign_completion_title(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[0]['text'],'Foreign Advisor' if case=='valid' else 'Foreign Adrisor',case)

    def test_actual_pyramids_announcement(self):
        path=Path('runs/attempt-010/screens/ui-0002354.png')
        if not path.exists():self.skipTest('Private original image unavailable')
        from civ2.run import game_text,labels_text
        o=observe.recognize(path)
        d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'BUILT2')
        self.assertEqual(d['evidence']['observed_body'],'Berlin (German) builds Pyramids.')
        title=next(r for r in o['lines'] if r['text']=='Foreign Advisor')
        self.assertEqual([p['text'] for p in title['provenance']],['Foreign Adrisor','Foreign Advisor','Foreign Advisor'])


if __name__=='__main__':unittest.main()
