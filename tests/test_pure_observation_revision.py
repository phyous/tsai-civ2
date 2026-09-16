"""Live provenance cannot masquerade as a save or authorize stale native input."""
from copy import deepcopy
import unittest

from civ2.city import CityLaborError, city_labor_projection
from civ2.city_controls import (CityControlError, city_control_candidates,
    city_control_request_for, city_labor_result, validate_city_control)
from civ2.empire import EmpireError, empire_candidates, validate_empire_action
from civ2.planning import advance_plan, make_plan, task_candidates
from civ2.policy import PolicyError, _recent_actions, model_state, unit_candidates, validate_action
from test_planning import fixture as unit_fixture
from test_city_labor_controls import inputs as labor_fixture
from test_empire import inputs as empire_fixture


def live(state, digest='c'*64):
    result=deepcopy(state)
    result['evidence']={'kind':'live_memory','observation_sha256':digest}
    return result


class PureObservationRevisionTests(unittest.TestCase):
    def test_live_unit_commands_bind_observation_only_and_reject_stale_snapshot(self):
        old,rules=unit_fixture();state=live(old)
        commands=unit_candidates(state,rules=rules)
        self.assertEqual(set(commands),set(unit_candidates(old,rules=rules)))
        action=commands['move_north'] if 'move_north' in commands else next(iter(commands.values()))
        self.assertEqual(action['preconditions']['observation_sha256'],'c'*64)
        self.assertNotIn('save_sha256',action['preconditions'])
        validate_action(action,state,rules)
        with self.assertRaises(PolicyError):validate_action(action,live(state,'d'*64),rules)
        wrong=deepcopy(action);wrong['preconditions']['save_sha256']='c'*64
        with self.assertRaises(PolicyError):validate_action(wrong,state,rules)
        projection=model_state(state,rules,[{'action':action}])
        self.assertEqual(projection['recent_actions'][0]['observation_sha256_at_issue'],'c'*64)
        self.assertNotIn('save_sha256_at_issue',projection['recent_actions'][0])
        self.assertIn('live memory',projection['year_note'])
        self.assertIn('observed slots',projection['unit_identity_note'])

    def test_plan_continuity_cannot_confuse_equal_save_and_observation_hashes(self):
        original,rules=unit_fixture();state=live(original)
        task=task_candidates(state,rules)[0]['hold_one_turn'];plan=make_plan(task,state,rules)
        self.assertEqual(plan['current_observation_sha256'],'c'*64)
        self.assertNotIn('current_save_sha256',plan)
        advanced=advance_plan(plan,state,live(state,'d'*64),rules=rules)
        self.assertEqual(advanced['current_observation_sha256'],'d'*64)
        self.assertEqual(advanced['status'],'active')
        for bad in ({'current_save_sha256':'c'*64},
                    {'current_save_sha256':'c'*64,'current_observation_sha256':'c'*64}):
            forged={k:v for k,v in plan.items() if not k.startswith('current_')};forged.update(bad)
            self.assertEqual(advance_plan(forged,state,live(state,'d'*64),rules=rules)['status'],'invalidated')
        # A real source transition remains explicit, never retaining both names.
        migrated=advance_plan(plan,state,original,rules=rules)
        self.assertEqual(migrated['current_save_sha256'],'a'*64)
        self.assertNotIn('current_observation_sha256',migrated)

    def test_live_labor_needs_exact_bitmap_and_fresh_readback_with_distinct_hashes(self):
        old,screen,rules=labor_fixture();state=live(old)
        actions=city_control_candidates(state,screen,rules=rules,labor_ready=True)
        action=actions['labor_remove_worker_2'];validate_city_control(action,state,screen,rules=rules,labor_ready=True)
        projection=city_labor_projection(state,0,rules)
        self.assertEqual(projection['revision'],{'observation_sha256':'c'*64,'turn':7})
        self.assertIn('city_totals_as_observed',projection);self.assertNotIn('city_totals_as_saved',projection)
        after=live(state,'d'*64)
        self.assertEqual(city_labor_result(action,state,after)['status'],'no_observed_change')
        after['cities'][0].update(worked_tiles_bits=[0,0,16],specialist_count=1,specialists={'entertainer':1})
        result=city_labor_result(action,state,after)
        self.assertEqual(result['status'],'observed_expected_change')
        self.assertEqual((result['before_observation_sha256'],result['after_observation_sha256']),('c'*64,'d'*64))
        self.assertNotIn('before_save_sha256',result);self.assertNotIn('save comparison',result['observation'])
        forged=deepcopy(action);forged['preconditions']['save_sha256']='c'*64
        with self.assertRaises(CityControlError):city_labor_result(forged,state,after)
        changed=live(state,'e'*64)
        with self.assertRaises(CityControlError):city_labor_result(action,changed,after)
        request=city_control_request_for(state,screen,actions,rules=rules,labor_ready=True)
        self.assertIn('live memory',request['state']['city_control_review']['scope'])

    def test_city_name_recovery_cannot_relabel_save_proof_as_memory_proof(self):
        old,screen,rules=labor_fixture();state=live(old)
        screen['title']=screen['title'].replace('TEST Rome','TEST Rom')
        screen['observed_city_name']='TEST Rome'
        proof=dict(source='Unique one-edit match to owned city in live memory observation',
            ocr_text='TEST Rom',canonical_name='TEST Rome',city_id=0,observation_sha256='c'*64,source_line=0)
        screen['city_name_recovery']=proof
        self.assertIn('exit_city',city_control_candidates(state,screen,rules=rules))
        for changed in ({'save_sha256':'c'*64}, {'source':'Unique one-edit match to owned city in original save'},
                        {'observation_sha256':'d'*64}):
            bad=deepcopy(screen);bad['city_name_recovery'].update(changed)
            with self.assertRaises(CityControlError):city_control_candidates(state,bad,rules=rules)

    def test_live_empire_commands_keep_screen_guard_and_exact_revision(self):
        old,screen,rules=empire_fixture();state=live(old)
        actions=empire_candidates(state,screen,rules=rules)
        action=actions['finish_turn'];validate_empire_action(action,state,screen,rules=rules)
        self.assertEqual(action['preconditions']['observation_sha256'],'c'*64)
        self.assertNotIn('save_sha256',action['preconditions'])
        with self.assertRaises(EmpireError):validate_empire_action(action,live(state,'d'*64),screen,rules=rules)
        with self.assertRaises(EmpireError):empire_candidates(state,{**screen,'kind':'normal_map'},rules=rules)

    def test_missing_mislabeled_dual_and_unknown_source_rejected_by_all_action_paths(self):
        evidence_cases=({}, {'observation_sha256':'c'*64},
            {'kind':'live_memory','save_sha256':'c'*64},
            {'kind':'live_memory','observation_sha256':'c'*64,'save_sha256':None},
            {'kind':'invented','observation_sha256':'c'*64})
        for evidence in evidence_cases:
            with self.subTest(evidence=evidence):
                unit,rules=unit_fixture();unit['evidence']=evidence
                with self.assertRaises(PolicyError):unit_candidates(unit,rules=rules)
                city,screen,rules=labor_fixture();city['evidence']=evidence
                with self.assertRaises(CityLaborError):city_labor_projection(city,0,rules)
                with self.assertRaises(CityControlError):city_control_candidates(city,screen,rules=rules)
                empire,screen,rules=empire_fixture();empire['evidence']=evidence
                with self.assertRaises(EmpireError):empire_candidates(empire,screen,rules=rules)

    def test_recent_receipts_do_not_propagate_ambiguous_revision_claims(self):
        rows=_recent_actions([{'action':{'kind':'wait','preconditions':{'turn':7,'save_sha256':'a'*64,'observation_sha256':'b'*64}},
            'receipt':{'before':{'turn':7,'save_sha256':'a'*64,'observation_sha256':'b'*64}}}])
        self.assertNotIn('save_sha256_at_issue',rows[0]);self.assertNotIn('observation_sha256_at_issue',rows[0])
        self.assertEqual(rows[0]['before'],{'turn':7})


if __name__=='__main__':unittest.main()
