"""Source/choice guards and optional original one-contact F3 regressions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from PIL import Image
from civ2.dialogs import _rows
from civ2.evidence import canonical
from civ2.foreign_report import (SOURCE,SOURCE_SHA256,POWERS,REPUTATIONS,RELATIONS,
                                _pixels,classify_foreign_report)


def fixture():
    def row(text,x,y,w,h):
        return dict(text=text,bounds=[x,y,w,h],center=[x+w//2,y+h//2],confidence=1.)
    observation=dict(width=640,height=480,sha256='a'*64,lines=[
        row('Foreign Minisber',270,190,102,18),
        row('Sire, our power is Supreme and our reputation is Spotless.',30,214,386,16),
        row('Emperor TEST Leader of the TEST Tribe (Enthusiastic, Peace, No Embassy)',68,240,470,18),
        row('Check Intelligence',70,274,112,16),row('Send Emissary',276,274,90,17),
        row('Cancel',498,274,42,14)])
    labels=['']*251;labels[7:11]=['@POPUPS','OK','Help','Cancel']
    labels[157:162]=[*RELATIONS,'No Embassy'];labels[236:251]=[*REPUTATIONS,*POWERS]
    rules={'leaders':[{'male':'TEST Leader','female':'TEST Other','tribe':'TEST Tribe'}]}
    return observation,[deepcopy(SOURCE)],rules,'\n'.join(labels)


class ForeignReportTests(TestCase):
    def classify(self,o,s,r,l):
        return classify_foreign_report(o,_rows(o),s,r,l)

    def test_original_source_pin_and_all_buttons_need_separate_model_choice(self):
        self.assertEqual(hashlib.sha256(canonical(SOURCE)).hexdigest(),SOURCE_SHA256)
        o,s,r,l=fixture()
        # Public fixtures test semantic/geometry guards independently from the
        # separately exercised original-pixel calibration below.
        with patch('civ2.foreign_report._pixels',return_value=[{'test':'pixel proof'}]):
            result=self.classify(o,s,r,l)
        self.assertEqual(result['kind'],'foreign_minister')
        self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
        self.assertEqual([x['text'] for x in result['options']],['Check Intelligence','Send Emissary','Cancel'])
        self.assertTrue(all(x['control']=='button' for x in result['options']))
        proof=result['evidence']['foreign_report']
        self.assertEqual(proof['selected_contact'],{'leader':'TEST Leader','tribe':'TEST Tribe'})
        self.assertEqual(proof['observed_title'],'Foreign Minisber')
        self.assertNotIn('civ_id',proof['selected_contact'])
        self.assertEqual(result['options'][1]['center'],o['lines'][4]['center'])

    def test_missing_or_added_contact_control_and_unknown_heading_fail_closed(self):
        for case in ('missing_contact','missing_button','extra_contact','extra_control','title','low_confidence','overlap','radio_failure'):
            with self.subTest(case=case):
                o,s,r,l=fixture()
                if case=='missing_contact':o['lines'].pop(2)
                elif case=='missing_button':o['lines'].pop(4)
                elif case=='extra_contact':o['lines'].append(deepcopy(o['lines'][2]))
                elif case=='extra_control':o['lines'].append(deepcopy(o['lines'][4]))
                elif case=='title':o['lines'][0]['text']='Foreign Anything'
                elif case=='low_confidence':o['lines'][2]['confidence']=.7
                elif case=='overlap':o['lines'][2]['bounds'][0]=19
                with patch('civ2.foreign_report._pixels',return_value=None if case=='radio_failure' else []):
                    self.assertIsNone(self.classify(o,s,r,l))

    def test_source_body_leader_tribe_labels_and_button_changes_reject(self):
        for case in ('source','duplicate_source','source_option','body','leader','tribe','label','button','embassy'):
            with self.subTest(case=case):
                o,s,r,l=fixture()
                if case=='source':s[0]['width']=320
                elif case=='duplicate_source':s.append(deepcopy(s[0]))
                elif case=='source_option':s[0]['options']=['Another choice']
                elif case=='body':o['lines'][1]['text']=o['lines'][1]['text'].replace('Supreme','Imagined')
                elif case=='leader':r['leaders'][0]['male']='Different Leader'
                elif case=='tribe':r['leaders'][0]['tribe']='Different Tribe'
                elif case=='label':l=l.replace('No Embassy','Embassy')
                elif case=='button':o['lines'][4]['text']='Send Mission'
                else:o['lines'][2]['text']=o['lines'][2]['text'].replace('No Embassy','Embassy')
                with patch('civ2.foreign_report._pixels',return_value=[]):self.assertIsNone(self.classify(o,s,r,l))

    def test_moved_button_or_unmeasured_multi_contact_frame_never_authorizes_input(self):
        o,s,r,l=fixture();o['lines'][4]['center'][0]+=20;o['lines'][4]['bounds'][0]+=20
        with patch('civ2.foreign_report._pixels',return_value=[]):self.assertIsNone(self.classify(o,s,r,l))
        with TemporaryDirectory() as directory:
            path=Path(directory)/'frame.png';Image.new('RGB',(640,480)).save(path)
            o['path']=str(path);o['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertIsNone(_pixels(o))
            o['sha256']='a'*64;self.assertIsNone(_pixels(o))

    def test_actual_two_original_reports_and_pixel_tampering(self):
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import dialog_resources
        from civ2.observe import recognize
        paths=[Path('.runtime/foreign-minister-calibration-01/screens/ui-0000014.png'),
               Path('runs/attempt-010/screens/ui-0001942.png')]
        if not all(p.exists() for p in paths):self.skipTest('Private original captures unavailable')
        resources=dialog_resources(game_text());rules=parse_rules(original_rules());labels=labels_text()
        for path,tribe in zip(paths,('Vikings','Germans')):
            with self.subTest(path=path):
                o=recognize(path);o['path']=str(path)
                result=self.classify(o,resources,rules,labels)
                self.assertIsNotNone(result)
                self.assertEqual(result['evidence']['foreign_report']['selected_contact']['tribe'],tribe)
                self.assertEqual(len(result['options']),3)
                with TemporaryDirectory() as directory:
                    for point in ((48,248),(20,183),(621,250),(500,262)):
                        image=Image.open(path).convert('RGB');rgb=image.getpixel(point)
                        image.putpixel(point,(rgb[0]^1,rgb[1],rgb[2]))
                        bad=Path(directory)/'changed.png';image.save(bad)
                        mutated=deepcopy(o);mutated['path']=str(bad)
                        mutated['sha256']=hashlib.sha256(bad.read_bytes()).hexdigest()
                        self.assertIsNone(self.classify(mutated,resources,rules,labels))
                o['sha256']='f'*64
                self.assertIsNone(self.classify(o,resources,rules,labels))
