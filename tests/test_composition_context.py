from copy import deepcopy
import json
from pathlib import Path
import unittest
from civ2.policy import _composition_context


def fixture():
    warrior=dict(id=2,name='TEST Warrior',domain=0,role=1,attack=1,defense=1,movement=1,max_hp=10,shield_cost=10)
    worker=dict(warrior,id=0,name='TEST Worker',role=5,attack=0,max_hp=20,shield_cost=40)
    pike=dict(warrior,id=6,name='TEST Pike',defense=2,shield_cost=20)
    trade=dict(warrior,id=48,name='TEST Trade',role=7,attack=0,shield_cost=50)
    rules=dict(units=[warrior,worker,pike,trade],improvements=[])
    own=[dict(id=i,type_id=2,hp=10,hp_lost=0,order_id=2 if i<24 else 255) for i in range(25)]
    cities=[dict(id=i,production=dict(kind='unit',id=0 if i==0 else 6,name='TEST Worker' if i==0 else 'TEST Pike')) for i in range(6)]
    return rules,own,cities


class CompositionContextTests(unittest.TestCase):
    def test_explicit_roster_orders_and_different_current_builds(self):
        args=fixture();before=deepcopy(args);facts=_composition_context(*args)
        self.assertEqual(args,before);self.assertEqual(facts['fortified_record_count'],24)
        self.assertEqual(facts['observed_order_id_counts'],{'2':24,'255':1})
        self.assertEqual(facts['owned_types'][0]['observed_count'],25)
        self.assertEqual(facts['owned_types'][0]['original_specification']['attack'],1)
        self.assertEqual((facts['resolved_worker_count'],facts['resolved_trade_count']),(0,0))
        self.assertEqual([(g['type_id'],g['city_count']) for g in facts['current_production_groups']],[(0,1),(6,5)])
        self.assertEqual(facts['current_production_groups'][1]['original_specification']['defense'],2)
        self.assertEqual(facts['unknown_specification_unit_ids'],[])

    def test_dead_inconsistent_hp_and_unknown_rules_remain_explicit(self):
        for mode in ('dead','inconsistent','unknown','malformed','duplicate','missing_order'):
            rules,own,cities=fixture();own=own[:1]
            if mode=='dead':own[0].update(hp=0,hp_lost=10)
            elif mode=='inconsistent':own[0]['hp_lost']=3
            elif mode=='unknown':rules['units']=[]
            elif mode=='malformed':rules['units'][0]['attack']=True
            elif mode=='duplicate':rules['units'].append(deepcopy(rules['units'][0]))
            else:own[0].pop('order_id')
            facts=_composition_context(rules,own,cities)
            self.assertEqual(facts['owned_types'][0]['observed_count'],1)
            if mode=='missing_order':self.assertEqual(facts['unknown_order_unit_ids'],[0])
            else:self.assertEqual(facts['unresolved_hp_unit_ids'],[0])
            if mode in ('unknown','malformed','duplicate'):self.assertEqual(facts['unknown_specification_unit_ids'],[0])

    def test_all_roles_and_improvements_have_current_facts_without_forecasts(self):
        rules,own,cities=fixture();own=[dict(id=1,type_id=0,hp=20,hp_lost=0,order_id=255),dict(id=2,type_id=48,hp=9,hp_lost=1,order_id=2)]
        rules['improvements']=[dict(id=6,name='TEST Library',kind='building',shield_cost=80,upkeep=1)]
        cities.append(dict(id=8,production=dict(kind='improvement',id=6,name='TEST Library')))
        cities.append(dict(id=9,production=dict(kind='unit',id=999,name='TEST Unknown')))
        facts=_composition_context(rules,own,cities)
        self.assertEqual((facts['resolved_worker_count'],facts['resolved_trade_count']),(1,1))
        self.assertEqual(facts['unknown_production_specification_city_ids'],[9])
        library=next(g for g in facts['current_production_groups'] if g['record_type']=='improvement')
        self.assertEqual(library['original_specification']['upkeep'],1)
        self.assertNotIn('eligible',json.dumps(facts));self.assertNotIn('completion_turn',json.dumps(facts))

    def test_missing_build_name_is_counted_without_fabricated_text(self):
        rules,own,cities=fixture();cities[0]['production']['name']=None
        group=next(g for g in _composition_context(rules,own,cities)['current_production_groups'] if g['type_id']==0)
        self.assertEqual(group['observed_names'],[]);self.assertEqual(group['missing_observed_name_count'],1)
        self.assertNotIn('None',json.dumps(group))

    def test_optional_actual_011_request_reconstructed_current_counts(self):
        p=Path('runs/attempt-011/decisions/000531-request.json')
        if not p.exists():self.skipTest('Private actual request unavailable')
        from civ2.compact import expand_model_state
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        state=expand_model_state(json.loads(p.read_text())['state'])
        f=_composition_context(parse_rules(original_rules()),state['owned_unit_roster'],state['owned_cities'])
        self.assertEqual(f['fortified_record_count'],24)
        self.assertEqual([(r['type_id'],r['observed_count']) for r in f['owned_types']],[(2,25)])
        self.assertEqual([(r['type_id'],r['city_count']) for r in f['current_production_groups']],[(0,1),(6,5)])
        self.assertEqual(f['unknown_specification_unit_ids'],[])


if __name__=='__main__':unittest.main()
