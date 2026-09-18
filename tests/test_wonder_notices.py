"""Synthetic TEST public wonder reports and optional original notice."""
import copy
from pathlib import Path
import hashlib
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.native_events import classify_information
from civ2.dialogs import classify_dialog
from tests.test_herald import prepared
from tests.test_native_events import resource,notice


class WonderNoticeTests(unittest.TestCase):
    def test_all_four_original_wonder_notices_have_independent_audit_pins(self):
        from civ2.evidence import canonical
        from civ2.verify import PUBLIC_NOTICE_RESOURCES
        bodies={'STARTWONDER':'The %STRING1 have undertaken a great project: %STRING2!',
                'SWITCHWONDER':'The %STRING1 have changed projects from %STRING2 to %STRING3!',
                'ABANDONWONDER':'The %STRING1 have abandoned their great project, %STRING2.',
                'ALMOSTWONDER':'The %STRING1 have nearly completed their great project, %STRING2.'}
        for tag,body in bodies.items():
            source=dict(tag=tag,title='Travellers Report',width=320,body=body,options=[],buttons=[],listbox=False)
            self.assertEqual(PUBLIC_NOTICE_RESOURCES[tag],hashlib.sha256(canonical(source)).hexdigest())

    def test_only_complete_original_informational_wonder_templates_are_supported(self):
        cases=[('STARTWONDER','The %STRING1 have undertaken a great project: %STRING2!',
                'The TEST Romans have undertaken a great project: TEST Wonder!'),
               ('SWITCHWONDER','The %STRING1 have changed projects from %STRING2 to %STRING3!',
                'The TEST Romans have changed projects from TEST One to TEST Two!'),
               ('ABANDONWONDER','The %STRING1 have abandoned their great project, %STRING2.',
                'The TEST Romans have abandoned their great project, TEST Wonder.'),
               ('ALMOSTWONDER','The %STRING1 have nearly completed their great project, %STRING2.',
                'The TEST Romans have nearly completed their great project, TEST Wonder.')]
        for tag,body,text in cases:
            source=resource(tag=tag,title='Travellers Report',body=body)
            screen=notice(text,title='Travellers Report')
            d=classify_information(screen,[source]);self.assertTrue(d['supported'],d)
            self.assertEqual(d['resource_tag'],tag);self.assertFalse(d['requires_model'])
            self.assertEqual(d['mechanical_action'],'acknowledge_information')
            self.assertFalse(classify_information(notice(text.replace(' have ',' '),title='Travellers Report'),[source])['supported'])
            self.assertFalse(classify_information(screen,[{**source,'options':['Pay gold','Refuse']}])['supported'])
            self.assertFalse(classify_information(screen,[{**source,'tag':'TEST_UNKNOWN'}])['supported'])

    def test_report_title_needs_exact_paired_pixels_and_visible_report_body(self):
        base=[prepared('Dravellers Report',264,196,112,16),
              prepared('The TEST Romans have undertaken a great',206,220,250,16),
              prepared('project: TEST Wonder!',206,240,180,16),prepared('OK',309,286,24,14)]
        good=prepared('Travellers Report',264,196,112,16)
        for case in ('good','different','partial','extra','weak'):
            rows=copy.deepcopy(base);peer=copy.deepcopy(good)
            if case=='different':peer['text']='Travellers Reports'
            if case=='partial':rows[1]['text']='The TEST Romans request tribute'
            if case=='extra':rows.append(prepared('No',400,286,24,14))
            if case=='weak':peer['confidence']=.5
            with patch.object(observe,'_crop_text',side_effect=[[good],[peer]]):
                observe._recover_travellers_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],good['text'] if case=='good' else base[0]['text'],case)

    def test_abandon_word_requires_paired_pixels_and_preserves_nation_and_project(self):
        base=[prepared('Dravellers Report',264,196,112,16),
              prepared('The TEST Romans have ahandoned their great project,',200,220,308,16),
              prepared('TEST Wonder.',200,240,180,16),prepared('OK',309,272,24,14)]
        for case in ('valid','nation','verb','peer','weak','missing_tail','extra_control'):
            rows=copy.deepcopy(base)
            if case=='missing_tail':rows.pop(2)
            if case=='extra_control':rows.append(prepared('No',400,272,24,14))
            before=copy.deepcopy(rows)
            def crop(image,old,name,*args,**kwargs):
                r=copy.deepcopy(old)
                if '_title_' in name:r['text']='Travellers Report'
                else:
                    r['text']='The TEST Romans have abandoned their great project,'
                    if case=='nation':r['text']=r['text'].replace('Romans','OTHER')
                    if case=='verb':r['text']=r['text'].replace('abandoned','undertaken')
                    if case=='peer' and kwargs.get('grayscale'):r['text']=old['text']
                    if case=='weak':r['confidence']=.5
                return [r]
            with self.subTest(case=case),patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_travellers_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(rows[0]['text'],'Travellers Report')
                self.assertEqual(rows[1]['text'],'The TEST Romans have abandoned their great project,')
                self.assertEqual(rows[2],before[2])
            else:self.assertEqual(rows,before)

    def test_actual_zulu_abandonment_is_only_an_informational_notice(self):
        p=Path('runs/attempt-010/screens/ui-0003118.png')
        if not p.exists():self.skipTest('Private original report unavailable')
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'ABANDONWONDER')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        body=next(r for r in o['lines']if r['text'].startswith('The Zulus'))
        self.assertEqual(body['text'],'The Zulus have abandoned their great project,')
        self.assertIn('ahandoned',body['provenance'][0]['text'])
        self.assertIn('Hanging Gardens.',d['visible_text'])

    def test_optional_original_public_start_report(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-005/screens/ui-0002312.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original report unavailable')
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'STARTWONDER')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertEqual(next(r for r in o['lines'] if r['text']=='Travellers Report')['provenance'][0]['text'],'Dravellers Report')


if __name__=='__main__':unittest.main()
