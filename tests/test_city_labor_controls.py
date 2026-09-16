"""Calibrated labor choices and native-save comparisons; no game inputs."""
from copy import deepcopy
import unittest
from civ2.city import WORKED_BITS
from civ2.city_controls import (CityControlError,LABOR_POINTS,city_control_candidates,
    city_control_request_for,validate_city_control,city_labor_result)
from test_city_controls import inputs as base_inputs,reviewed


def inputs(free=False):
    state,screen,rules=base_inputs();city=state['cities'][0]
    city.update(x=8,y=8,size=1,worked_tiles_bits=[0 if free else 32,0,16],
                specialist_count=1 if free else 0,specialists={'entertainer':1} if free else {})
    state['map']['tiles']=[dict(x=8+dx,y=8+dy,terrain_id=2,terrain='TEST Grassland',
        river=False,known_improvements=[]) for _,_,dx,dy in WORKED_BITS]
    screen['evidence']={'city_resource_map':{
        'resource_map':{'center':[104,255],'bounds':[62,248,84,14],'source_line':8},
        'citizens':{'center':[103,112],'bounds':[76,105,54,14],'source_line':3}}}
    return state,screen,rules


def labor(state,screen,rules,record=None):
    return {k:a for k,a in city_control_candidates(state,screen,record,rules,labor_ready=True).items() if a['kind']=='city_labor'}


