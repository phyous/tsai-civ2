"""A damaged title may locate pixels but cannot supply a build or city name."""
from pathlib import Path
import unittest
from civ2 import observe

class ProductionDamagedPronoun(unittest.TestCase):
    def test_original_ravenna_reads_all_options_and_stats(self):
        path=Path('runs/attempt-012/screens/ui-0002507.png')
        if not path.exists():self.skipTest('Private original calibration unavailable')
        o=observe.recognize(path)
        stats=[r for r in o['lines'] if r['text']=='(20 Turns, ADM: 0/1/1 HP: 2/1)']
        self.assertEqual(len(stats),1)
        self.assertTrue(any(r['text'].endswith(' *') for r in stats[0]['provenance']))
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.run import game_text,labels_text
        from civ2.dialogs import classify_dialog
        import hashlib
        obs={**o,'path':str(path.resolve())}
        result=classify_dialog(obs,rules=parse_rules(original_rules()),game_text=game_text(),
            labels_text=labels_text(),state={'cities':[{'name':'Ravenna'}]})
        self.assertTrue(result['supported'],result.get('reason'))
        self.assertEqual(result['kind'],'production_choice')
        self.assertEqual(len(result['options']),16)
