"""Synthetic reference-page failures plus optional original private screenshots."""
import copy
from pathlib import Path
import unittest

from civ2.dialogs import classify_dialog
from tests.test_dialogs import observation, row, native_map, ROMAN_STATE


RULES={'advances':[{'id':1,'name':'TEST Alphabet'},{'id':2,'name':'TEST Writing'},
                   {'id':3,'name':'TEST Mathematics'},{'id':4,'name':'TEST Masonry'}]}


def reference():
    return observation(row('TEST Alphabet',x=320,y=27,w=190,h=34),
        row('Allows:',x=360,y=71,w=52,h=15),
        row('TEST Writing',x=384,y=100,w=100,h=14),
        row('TEST Mathematics (with Masonty)',x=444,y=125,w=220,h=14),
        row('ABC',x=192,y=156,w=232,h=116),
        row('TEST Alphabet',x=320,y=344,w=100),
        row('Ancient',x=464,y=404,w=44,h=12),row('Academic',x=468,y=418,w=52,h=12),
        row('ADVANCES MENU',x=175,y=459,w=118,h=10),
        row('DESCRIPTION',x=362,y=458,w=96,h=12),row('EXIT',x=498,y=458,w=36,h=12))


class CivilopediaTests(unittest.TestCase):
    def test_observed_exit_is_only_authorized_action_and_source_text_is_preserved(self):
        o=reference();old=copy.deepcopy(o);result=classify_dialog(o,rules=RULES)
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['kind'],'civilopedia_reference')
        self.assertEqual(result['mechanical_action'],'close_reference')
        self.assertFalse(result['requires_model'])
        self.assertEqual(result['sha256'],o['sha256'])
        self.assertEqual([b['text'] for b in result['buttons']],['ADVANCES MENU','DESCRIPTION','EXIT'])
        self.assertEqual(len(result['options']),1)
        self.assertEqual(result['options'][0]['text'],'EXIT')
        self.assertEqual(result['options'][0]['center'],[498,458])
        self.assertEqual(result['options'][0]['source_line'],10)
        self.assertEqual(result['reference']['advance_id'],1)
        self.assertIn('TEST Mathematics (with Masonty)',result['reference']['observed_body'])
        self.assertEqual(o,old)

    def test_missing_or_duplicate_original_title_and_controls_fail_closed(self):
        for index in (0,1,5,8,9,10):
            o=reference();o['lines'].pop(index)
            with self.subTest(missing=index):self.assertFalse(classify_dialog(o,rules=RULES)['supported'])
        for index in (0,8,9,10):
            o=reference();o['lines'].append(copy.deepcopy(o['lines'][index]))
            with self.subTest(duplicate=index):self.assertFalse(classify_dialog(o,rules=RULES)['supported'])
        for bad_rules in (None,{}, {'advances':[{'id':1,'name':'Other'}]},
                          {'advances':RULES['advances']+[copy.deepcopy(RULES['advances'][0])]}):
            self.assertFalse(classify_dialog(reference(),rules=bad_rules)['supported'])

    def test_control_geometry_and_low_confidence_never_generate_exit_target(self):
        mutations=(lambda o:o.update(width=800),
            lambda o:o['lines'].__setitem__(10,row('EXIT',x=320,y=250,w=36,h=12)),
            lambda o:o['lines'][10].update(confidence=.7),
            lambda o:o['lines'].__setitem__(0,row('TEST Alphabet',x=320,y=80,w=190,h=34)),
            lambda o:o['lines'].append(row('HELP',x=570,y=459,w=30,h=12)),
            lambda o:o['lines'].__setitem__(5,row('TEST Writing',x=320,y=344,w=100)))
        for mutate in mutations:
            o=reference();mutate(o);result=classify_dialog(o,rules=RULES)
            self.assertFalse(result['supported'],result)
            self.assertIsNone(result['mechanical_action'])
            self.assertEqual(result['options'],[])

    def test_foreground_modal_and_strategic_text_cannot_be_treated_as_reference(self):
        for extra in (row('OK',x=320,y=280,w=25),row('Cancel',x=380,y=280,w=50),
                      row('Are you sure?',x=320,y=260,w=120),
                      row('Choose your new advance',x=400,y=200,w=180)):
            o=reference();o['lines'].append(extra)
            self.assertFalse(classify_dialog(o,rules=RULES)['supported'])
        # A map with these same words does not inherit a reference close action.
        o=native_map();o['lines'].extend(reference()['lines'][-3:])
        result=classify_dialog(o,rules=RULES,state=ROMAN_STATE)
        self.assertFalse(result['supported']);self.assertIsNone(result['mechanical_action'])

    def test_optional_original_alphabet_pages_expose_actual_exit(self):
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        root=Path(__file__).resolve().parents[1]
        paths=[root/f'runs/attempt-002/screens/ui-{number:07d}.png' for number in (260,261)]
        if not all(path.exists() for path in paths) or not (root/'.runtime/ocr').exists():
            self.skipTest('private original reference images unavailable')
        rules=parse_rules(original_rules())
        for path in paths:
            o=recognize(path);result=classify_dialog(o,rules=rules)
            self.assertTrue(result['supported'],result)
            self.assertEqual(result['kind'],'civilopedia_reference')
            self.assertEqual(result['title'],'Alphabet')
            self.assertEqual(result['options'][0]['center'],[498,458])
            self.assertEqual(result['mechanical_action'],'close_reference')


if __name__=='__main__':unittest.main()
