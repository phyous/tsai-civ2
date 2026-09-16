"""Original presentation notices cannot authorize strategic or cosmetic choices."""
from copy import deepcopy
from pathlib import Path
import unittest
from test_dialogs import observation,row
from civ2.dialogs import classify_dialog

BODY=('The TEST people announce this complete informational celebration. '
      'The TEST craftsmen return to decorate the palace.')
RESOURCE='@THRONE\n'+BODY+'\n\n@NEXT\nTEST unrelated resource\n'

def notice():
    return observation(row('The TEST people announce this complete',y=135,w=400),
        row('informational celebration. The TEST craftsmen',y=165,w=430),
        row('return to decorate the palace.',y=195,w=300),
        row('(Click mouse to continue...)',y=465,w=210))

class PresentationNoticeTests(unittest.TestCase):
    def test_complete_resource_and_observed_prompt_only_acknowledge_notice(self):
        o=notice();d=classify_dialog(o,game_text=RESOURCE)
        self.assertTrue(d['supported'],d)
        self.assertEqual(d['kind'],'presentation_notice')
        self.assertEqual(d['mechanical_action'],'acknowledge_presentation')
        self.assertFalse(d['requires_model'])
        self.assertEqual(d['resource_tag'],'THRONE')
        self.assertEqual(d['buttons'][0]['center'],[320,465])
        self.assertEqual(d['acknowledgement_point'],[320,135])

    def test_partial_body_prompt_without_resource_or_extra_choices_never_authorizes_click(self):
        for mutation in (lambda o:o['lines'].pop(1),lambda o:o['lines'].append(row('Buy upgrade',y=340)),
                         lambda o:o['lines'][1].update(confidence=.4),
                         lambda o:o['lines'][-1].update(text='Choose an upgrade'),
                         lambda o:o.update(ocr={'conflicts':[{'text':'TEST'}]})):
            o=notice();mutation(o)
            self.assertFalse(classify_dialog(o,game_text=RESOURCE)['supported'])
        self.assertFalse(classify_dialog(notice())['supported'])
        self.assertFalse(classify_dialog(notice(),game_text=RESOURCE.replace('@THRONE','@UNREVIEWED'))['supported'])

    def test_optional_actual_throne_notice(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        p=Path(__file__).resolve().parents[1]/'runs/attempt-004/screens/ui-0000335.png'
        if not p.exists():self.skipTest('Private original image unavailable')
        d=classify_dialog(recognize(p),game_text=game_text())
        self.assertTrue(d['supported'],d)
        self.assertEqual(d['mechanical_action'],'acknowledge_presentation')

if __name__=='__main__':unittest.main()
