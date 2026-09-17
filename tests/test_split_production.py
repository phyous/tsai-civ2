"""Synthetic TEST heading fragments and original production statistics."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class SplitProductionTests(unittest.TestCase):
    def test_fragments_are_only_crop_anchors_and_need_full_independent_title(self):
        base=[prepared('Soheit s',232,148,40,12),prepared('hall me boikd in TEST Rome?',274,146,170,14),
              prepared('Auto',156,320,32,12),prepared('Help',306,320,30,14),prepared('OK',458,319,25,13)]
        good=prepared('What shall me boikd in TEST Rome?',232,146,212,14)
        for case in ('good','different','city_changed','missing_button','extra_fragment','distant'):
            rows=copy.deepcopy(base);peer=copy.deepcopy(good)
            if case=='different':peer['text']='What shall we buy in TEST Rome?'
            if case=='city_changed':peer['text']='What shall me boikd in TEST Veii?'
            if case=='missing_button':rows.pop()
            if case=='extra_fragment':rows.append(prepared('Other',230,148,40,12))
            if case=='distant':rows[0]['bounds'][0]=100
            with patch.object(observe,'_crop_text',side_effect=[[good],[peer]]):
                observe._recover_split_production_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[0]['text'],good['text'] if case=='good' else base[0]['text'],case)
            if case=='good':self.assertEqual([p['text'] for p in rows[0]['provenance'][:2]],['Soheit s','hall me boikd in TEST Rome?'])

    def test_misread_adm_separator_cannot_change_turns_hp_or_other_digits(self):
        old='(40 Tums, ADM: 0/171 HP: 2/1)';good='(40 Tums, ADM: 0/1/1 HP: 2/1)'
        self.assertTrue(observe._stat_numbers_compatible(old,good))
        for a,b in ((old,good.replace('40','50')),(old,good.replace('HP: 2','HP: 3')),
                    (old.replace('171','181'),good),(old.replace('0/171','0/17/1'),good)):
            self.assertFalse(observe._stat_numbers_compatible(a,b),(a,b))

    def test_optional_original_split_heading_all_six_choices_and_stats(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-008/screens/ui-0000382.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original menu unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        o=observe.recognize(p);d=classify_dialog(o,state={'cities':[{'name':'Rome'}]},rules=parse_rules(original_rules()))
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_choice')
        self.assertEqual([v['text'] for v in d['options']],['Settlers','Warriors','Phalanx','Barracks','Temple','Colossus'])
        r=next(r for r in o['lines'] if 'ADM: 0/1/1' in r['text'])
        self.assertIn('0/171',r['provenance'][0]['text'])
        t=next(r for r in o['lines'] if r['text'].startswith('What shall'))
        self.assertEqual([q['text'] for q in t['provenance'][:2]],['Soheit s','hall me boikd in Rome?'])


if __name__=='__main__':unittest.main()
