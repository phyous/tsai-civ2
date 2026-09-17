"""TEST original sneak-attack information, never an authorization to attack."""
from pathlib import Path
import unittest
from civ2.native_events import classify_information
from tests.test_native_events import resource,notice,row

class SneakNotice(unittest.TestCase):
    def test_complete_attack_notice_has_only_informational_ok(self):
        template=resource('SNEAK','Defense Minister','Sneak attack by %STRING0 forces!')
        screen=notice('Sneak attack by TEST American forces!',title='Detense Mfinister')
        d=classify_information(screen,[template])
        self.assertTrue(d['supported'],d);self.assertFalse(d['requires_model'])
        self.assertEqual(d['resource_tag'],'SNEAK');self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertEqual([r['text'] for r in d['options']],['OK'])
        self.assertEqual(d['title'],'Detense Mfinister')
        for bad in (notice('Sneak attack by TEST Americans.',title='Detense Mfinister'),
                    notice('Sneak attack by TEST American forces! Attack them now?',title='Detense Mfinister')):
            self.assertFalse(classify_information(bad,[template])['supported'])
        screen['lines'].append(row('Cancel',y=265,width=50))
        self.assertFalse(classify_information(screen,[template])['supported'])

    def test_optional_original_009_attack_notice(self):
        from civ2.observe import recognize
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-009/screens/ui-0000570.png'
        if not path.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original sneak notice unavailable')
        d=classify_dialog(recognize(path),game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'SNEAK')
        self.assertEqual(d['mechanical_action'],'acknowledge_information');self.assertFalse(d['requires_model'])
        self.assertIn('Sneak attack by American forces!',d['visible_text'])

if __name__=='__main__':unittest.main()
