"""Support regressions from original 009/008 observations; no game inputs."""
from copy import deepcopy
import unittest

from civ2.empire import _production_context,empire_candidates,empire_request_for
from tests.test_empire import inputs


def support_fixture(government=1):
    state,screen,rules=inputs()
    state['player']['government_id']=government
    rules['units']=[dict(id=0,name='Settlers',role=5,domain=0,attack=0),
                    dict(id=2,name='Warriors',role=1,domain=0,attack=1)]
    state['cities'][0].update(size=2,food_produced=6,shields_produced=2,
                             production=dict(id=0,kind='unit',name='Settlers'))
    state['units']=[dict(id=i,owner=1,type_id=2,home_city_id=0,x=2,y=2,hp=10) for i in range(4)]
    state['units'].append(dict(id=20,owner=1,type_id=0,home_city_id=0,x=0,y=2,hp=10))
    return state,screen,rules


def budget(state,rules):
    return _production_context(state,rules)['cities'][0]['support_review']


class EmpireSupportTests(unittest.TestCase):
    def test_actual_despotism_settler_completion_creates_shield_shortfall_not_food_shortfall(self):
        # 009 decision61: four home Warriors + new Settler; size3 -> size2.
        state,_,rules=support_fixture()
        before=deepcopy(state);before['units'].pop()
        before['cities'][0].update(size=3,food_produced=7,shields_produced=4)
        self.assertEqual(budget(before,rules)['shields_after_listed_costs'],3)
        after=budget(state,rules)
        self.assertEqual(after['minimum_shield_support'],3)
        self.assertEqual(after['shields_after_listed_costs'],-1)
        self.assertEqual(after['food_after_listed_costs'],1)
        self.assertEqual(after['home_units_away'],1)

    def test_actual_monarchy_postcompletion_can_have_shields_but_no_regrowth_food(self):
        # 008 city370 displays Support3/Production1, Food3/Surplus0.
        state,_,rules=support_fixture(2)
        state['cities'][0].update(size=1,food_produced=3,shields_produced=4)
        state['units'].append(dict(id=21,owner=1,type_id=2,home_city_id=0,x=2,y=2,hp=10))
        result=budget(state,rules)
        self.assertEqual(result['free_shield_support_allowance'],3)
        self.assertEqual(result['minimum_shield_support'],3)
        self.assertEqual(result['shields_after_listed_costs'],1)
        self.assertEqual(result['food_after_listed_costs'],0)

    def test_movement_changes_garrison_but_never_home_support(self):
        state,_,rules=support_fixture();before=budget(state,rules)
        for unit in state['units']:unit.update(x=12,y=12)
        after=budget(state,rules)
        self.assertEqual(after['home_units_away'],5)
        for key in ('home_units','minimum_shield_support','food_after_listed_costs','shields_after_listed_costs'):
            self.assertEqual(before[key],after[key])
        self.assertEqual(_production_context(state,rules)['cities'][0]['armed_units_here'],0)

    def test_foreign_nonhome_and_missing_home_units_never_assigned_by_proximity(self):
        state,_,rules=support_fixture();before=budget(state,rules)
        for i,extra in enumerate((dict(owner=2,home_city_id=0),dict(home_city_id=None),
                                  dict(home_city_id=3),dict(home_city_id=False),{})):
            unit=dict(id=40+i,owner=1,type_id=0,x=2,y=2,hp=10);unit.update(extra)
            state['units'].append(unit)
        self.assertEqual(budget(state,rules),before)

    def test_unknown_and_non_ground_costs_are_unclassified_not_guessed(self):
        state,_,rules=support_fixture()
        rules['units'].append(dict(id=40,name='TEST Ship',role=2,domain=2,attack=12))
        for i,kind in enumerate((40,99)):
            state['units'].append(dict(id=50+i,owner=1,type_id=kind,home_city_id=0,x=2,y=2,hp=10))
        result=budget(state,rules)
        self.assertEqual(result['home_units'],7)
        self.assertEqual(result['unclassified_home_units'],2)
        self.assertEqual(result['minimum_shield_support'],3) # conservative ground-only minimum
        self.assertIn('not verified net surplus',_production_context(state,rules)['support_note'])

    def test_other_governments_and_missing_output_have_no_invented_budget(self):
        for government in (0,3,4,5,6,None,True):
            with self.subTest(government=government):
                state,_,rules=support_fixture(government)
                result=budget(state,rules)
                self.assertEqual(result['home_units'],5)
                self.assertNotIn('minimum_shield_support',result)
        for value in (None,True,-1,'2'):
            state,_,rules=support_fixture()
            state['cities'][0].update(food_produced=value,shields_produced=value)
            result=budget(state,rules)
            self.assertNotIn('food_after_listed_costs',result)
            self.assertNotIn('shields_after_listed_costs',result)

    def test_facts_reach_request_without_changing_actions_or_mutating_state(self):
        state,screen,rules=support_fixture();original=deepcopy((state,screen,rules))
        actions=empire_candidates(state,screen,rules=rules)
        request=empire_request_for(state,screen,actions,rules=rules)
        facts=request['state']['end_of_turn_review']['production_review']
        self.assertEqual(facts['cities'][0]['support_review']['shields_after_listed_costs'],-1)
        self.assertEqual(request['questions']['empire_action']['criteria'],{k:a['label'] for k,a in actions.items()})
        self.assertEqual(set(actions),{'finish_turn','inspect_city_0','open_tax','open_research'})
        self.assertEqual((state,screen,rules),original)


if __name__=='__main__':unittest.main()


class ConditionalSettlerSupportTests(unittest.TestCase):
    def test_population_loss_and_added_support_are_explicitly_conditional(self):
        state,_,rules=support_fixture();state['units'].pop()
        state['cities'][0].update(size=2,shields_produced=3)
        original=deepcopy(state);scenario=budget(state,rules)['settler_completion_scenario']
        self.assertEqual(scenario['population_if_completed'],1)
        self.assertEqual(scenario['home_support_units_if_completed'],5)
        self.assertEqual(scenario['shield_support_if_completed'],4)
        self.assertEqual(scenario['shields_after_support_if_gross_output_unchanged'],-1)
        self.assertEqual(scenario['kind'],'conditional_arithmetic_not_a_forecast')
        self.assertIn('NOT projected',scenario['output_warning']);self.assertEqual(state,original)
    def test_monarchy_keeps_fixed_allowance_and_unsupported_cases_have_no_scenario(self):
        state,_,rules=support_fixture(2)
        self.assertEqual(budget(state,rules)['settler_completion_scenario']['free_shield_allowance_if_completed'],3)
        for change in ('size_one','other_build','other_government','unresolved'):
            s=deepcopy(state)
            if change=='size_one':s['cities'][0]['size']=1
            elif change=='other_build':s['cities'][0]['production']['id']=2
            elif change=='other_government':s['player']['government_id']=5
            else:s['units'][0]['hp']=0
            self.assertNotIn('settler_completion_scenario',budget(s,rules))
