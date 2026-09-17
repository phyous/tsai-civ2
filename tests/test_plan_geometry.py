"""Synthetic geometric context; no route or model decision is fabricated."""
from copy import deepcopy
import unittest
from civ2.planning import target_geometry
from civ2.policy import unit_candidates
from test_planning import fixture, select


class PlanGeometryTests(unittest.TestCase):
    def test_all_offered_moves_retain_order_and_distance_without_ranking(self):
        state,rules=fixture();plan=select(state,rules,'settle',(10,8))
        actions=unit_candidates(state,rules=rules);before=deepcopy((plan,state,actions))
        result=target_geometry(plan,state,actions)
        self.assertEqual(result['current_geometric_steps_to_target'],1)
        self.assertEqual(result['offered_moves']['move_e']['geometric_steps_to_target'],0)
        self.assertEqual(result['offered_moves']['move_w']['change_in_geometric_steps'],1)
        self.assertEqual(list(result['offered_moves']),[k for k,v in actions.items() if v['kind']=='move'])
        self.assertEqual((plan,state,actions),before)
        self.assertIn('not a route',result['note'])

    def test_hold_or_changed_actor_has_no_geometry(self):
        state,rules=fixture();actions=unit_candidates(state,rules=rules)
        self.assertIsNone(target_geometry(select(state,rules,'hold'),state,actions))
        plan=select(state,rules,'settle',(10,8));plan['actor']['home_city_id']=999
        self.assertIsNone(target_geometry(plan,state,actions))

    def test_original_horizontal_world_wrap_is_respected(self):
        state,rules=fixture();plan=select(state,rules,'settle',(10,8))
        state['settings']['round_world']=True
        plan['candidate']['target']={'x':38,'y':8}
        result=target_geometry(plan,state,unit_candidates(state,rules=rules))
        self.assertEqual(result['current_geometric_steps_to_target'],5)
        self.assertEqual(result['offered_moves']['move_w']['geometric_steps_to_target'],4)

    def test_known_water_detour_is_visible_without_hidden_tiles_or_cost_claims(self):
        state,rules=fixture()
        state['map']['tiles']=[dict(x=x,y=y,terrain='Plains',terrain_id=1,river=False,known_improvements=[])
            for x,y in ((8,8),(8,6),(8,10),(10,10),(12,10),(12,8))]
        state['map']['tiles'].append(dict(x=10,y=8,terrain='Ocean',terrain_id=10))
        state['map']['hidden_tiles']=[dict(x=9,y=9,terrain='Plains')]
        state['map']['tiles'].append(dict(x=9,y=9,terrain=None))
        plan=select(state,rules,'settle',(12,8));actions=unit_candidates(state,rules=rules)
        result=target_geometry(plan,state,actions,rules)
        self.assertEqual(result['current_fewest_observed_land_edges_to_target'],4)
        self.assertEqual(result['offered_moves']['move_s']['fewest_observed_land_edges_to_target'],3)
        self.assertEqual(result['offered_moves']['move_n']['fewest_observed_land_edges_to_target'],5)
        self.assertIsNone(result['offered_moves']['move_se']['fewest_observed_land_edges_to_target'])
        self.assertNotIn('move_e',result['offered_moves'])
        self.assertIn('not that travel is impossible',result['observed_land_note'])

    def test_disconnected_known_land_does_not_assert_impossibility(self):
        state,rules=fixture();plan=select(state,rules,'settle',(10,8))
        state['map']['tiles']=[tile for tile in state['map']['tiles'] if (tile['x'],tile['y'])==(8,8)]
        result=target_geometry(plan,state,unit_candidates(state,rules=rules),rules)
        self.assertIsNone(result['current_fewest_observed_land_edges_to_target'])


if __name__=='__main__':unittest.main()
