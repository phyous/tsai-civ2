"""Synthetic original-form regressions; no gameplay/model evidence."""
from copy import deepcopy
from unittest import TestCase, mock
from PIL import Image
from civ2 import observe
from civ2.dialogs import classify_dialog
from test_dialogs import observation, row

SOURCE='@REVOLUTION\n@width=240\n@title=Revolution\nDo we want a revolution to overthrow the %STRING0 %STRING1?\n\nYes\nNo\n'


class RevolutionTests(TestCase):
    def form(self):
        return observation(row('Revobtion',x=321,y=176,w=68),
            row('Do we want a revolution to',x=326,y=201,w=210),
            row('overthrow the Roman Despotism?',x=336,y=221,w=228),
            row('O Yes',x=257,y=248,w=58),row('• No',x=254,y=273,w=52),
            row('OK',x=320,y=305,w=24))

    def test_full_resource_and_raw_radio_choices_survive_title_glyph_damage(self):
        o=self.form();d=classify_dialog(o,game_text=SOURCE)
        self.assertTrue(d['supported']);self.assertTrue(d['requires_model'])
        self.assertEqual(d['kind'],'revolution_choice')
        self.assertEqual([r['text'] for r in d['options']],['O Yes','• No'])
        self.assertEqual(d['title'],'Revobtion')
        for index,text in ((0,'Unrelated'),(1,'Do we want to'),(3,'O Maybe'),(5,'Cancel')):
            altered=deepcopy(o);altered['lines'][index]['text']=text
            self.assertFalse(classify_dialog(altered,game_text=SOURCE)['supported'])
        self.assertFalse(classify_dialog(o)['supported'])

    def test_two_actual_heading_crops_must_agree_at_the_same_location(self):
        # Input rows in the dialog fixture already use pixel fields; construct
        # an independent normalized OCR source for the crop reader instead.
        rows=[]
        for r in self.form()['lines']:
            x,y,w,h=r['bounds']
            rows+=observe._prepare_rows([dict(text=r['text'],confidence=1,
                x=x/640,y=y/480,width=w/640,height=h/480)],640,480,'TEST')
        rows[0]['text']='Reromnon'
        candidate=deepcopy(rows[0]);candidate['text']='Revolution'
        with mock.patch.object(observe,'_crop_text',side_effect=[[deepcopy(candidate)],[deepcopy(candidate)]]):
            observe._recover_revolution_title(Image.new('RGB',(640,480)),rows,'TEST','TEST',{'passes':[]})
        self.assertEqual(rows[0]['text'],'Revolution')
        rows[0]['text']='Reromnon';bad=deepcopy(candidate);bad['text']='Resolution'
        with mock.patch.object(observe,'_crop_text',side_effect=[[deepcopy(candidate)],[bad]]):
            observe._recover_revolution_title(Image.new('RGB',(640,480)),rows,'TEST','TEST',{'passes':[]})
        self.assertEqual(rows[0]['text'],'Reromnon')
