"""Native stack-link projection never leaks a foreign linked actor."""
import json
import struct
import unittest
from pathlib import Path
from copy import deepcopy

from civ2.save import parse_save
from civ2.memory import parse_memory
from tests.test_save import fixture


def stack_fixture():
    data,base,_=fixture()
    for i in range(3):
        struct.pack_into('<hh',data,base+26*i,2,2)
        data[base+26*i+7]=1
    # Native stack order 2 -> 0 -> 1 deliberately differs from array order.
    for i,links in enumerate(((2,1),(0,-1),(-1,0))):
        struct.pack_into('<hh',data,base+26*i+22,*links)
    return data,base


class UnitStackTests(unittest.TestCase):
    def test_opt_in_preserves_old_projection_and_native_chain_order(self):
        data,_=stack_fixture();old=parse_save(bytes(data));new=parse_save(bytes(data),include_stack_links=True)
        self.assertNotIn('owned_unit_stacks',old)
        self.assertEqual({k:v for k,v in new.items() if k!='owned_unit_stacks'},old)
        self.assertEqual(new['owned_unit_stacks'][0]['unit_ids'],[2,0,1])
        self.assertEqual(new['owned_unit_stacks'][0]['links'],[
            dict(id=2,previous=None,next=0),dict(id=0,previous=2,next=1),dict(id=1,previous=0,next=None)])

    def test_rejects_foreign_cross_tile_cycle_self_link_and_missing_reciprocity(self):
        for case in ('foreign','cross_tile','cycle','self','one_way','disconnected','outside'):
            data,base=stack_fixture()
            if case=='foreign':data[base+26+7]=2
            elif case=='cross_tile':struct.pack_into('<hh',data,base+26,4,2)
            elif case=='cycle':
                struct.pack_into('<hh',data,base+26+22,0,2);struct.pack_into('<hh',data,base+52+22,1,0)
            elif case=='self':struct.pack_into('<h',data,base+22,0)
            elif case=='one_way':struct.pack_into('<h',data,base+22,-1)
            elif case=='disconnected':struct.pack_into('<hh',data,base+26+22,-1,-1)
            else:struct.pack_into('<h',data,base+22,32767)
            with self.subTest(case=case):
                stacks=parse_save(bytes(data),include_stack_links=True)['owned_unit_stacks']
                self.assertFalse(any(s['x']==2 and s['y']==2 for s in stacks))
                self.assertNotIn('32767',json.dumps(stacks))

    def test_actual_owned_memory_stack_matches_activation_calibration(self):
        path=Path('.runtime/activation-calibration/awake-before-observation.bin')
        if not path.exists():self.skipTest('Private original calibration unavailable')
        data=path.read_bytes();old=parse_memory(data);new=parse_memory(data,include_stack_links=True)
        self.assertEqual({k:v for k,v in new.items() if k!='owned_unit_stacks'},old)
        stack=next(s for s in new['owned_unit_stacks'] if (s['x'],s['y'])==(54,24))
        self.assertEqual(stack['unit_ids'],[12,6])
        self.assertEqual(stack['links'],[dict(id=12,previous=None,next=6),dict(id=6,previous=12,next=None)])


if __name__=='__main__':unittest.main()
