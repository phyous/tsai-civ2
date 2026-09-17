"""Researched advice reaches real request construction without choosing actions."""
from copy import deepcopy
import unittest
from civ2 import policy,strategy
from tests.test_policy import fixture,rules


class StrategyGuideTests(unittest.TestCase):
    def test_surplus_advice_and_version_reach_unit_request_with_original_choices(self):
        state=fixture(unit_type=1);original=deepcopy(state);r=rules()
        actions=policy.unit_candidates(state,rules=r)
        request=policy.unit_request_for(state,actions,r)
        self.assertEqual(request['state']['strategy_guide']['revision'],'civ2-prince-guide-2026-09-17-v3')
        self.assertEqual(request['state']['strategy_guide']['sources'],strategy.SOURCES)
        advice=request['state']['strategic_playbook']['garrison_and_surplus']
        self.assertIn('observed city garrisons',advice)
        self.assertIn('scout known frontiers',advice)
        self.assertIn('actual economy and threats',advice)
        self.assertIn('not mandatory moves or fixed garrison counts',advice)
        self.assertEqual(request['questions']['unit_action']['criteria'],{key:a['label'] for key,a in actions.items()})
        self.assertEqual(state,original)


if __name__=='__main__':unittest.main()
