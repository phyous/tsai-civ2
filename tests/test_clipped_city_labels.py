from copy import deepcopy
from pathlib import Path
import unittest
from civ2.dialogs import _clipped_city_label
from tests.test_herald import prepared

class ClippedCityLabels(unittest.TestCase):
    def test_two_letter_fragment_is_unique_native_right_edge_context(self):
        state={'evidence':{'kind':'live_memory','observation_sha256':'a'*64},
               'cities':[{'name':'Antium','x':60,'y':26}]}
        for case in ('valid','ambiguous','no_revision','left','interior','one_letter','ok','no'):
            s=deepcopy(state);r=prepared('An',428,238,26,16);r['normal']='an'
            if case=='ambiguous':s['cities'].append({'name':'Ancona','x':62,'y':26})
            if case=='no_revision':s.pop('evidence')
            if case=='left':r['bounds'][0]=0
            if case=='interior':r['bounds'][0]=200
            if case=='one_letter':r['normal']='a'
            if case in ('ok','no'):
                r['normal']=case;s['cities'][0]['name']=case+'polis'
            self.assertEqual(_clipped_city_label(r,s),case=='valid',case)

    def test_actual_fragment_preserves_raw_text(self):
        p=Path('runs/attempt-012/screens/ui-0002824.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        from civ2.observe import recognize
        r=next(r for r in recognize(p)['lines'] if r['text']=='An');r['normal']='an'
        s={'evidence':{'kind':'live_memory','observation_sha256':'a'*64},'cities':[{'name':'Antium','x':60,'y':26}]}
        old=deepcopy(r);self.assertTrue(_clipped_city_label(r,s));self.assertEqual(r,old)

if __name__=='__main__':unittest.main()
