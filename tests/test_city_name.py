"""Synthetic TEST naming forms; accepting a default never invents its value."""
from copy import deepcopy
import unittest
from civ2.dialogs import classify_dialog


SOURCE='@NAMECITY\n@title=What Shall We Name This City?\n@options\nCity Name:\n'


def row(text,x,y,w,h=14):
    return dict(text=text,bounds=[x,y,w,h],center=[x+w//2,y+h//2],confidence=1.)


def form():
    return dict(width=640,height=480,sha256='a'*64,lines=[
        row('What Shall We Name "This City?',220,200,200,18),
        row('City Name:',102,230,70,12),row('OK',194,266,26),
        row('Cancel',412,266,42,12)])


class CityNameTests(unittest.TestCase):
    def test_complete_source_bound_form_accepts_untouched_unreadable_default(self):
        original=form();result=classify_dialog(original,game_text=SOURCE)
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['kind'],'new_city_name')
        self.assertIsNone(result['default_name'])
        self.assertNotIn('observed_city_name',result)
        self.assertEqual(result['mechanical_action'],'accept_observed_default_name')
        self.assertEqual([o['text'] for o in result['options']],['OK'])
        self.assertEqual(result['options'][0]['center'],[207,273])
        self.assertFalse(result['evidence']['name_entry']['value_observed'])
        self.assertEqual(original,form())

    def test_unreadable_default_requires_exact_original_form_resource(self):
        for source in (None,SOURCE.replace('@NAMECITY','@RENAMECITY'),
                       SOURCE.replace('City Name:','Overwrite City:'),
                       SOURCE+'\nCancel\nContinue\n'):
            with self.subTest(source=source):
                self.assertFalse(classify_dialog(form(),game_text=source)['supported'])

    def test_missing_instruction_title_or_cancel_never_authorizes_enter(self):
        for index in range(4):
            screen=form();screen['lines'].pop(index)
            self.assertFalse(classify_dialog(screen,game_text=SOURCE)['supported'])

    def test_extra_choices_unknown_body_and_ambiguous_values_refuse(self):
        for extra in ([row('Yes',260,310,30)],
                      [row('Really replace an existing city?',210,250,220)],
                      [row('TEST first',200,225,70),row('TEST second',285,225,80)]):
            screen=form();screen['lines']+=extra
            self.assertFalse(classify_dialog(screen,game_text=SOURCE)['supported'])

    def test_unreadable_form_checks_control_and_field_label_geometry(self):
        for index,replacement in ((2,row('OK',500,266,26)),
                                  (3,row('Cancel',412,340,42)),
                                  (1,row('City Name:',400,230,70)),
                                  (1,row('City Name:',102,270,70))):
            screen=form();screen['lines'][index]=replacement
            self.assertFalse(classify_dialog(screen,game_text=SOURCE)['supported'])

    def test_readable_name_remains_observation_and_low_confidence_refuses(self):
        screen=form();screen['lines'].append(row('TEST Veii',190,230,70))
        result=classify_dialog(screen,game_text=SOURCE)
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['default_name'],'TEST Veii')
        screen['lines'][-1]['confidence']=.4
        self.assertFalse(classify_dialog(screen,game_text=SOURCE)['supported'])


if __name__=='__main__': unittest.main()
