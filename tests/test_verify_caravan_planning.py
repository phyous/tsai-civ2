"""Independent native-byte bindings for model-selected Caravan travel tasks."""
from copy import deepcopy
import struct
import unittest
from civ2.planning import request_for,category_request_for
from civ2.save import parse_save
from civ2.verify import _plan_binding,_plan_category_binding,VerificationError
from tests.test_verify import initial_save


def fixture(freight=False):
    data=bytearray(initial_save(49 if freight else 48));base=13432+14+13*2000+2*20*13+1024
    data[base+16]=0;struct.pack_into('<H',data,60,3)
    for i,(x,owner) in enumerate(((6,1),(10,1),(12,2))):
        offset=base+26+i*84;struct.pack_into('<hh',data,offset,x,8)
        data[offset+8]=owner;data[offset+9]=2;data[offset+12]=2;data[offset+14]=2
        data[offset+50]=16;data[offset+51]=8;data[offset+22]=5
        name=f'TEST City {i}'.encode();data[offset+32:offset+32+len(name)]=name
        struct.pack_into('<b',data,offset+57,-39 if i==1 else 2)
    for x in (6,8,10,12):
        off=13446+7*2000+6*(8*40+x//2);data[off]=1;data[off+4]=2
    raw=parse_save(bytes(data));state=deepcopy(raw)
    spec=dict(id=49 if freight else 48,name='TEST trade unit',domain=0,role=7,attack=0,defense=1,movement=1,max_hp=10)
    state['units'][0].update(hp=10,specification=spec,type=spec['name'])
    state['cities'][1]['production']['name']='TEST Wonder'
    rules=dict(units=[spec],improvements=[dict(id=39,name='TEST Wonder',kind='wonder')],terrain=[],advances=[])
    return state,rules,raw


class VerifyCaravanPlanning(unittest.TestCase):
    def test_native_bound_caravan_freight_targets_and_complete_category_partition(self):
        for freight in (False,True):
            state,rules,raw=fixture(freight);request,candidates=request_for(state,rules)
            saves={raw['evidence']['save_sha256']:raw}
            found=[c for c in candidates.values() if c['task'] in ('trade_delivery','assist_wonder')]
            self.assertEqual({c['task'] for c in found},{'trade_delivery','assist_wonder'})
            for task in candidates.values():_plan_binding(task,request,saves)
            req,categories=category_request_for(state,rules)
            for category in categories.values():_plan_category_binding(category,req,saves,raw['evidence']['save_sha256'])
            for task in found:self.assertNotIn('owner',task['target'])

    def test_forged_delivery_binding_cannot_add_hidden_or_invalid_targets(self):
        state,rules,raw=fixture();request,candidates=request_for(state,rules)
        original=next(c for c in candidates.values() if c['task']=='trade_delivery' and c['target']['x']==12)
        for mode in ('dead','wrongtype','role','hp','unknown_home','home','here','water','hidden','duplicate','modelmissing','extraowner','bool'):
            task=deepcopy(original);req=deepcopy(request);native=deepcopy(raw)
            if mode=='dead':native['units'][0]['hp_lost']=10
            elif mode=='wrongtype':
                native['units'][0]['type_id']=46;task['actor']['type_id']=46;req['state']['selected_unit']['type_id']=46
            elif mode=='role':req['state']['selected_unit']['specification']['role']=6
            elif mode=='hp':req['state']['selected_unit']['hp']=11
            elif mode=='unknown_home':
                native['units'][0]['home_city_id']=None;task['actor']['home_city_id']=None;req['state']['selected_unit']['home_city_id']=None
            elif mode=='home':task['target']['x']=6
            elif mode=='here':task['target']['x']=8
            elif mode=='water':next(t for t in native['map']['tiles'] if t['x']==12)['terrain']='Ocean'
            elif mode=='hidden':native['map']['tiles']=[t for t in native['map']['tiles'] if t['x']!=12]
            elif mode=='duplicate':native['known_cities']*=2
            elif mode=='modelmissing':req['state']['remembered_foreign_cities']=[]
            elif mode=='extraowner':task['target']['owner']=2
            else:task['target']['x']=True
            req['state']['planning']['targets'][task['id']]['target']=deepcopy(task['target'])
            with self.subTest(mode=mode),self.assertRaises(VerificationError):
                _plan_binding(task,req,{raw['evidence']['save_sha256']:native})

    def test_wonder_requires_current_exact_owned_production_and_unbuilt_status(self):
        state,rules,raw=fixture();request,candidates=request_for(state,rules)
        original=next(c for c in candidates.values() if c['task']=='assist_wonder')
        for mode in ('notwonder','wrongcity','differentproduction','unit','built','destroyed','duplicate','foreign','modelproduction'):
            task=deepcopy(original);req=deepcopy(request);native=deepcopy(raw)
            if mode=='notwonder':task['target']['improvement_id']=38
            elif mode=='wrongcity':task['target']['id']=0
            elif mode=='differentproduction':native['cities'][1]['production']['id']=40
            elif mode=='unit':native['cities'][1]['production']['kind']='unit'
            elif mode in ('built','destroyed'):native['wonders'][0]['status']=mode
            elif mode=='duplicate':native['wonders'].append(deepcopy(native['wonders'][0]))
            elif mode=='foreign':native['cities'][1]['owner']=2
            else:req['state']['owned_city_locations'][1]['production']['id']=40
            req['state']['planning']['targets'][task['id']]['target']=deepcopy(task['target'])
            with self.subTest(mode=mode),self.assertRaises(VerificationError):
                _plan_binding(task,req,{raw['evidence']['save_sha256']:native})


if __name__=='__main__':unittest.main()
