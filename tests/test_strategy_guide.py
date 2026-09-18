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
        self.assertEqual(request['state']['strategy_guide']['revision'],'civ2-prince-guide-2026-09-17-v8')
        self.assertEqual(request['state']['strategy_guide']['sources'],strategy.SOURCES)
        advice=request['state']['strategic_playbook']['garrison_and_surplus']
        self.assertIn('observed city garrisons',advice)
        self.assertIn('scout known frontiers',advice)
        self.assertIn('actual economy and threats',advice)
        self.assertIn('not mandatory moves or fixed garrison counts',advice)
        self.assertEqual(request['questions']['unit_action']['criteria'],{key:a['label'] for key,a in actions.items()})
        self.assertEqual(state,original)
        self.assertIn('repeats unit production',request['state']['strategic_playbook']['productive_turns'])
        self.assertIn('no Settlers/Engineers',request['state']['strategic_playbook']['productive_turns'])
        support=request['state']['strategic_playbook']['support_and_expansion']
        self.assertIn('does not transfer its home-city support',support)
        self.assertIn('removes a population point',support)
        self.assertIn('Food stores do not cover a shield-support shortage',support)
        self.assertIn('use only offered commands',support.casefold())
        economy=request['state']['strategic_playbook']['unit_economy']
        self.assertIn('decide No or Yes separately',economy)
        self.assertIn('half its production cost',economy)
        self.assertIn('trade units cannot change home city',economy)


if __name__=='__main__':unittest.main()
