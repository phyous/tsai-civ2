"""The original war/alliance invitation always requires an actual model choice."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,mock
from PIL import Image
from civ2.observe import _recover_crusade_tail,recognize
from tests.test_herald import prepared


def rows():
    return [prepared('Enthusiastic TEST Emissary',346,306,182,16),
        prepared('"We invite you to join our crusade to rid the',312,328,294,18),
        prepared('world of the evil TEST. We will sign an alliance',312,350,312,18),
        prepared('for the duration of the hostilities.',312,370,220,14),
        prepared('"No, not interested."',346,392,148,22),
        prepared('Yes, declare war on TEST.',348,420,176,18),prepared('OK',424,454,26,16)]


class CrusadeTailTests(TestCase):
    def test_two_complete_reads_with_all_actual_war_options(self):
        for case in ('valid','disagree','other_target','other_terms','missing_choice','extra_choice','geometry'):
            original=rows();first=prepared('for the duration of the hostilities."',312,370,224,16);second=deepcopy(first)
            if case=='disagree':second['text']='for the duration of the hostilities.'
            if case=='other_target':original[5]['text']='Yes, declare war on OTHER.'
            if case=='other_terms':original[2]['text']='world of the evil TEST. We will declare a war'
            if case=='missing_choice':original.pop(4)
            if case=='extra_choice':original.insert(5,prepared('TEST another choice',346,411,148,12))
            if case=='geometry':first['center'][1]+=15
            before=deepcopy(original)
            with TemporaryDirectory() as d,mock.patch('civ2.observe._crop_text',side_effect=[[first],[second]]) as crop:
                _recover_crusade_tail(Image.new('RGB',(640,480)),original,None,d,{'passes':[]})
            if case=='valid':
                self.assertEqual(original[3]['text'],first['text']);self.assertEqual(original[4:],before[4:])
                self.assertEqual(len(original[3]['provenance']),3)
            else:self.assertEqual(original,before)
            if case in ('other_target','other_terms','missing_choice','extra_choice'):crop.assert_not_called()

    def test_actual_crusade_is_two_strategic_choices_not_acknowledgement(self):
        p=Path('runs/attempt-011/screens/ui-0002900.png')
        if not p.exists():self.skipTest('Private original frame unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['resource_tag'],'CRUSADE');self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text'] for r in d['options']],['"No, not interested."','Yes, declare war on Zulus.'])
        tail=next(r for r in o['lines'] if r['text'].startswith('for the duration'))
        self.assertEqual(tail['text'],'for the duration of the hostilities."')
        self.assertEqual([r['preprocessing'] for r in tail['provenance'][-2:]],['crusade_tail_rgb4','crusade_tail_gray4'])
