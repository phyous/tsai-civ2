"""Malformed title spacing can scope pixel reads, never invent a title."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from tests.test_herald import prepared
from civ2 import observe


class ProductionStatTitlePixels(unittest.TestCase):
    def fixture(self):
        return [prepared('Whait shall me buddin TEST!',221,78,198,16),
            prepared('Settlers',178,102,50,14),
            prepared('(20 Turns, ADM: 0/1/1 HP: 2/1 *',324,100,214,20),
            prepared('Auto',150,387,40,15),prepared('Help',305,387,30,15),prepared('OK',458,387,24,15)]

    def test_pair_recovers_stat_but_does_not_rewrite_title(self):
        for changed in (False,True):
            rows=self.fixture();a=deepcopy(rows[2]);a['text']='(20 Turns, ADM: 0/1/1 HP: 2/1)'
            b=deepcopy(a)
            if changed:b['text']='(19 Turns, ADM: 0/1/1 HP: 2/1)'
            def crop(image,old,name,*args,**kwargs):
                if name.startswith('production_title'):return []
                return [deepcopy(b if '_gray_' in name else a)]
            with patch.object(observe,'_production_names',return_value={'settlers'}),patch.object(
                    observe,'_crop_text',side_effect=crop):
                observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[0]['text'],self.fixture()[0]['text'])
            self.assertEqual(rows[2]['text'],self.fixture()[2]['text'] if changed else a['text'])

    def test_missing_native_controls_do_not_trigger(self):
        rows=self.fixture()[:-1]
        with patch.object(observe,'_crop_text') as crop:
            observe._recover_city_and_production_rows(Image.new('RGB',(640,480)),rows,None,None,{})
        crop.assert_not_called()

    def test_actual_native_stat_digits_and_raw_title_are_preserved(self):
        p=Path(__file__).resolve().parents[1]/'runs/attempt-010/screens/ui-0001379.png'
        if not p.exists():self.skipTest('Private original capture unavailable')
        o=observe.recognize(p)
        self.assertIn('Whait shall me buddin Neapous!',[r['text'] for r in o['lines']])
        stats=[r for r in o['lines'] if r['text']=='(20 Turns, ADM: 0/1/1 HP: 2/1)']
        self.assertEqual(len(stats),1)
        self.assertEqual(stats[0]['provenance'][0]['text'],'(20 Turns, ADM: 0/1/1 HP: 2/1 *')


if __name__=='__main__':unittest.main()
