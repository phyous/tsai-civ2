from copy import deepcopy
import unittest
from civ2.policy import unit_candidates,validate_action
from test_policy import fixture,rules


class CivilianInteraction(unittest.TestCase):
    def state(self,role):
        s=fixture();r=rules();spec={**r['units'][0],'role':role,'name':'TEST civilian'}
        r['units'][0]=spec;s['units'][0]['specification']=deepcopy(spec)
        s['visible_units']=[dict(id=22,type='TEST foreign defender',owner=2,x=10,y=8)]
        return s,r

    def test_original_diplomacy_role_can_request_occupied_entry(self):
        s,r=self.state(6);a=unit_candidates(s,rules=r)['move_e']
        self.assertEqual(a['parameters']['destination'],{'x':10,'y':8})
        self.assertIn('request original diplomacy interaction',a['label'])
        self.assertIn('separate observed choice',a['label']);validate_action(a,s,r)
        self.assertEqual(a['kind'],'move')

    def test_trade_entry_requires_observed_foreign_city(self):
        for city in (None,dict(x=10,y=8,owner=1),dict(x=10,y=8),dict(x=8,y=8,owner=2),dict(x=10,y=8,owner=2)):
            s,r=self.state(7);s['known_cities']=[] if city is None else [city]
            a=unit_candidates(s,rules=r)
            if city in (dict(x=10,y=8,owner=2),dict(x=10,y=8)):
                self.assertIn('request original trade interaction',a['move_e']['label']);validate_action(a['move_e'],s,r)
                self.assertIn('current owner unverified',a['move_e']['label'])
            else:self.assertNotIn('move_e',a)

    def test_saved_role_cannot_override_original_rules_and_worker_stays_blocked(self):
        for mode in ('worker','forged','missing','duplicate','sea','float','bool'):
            s,r=self.state(6)
            if mode=='worker':r['units'][0]['role']=s['units'][0]['specification']['role']=5
            elif mode=='forged':r['units'][0]['role']=5
            elif mode=='missing':r['units']=r['units'][1:]
            elif mode=='duplicate':r['units'].append(deepcopy(r['units'][0]))
            elif mode=='sea':r['units'][0]['domain']=2
            elif mode=='float':r['units'][0]['role']=6.0
            elif mode=='bool':r['units'][0]['attack']=False
            with self.subTest(mode=mode):self.assertNotIn('move_e',unit_candidates(s,rules=r))

    def test_hidden_city_never_enables_trade_and_observations_unchanged(self):
        s,r=self.state(7);s['hidden_cities']=[dict(x=10,y=8,owner=2)];before=deepcopy(s)
        self.assertNotIn('move_e',unit_candidates(s,rules=r));self.assertEqual(s,before)