class LaborControlTests(unittest.TestCase):
    def test_one_worked_square_can_be_removed_without_touching_center(self):
        s,c,r=inputs();actions=labor(s,c,r)
        self.assertEqual(list(actions),['labor_remove_worker_2'])
        a=actions['labor_remove_worker_2']
        self.assertEqual(a['parameters']['center'],[56,192])
        self.assertEqual(a['preconditions']['labor_before']['worked_tiles_bits'],[32,0,16])
        self.assertTrue(a['parameters']['native_checkpoint_required'])
        self.assertNotIn('yield',a['label'].lower())

    def test_free_entertainer_can_be_assigned_to20_calibrated_known_slots(self):
        s,c,r=inputs(True);actions=labor(s,c,r)
        self.assertEqual(len(actions),20)
        self.assertEqual({a['parameters']['slot'] for a in actions.values()},set(range(21))-{16})
        for a in actions.values():
            self.assertEqual(a['parameters']['center'],list(LABOR_POINTS[a['parameters']['slot']]))
            validate_city_control(a,s,c,rules=r,labor_ready=True)
        self.assertNotIn('taxman',str(actions));self.assertNotIn('scientist',str(actions))

    def test_fresh_checkpoint_and_native_geometry_are_required_for_labor(self):
        s,c,r=inputs()
        self.assertFalse(any(a['kind']=='city_labor' for a in city_control_candidates(s,c,rules=r).values()))
        for change in ('scale','anchor','offset'):
            bad=deepcopy(c)
            if change=='scale':bad['width']=1280
            elif change=='anchor':bad.pop('evidence')
            else:bad['evidence']['city_resource_map']['citizens']['center'][0]+=20
            self.assertEqual(labor(s,bad,r),{})

    def test_budget_omits_labor_but_not_exit_and_is_not_native_illegality(self):
        s,c,r=inputs();record={**reviewed(), 'labor_reassignments':2}
        actions=city_control_candidates(s,c,record,r,labor_ready=True)
        self.assertEqual(set(actions),{'change_production','open_buy_quote','exit_city'})
        request=city_control_request_for(s,c,actions,record,r,labor_ready=True)
        self.assertEqual(request['state']['city_control_review']['labor_review']['remaining'],0)
        self.assertIn('not claimed illegal',request['state']['city_control_review']['labor_review']['scope'])
        with self.assertRaises(CityControlError):city_control_candidates(s,c,{**record,'labor_reassignments':41},r,labor_ready=True)

    def test_unknown_tiles_occupied_tiles_and_mixed_specialists_are_not_assigned(self):
        s,c,r=inputs(True);s['map']['tiles']=[t for t in s['map']['tiles'] if (t['x'],t['y'])!=(8,6)]
        s['visible_units']=[{'owner':2,'x':7,'y':7}]
        actions=labor(s,c,r)
        self.assertNotIn('labor_assign_entertainer_0',actions)
        self.assertNotIn('labor_assign_entertainer_1',actions)
        s['cities'][0].update(size=2,specialist_count=2,specialists={'entertainer':1,'scientist':1})
        self.assertEqual(labor(s,c,r),{})

    def test_another_owned_city_worked_square_cannot_be_assigned(self):
        s,c,r=inputs(True);other=deepcopy(s['cities'][0]);other.update(id=1,name='TEST Veii',x=10,
            worked_tiles_bits=[32,0,16],specialist_count=0,specialists={})
        s['cities'].append(other)
        self.assertNotIn('labor_assign_entertainer_6',labor(s,c,r))

    def test_bitmap_inconsistency_and_tampered_coordinates_fail_closed(self):
        s,c,r=inputs();a=next(iter(labor(s,c,r).values()));a['parameters']['center']=[104,192]
        with self.assertRaises(CityControlError):validate_city_control(a,s,c,rules=r,labor_ready=True)
        s['cities'][0]['specialist_count']=1
        self.assertEqual(labor(s,c,r),{})

    def test_native_result_distinguishes_expected_unchanged_and_wrong_square(self):
        s,c,r=inputs();action=next(iter(labor(s,c,r).values()));after=deepcopy(s)
        after['evidence']['save_sha256']='c'*64
        self.assertEqual(city_labor_result(action,s,after)['status'],'no_observed_change')
        after['cities'][0].update(worked_tiles_bits=[0,0,16],specialist_count=1,specialists={'entertainer':1})
        result=city_labor_result(action,s,after)
        self.assertEqual(result['status'],'observed_expected_change')
        self.assertEqual(result['after'],result['expected'])
        after['cities'][0]['worked_tiles_bits']=[64,0,16]
        self.assertEqual(city_labor_result(action,s,after)['status'],'unexpected_change')

    def test_assign_result_requires_exact_entertainer_consumption(self):
        s,c,r=inputs(True);action=labor(s,c,r)['labor_assign_entertainer_0'];after=deepcopy(s)
        after['cities'][0].update(worked_tiles_bits=[128,0,16],specialist_count=0,specialists={})
        after['evidence']['save_sha256']='c'*64
        self.assertEqual(city_labor_result(action,s,after)['status'],'observed_expected_change')
        after['cities'][0]['specialist_count']=1
        self.assertEqual(city_labor_result(action,s,after)['status'],'unexpected_change')
        after['turn']+=1
        with self.assertRaises(CityControlError):city_labor_result(action,s,after)


    def test_optional_original20slot_native_readback_fixture(self):
        # Private calibration assets are optional. This compares native save
        # facts/table receipts only; it performs no OCR, game input or inference.
        from pathlib import Path
        import hashlib,json
        from civ2.boot import original_rules
        from civ2.save import parse_save,parse_rules
        root=Path(__file__).resolve().parents[1]
        directory=root/'.runtime/labor-calibration-01'
        if not (directory/'report.json').exists() or not (root/'engine/game/civ2-win31.zip').exists():
            self.skipTest('Private original-game labor calibration not installed')
        report=json.loads((directory/'report.json').read_text());rules_text=original_rules();rules=parse_rules(rules_text)
        before=parse_save((directory/'empty.sav').read_bytes(),rules_text=rules_text)
        _,screen,_=inputs(True);city=before['cities'][0]
        screen['title']=f"City of {city['name']}, {abs(before['year_raw'])} B.C."
        actions=city_control_candidates(before,screen,rules=rules,labor_ready=True)
        self.assertEqual(len(report['results']),20)
        for row in report['results']:
            data=(directory/row['native_save']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),row['native_save_sha256'])
            self.assertEqual(list(LABOR_POINTS[row['slot']]),row['point'])
            after=parse_save(data,rules_text=rules_text)
            result=city_labor_result(actions[f"labor_assign_entertainer_{row['slot']}"],before,after)
            self.assertEqual(result['status'],'observed_expected_change')


if __name__=='__main__':unittest.main()
