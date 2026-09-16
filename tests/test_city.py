"""TEST-only labor bitmaps, plus optional private original calibration."""
from copy import deepcopy
from pathlib import Path
import unittest
import zipfile

from civ2.city import CityLaborError,WORKED_BITS,city_labor_projection
from civ2.save import parse_rules,parse_save


def inputs():
    state=dict(turn=1,evidence={'save_sha256':'a'*64},player={'id':1},settings={'round_world':True},
        cities=[dict(id=0,owner=1,name='TEST Rome',x=8,y=8,size=1,worked_tiles_bits=[32,0,16],
                     specialist_count=0,specialists={},happy=0,unhappy=0,disorder=False,celebrating=False,
                     food_produced=4,shields_produced=2,tax=0,science=1)],
        map=dict(coordinate_width=32,height=16,tiles=[
            dict(x=8,y=8,terrain_id=2,terrain='TEST Grassland',river=False,known_improvements=[]),
            dict(x=6,y=8,terrain_id=2,terrain='TEST Grassland',river=True,known_improvements=['road'])]))
    rules=dict(terrain=[dict(id=2,name='TEST Grassland',food=2,shields=1,trade=0)])
    return state,rules


class CityLaborTests(unittest.TestCase):
    def test_initial_center_and_west_mapping(self):
        s,r=inputs();p=city_labor_projection(s,0,r)
        self.assertEqual([c['position'] for c in p['worked_positions']],[{'x':8,'y':8},{'x':6,'y':8}])
        self.assertTrue(p['worked_positions'][0]['is_center'])
        self.assertEqual((p['worked_positions'][1]['source_byte'],p['worked_positions'][1]['source_bit']),(48,5))
        self.assertEqual(p['labor_balance'],dict(population=1,non_center_workers=1,specialists=0,accounted_citizens=1,consistent=True))
        self.assertEqual(p['revision'],dict(save_sha256='a'*64,turn=1))

    def test_mapping_covers_unique_classic21_slots(self):
        self.assertEqual(len(WORKED_BITS),21)
        self.assertEqual(len({(a,b) for a,b,_,_ in WORKED_BITS}),21)
        self.assertEqual(len({(x,y) for _,_,x,y in WORKED_BITS}),21)
        s,r=inputs();s['cities'][0]['worked_tiles_bits']=[0x80,0x80,0x18]
        s['cities'][0]['size']=3
        p=city_labor_projection(s,0,r)
        self.assertEqual({(c['relative']['dx'],c['relative']['dy']) for c in p['worked_positions']},
                         {(0,0),(0,-2),(1,3),(-1,-3)})

    def test_odd_city_coordinates_use_same_original_doubled_x_offsets(self):
        s,r=inputs();s['cities'][0].update(x=9,y=9)
        s['map']['tiles']=[]
        p=city_labor_projection(s,0,r)
        self.assertEqual([c['position'] for c in p['worked_positions']],[{'x':9,'y':9},{'x':7,'y':9}])
        self.assertTrue(all((c['position']['x']-c['position']['y'])%2==0 for c in p['city_radius'] if c['position']))

    def test_round_world_wrap_and_flat_world_boundary(self):
        s,r=inputs();s['cities'][0]['x']=0;s['map']['tiles']=[]
        p=city_labor_projection(s,0,r)
        self.assertEqual(p['worked_positions'][1]['position'],{'x':30,'y':8})
        self.assertEqual(p['worked_positions'][1]['knowledge'],'unexplored')
        s['settings']['round_world']=False
        p=city_labor_projection(s,0,r)
        self.assertIsNone(p['worked_positions'][1]['position'])
        self.assertEqual(p['worked_positions'][1]['knowledge'],'outside_map')
        self.assertTrue(p['warnings'])

    def test_polar_outside_and_unexplored_tiles_remain_unknown(self):
        s,r=inputs();s['cities'][0].update(x=8,y=0);s['map']['tiles']=[]
        p=city_labor_projection(s,0,r)
        self.assertTrue(any(c['knowledge']=='outside_map' for c in p['city_radius']))
        self.assertTrue(any(c['knowledge']=='unexplored' for c in p['city_radius']))
        self.assertTrue(all(c['terrain'] is None and c['original_base_yields'] is None for c in p['city_radius']))

    def test_only_known_terrain_and_remembered_work_forwarded(self):
        s,r=inputs();s['map']['seed']=1234
        s['map']['tiles'][1].update(hidden_owner='SECRET CIV',actual_improvements=['mine'],ai_fertility=15)
        p=city_labor_projection(s,0,r)
        west=p['worked_positions'][1]
        self.assertEqual(west['remembered_improvements'],['road'])
        self.assertNotIn('SECRET',str(p));self.assertNotIn('actual_improvements',str(p));self.assertNotIn('1234',str(p))
        self.assertEqual(west['terrain'],{'id':2,'name':'TEST Grassland'})

    def test_base_rules_yields_not_actual_forecast_or_city_sum(self):
        s,r=inputs();r['terrain'][0].update(food=9,shields=8,trade=7)
        p=city_labor_projection(s,0,r)
        self.assertEqual(p['worked_positions'][0]['original_base_yields'],dict(food=9,shields=8,trade=7))
        self.assertTrue(all(c['actual_yields'] is None for c in p['city_radius']))
        self.assertEqual(p['city_totals_as_saved']['food_produced'],4)
        self.assertIn('Do not sum',p['yield_note'])

    def test_missing_rules_leave_base_yields_unknown(self):
        s,_=inputs();p=city_labor_projection(s,0)
        self.assertTrue(all(c['original_base_yields'] is None for c in p['city_radius']))
        self.assertEqual(p['worked_positions'][0]['terrain']['id'],2)

    def test_specialists_and_happiness_are_saved_facts_not_recommendations(self):
        s,r=inputs();s['cities'][0].update(size=3,specialist_count=2,specialists={'entertainer':1,'scientist':1},
            happy=1,unhappy=1,disorder=True)
        p=city_labor_projection(s,0,r)
        self.assertTrue(p['labor_balance']['consistent']);self.assertTrue(p['specialists']['type_counts_complete'])
        self.assertEqual(p['happiness'],dict(happy=1,unhappy=1,disorder=True,celebrating=False))
        self.assertEqual(p['native_actions'],[])
        self.assertNotIn('recommendation',p)
        self.assertFalse(any('screen' in c or 'center' in c for c in p['city_radius']))

    def test_labor_and_specialist_mismatches_reported_not_fixed(self):
        s,r=inputs();s['cities'][0].update(size=4,specialist_count=2,specialists={'scientist':1})
        p=city_labor_projection(s,0,r)
        self.assertFalse(p['labor_balance']['consistent'])
        self.assertFalse(p['specialists']['type_counts_complete']);self.assertEqual(p['specialists']['untyped_count'],1)
        self.assertEqual(len(p['warnings']),2)
        self.assertEqual(s['cities'][0]['worked_tiles_bits'],[32,0,16])

    def test_invalid_city_owner_bitmap_or_revision_rejected(self):
        for field,value in [('owner',2),('worked_tiles_bits',[32,0]),('worked_tiles_bits',[32,0,0]),('worked_tiles_bits',[32,0,0xf0]),('specialist_count',-1)]:
            s,r=inputs();s['cities'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(CityLaborError):city_labor_projection(s,0,r)
        s,r=inputs();s['evidence']={}
        with self.assertRaises(CityLaborError):city_labor_projection(s,0,r)

    def test_duplicate_known_tile_and_malformed_rules_rejected(self):
        s,r=inputs();s['map']['tiles'].append(dict(s['map']['tiles'][0]))
        with self.assertRaises(CityLaborError):city_labor_projection(s,0,r)
        s,r=inputs();r['terrain'][0]['food']='9'
        with self.assertRaises(CityLaborError):city_labor_projection(s,0,r)

    def test_returned_projection_does_not_mutate_inputs(self):
        s,r=inputs();original=deepcopy((s,r));p=city_labor_projection(s,0,r)
        p['worked_positions'][1]['remembered_improvements'].append('TEST')
        p['specialists']['stored_type_counts']['scientist']=99
        self.assertEqual((s,r),original)

    def test_optional_original_west_worker_fixture(self):
        root=Path(__file__).resolve().parents[1]
        save=root/'.runtime/rome-city.sav';bundle=root/'engine/game/civ2-win31.zip'
        if not save.exists() or not bundle.exists():self.skipTest('private original calibration not supplied')
        with zipfile.ZipFile(bundle) as z:text=z.read('civ2/RULES.TXT').decode('cp1252')
        state=parse_save(save.read_bytes(),rules_text=text)
        p=city_labor_projection(state,0,parse_rules(text))
        self.assertEqual(p['worked_tiles_bits'],[32,0,16])
        self.assertEqual([c['position'] for c in p['worked_positions']],[{'x':42,'y':40},{'x':40,'y':40}])
        self.assertTrue(all(c['terrain']['name']=='Grassland' for c in p['worked_positions']))
        self.assertTrue(p['labor_balance']['consistent'])
        self.assertEqual(p['city_totals_as_saved']['food_produced'],4)
        self.assertEqual(p['native_actions'],[])


if __name__=='__main__':unittest.main()
