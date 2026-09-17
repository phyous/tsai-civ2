"""Transient native combat records must not look like a ready garrison."""
from copy import deepcopy
import unittest

from civ2.policy import model_state
from civ2.empire import _production_context
from tests.test_policy import fixture,rules
from tests.test_empire_support import support_fixture


class UnresolvedUnitContextTests(unittest.TestCase):
    def test_zero_missing_and_inconsistent_hp_remain_in_roster_but_not_ready_counts(self):
        for case in ('zero','missing','negative','boolean','exhausted','above_max'):
            state=fixture(1);rule=rules();unit=state['units'][0]
            state['cities']=[dict(id=0,owner=1,name='TEST Rome',x=8,y=8,size=2)]
            unit['hp']=10;unit['hp_lost']=0
            if case=='zero':unit['hp']=0
            elif case=='missing':unit.pop('hp');unit.pop('hp_lost')
            elif case=='negative':unit['hp']=-1
            elif case=='boolean':unit['hp']=True
            elif case=='exhausted':unit['hp_lost']=rule['units'][1]['max_hp']
            else:unit['hp']=rule['units'][1]['max_hp']+1
            original=deepcopy(state)
            projection=model_state(state,rule)
            with self.subTest(case=case):
                facts=projection['empire_readiness']
                self.assertEqual(facts['owned_armed_unit_count'],0)
                self.assertEqual(facts['unresolved_native_unit_ids'],[7])
                self.assertEqual(facts['city_garrisons'][0]['owned_unit_ids'],[7])
                self.assertEqual(facts['city_garrisons'][0]['unresolved_native_unit_ids'],[7])
                self.assertEqual([u['id'] for u in projection['owned_unit_roster']],[7])
                self.assertEqual(state,original)

    def test_zero_home_unit_blocks_support_arithmetic_without_erasing_native_record(self):
        state,_,rule=support_fixture();state['units'][0]['hp']=0
        before=deepcopy(state);facts=_production_context(state,rule)
        self.assertEqual(facts['cities'][0]['owned_units_here'],4)
        self.assertEqual(facts['cities'][0]['armed_units_here'],3)
        self.assertEqual(facts['cities'][0]['unresolved_native_unit_ids'],[0])
        support=facts['cities'][0]['support_review']
        self.assertEqual(support['home_units'],5)
        self.assertEqual(support['unresolved_native_home_unit_ids'],[0])
        self.assertNotIn('minimum_shield_support',support)
        self.assertNotIn('food_after_listed_costs',support)
        self.assertIn('stable native observation',support['arithmetic_unavailable'])
        self.assertEqual(state,before)


if __name__=='__main__':unittest.main()
