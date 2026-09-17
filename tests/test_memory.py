"""Synthetic TEST-only Win16 wire capsules, never native run/win evidence."""
import base64
import copy
import hashlib
import json
import struct
import tempfile
from pathlib import Path
import unittest
import zlib
from unittest import mock

from civ2 import memory
from civ2.save import parse_save
from test_save import fixture


def topology(nonce, task=4096):
    def window(handle, parent, kind, rect, top=0):
        return dict(hwnd=handle,parent=parent,owner=0,task=task,top=top,
                    foreign_above_root=0,root_related=1,enabled=1,style=0,
                    center_exposed=1,rect=list(rect),**{'class':kind},caption='')
    windows=[window(100,0,'MSWindowClass',(-4,-4,644,484),1),
             window(101,100,'MSWindowClass',(0,38,462,480)),
             window(102,100,'MSWindowClass',(462,38,640,174)),
             window(103,100,'MSWindowClass',(462,175,640,480)),
             window(104,101,'MSControlClass',(9,43,27,61)),
             window(105,101,'MSControlClass',(29,43,47,61))]
    return dict(version=1,nonce=nonce,ticks=100,active=100,active_task=task,root=100,
                root_count=1,game_task=task,status='observed',windows=windows,
                hit_grid=[[min(639,16+76*i),min(479,44+70*j),100,task] for j in range(7) for i in range(9)],
                stable_active=True,overflow=False)


def wire(save=None, *, nonce='a'*32, tree=None, map_owner=4096, map_selector=4001, extra=b''):
    data,unit_base,city_base=fixture()
    if save is not None:data=save
    data=bytes(data);module,task=2048,4096
    _,_,area,_,_,lx,ly=struct.unpack_from('<7H',data,13432)
    unit_base=13432+14+13*area+2*lx*ly+1024
    city_base=unit_base+26*struct.unpack_from('<H',data,58)[0]
    tree=topology(nonce) if tree is None else tree
    tree=copy.deepcopy(tree);tree['nonce']=nonce
    segs={77:bytearray(57568),78:bytearray(38400),80:bytearray(4704)}
    s=segs[78];s[0x8b66:0x8ca2]=data[12:328];s[0x5400:0x5b90]=data[328:2264];s[0x5fc6:0x8b66]=data[2264:13432]
    units,cities=struct.unpack_from('<HH',data,58)
    segs[77][0x10b0:0x10b0+26*units]=data[unit_base:unit_base+26*units]
    s[:84*cities]=data[city_base:city_base+84*cities]
    segs[80][:14]=data[13432:13446]
    area=struct.unpack_from('<H',data,13436)[0];human=data[39]
    struct.pack_into('<HH',segs[80],0x18,0,4001)
    struct.pack_into('<HH',segs[80],0x2c+4*human,0,4011)
    t=json.dumps(tree,separators=(',',':')).encode()
    payload=b'TREE '+str(len(t)).encode()+b'\n'+t+b'\n'
    for seg,block in segs.items():
        payload+=f'SEG {seg} {3000+seg*2} {3001+seg*2} 2 {len(block)} {module}\n'.encode()+block+b'\n'
    terrain=data[13446+7*area:13446+13*area];known=data[13446+(human-1)*area:13446+human*area]
    payload+=f'MAP 0 4000 {map_selector} {map_owner} 0 {6*area} {6*area}\n'.encode()+terrain+b'\n'
    payload+=f'MAP {human} 4010 4011 {map_owner} 0 {area} {area}\n'.encode()+known+b'\n'+extra
    checksum=2166136261
    for b in payload:checksum=((checksum^b)*16777619)&0xffffffff
    header=f'C2OBS2 {nonce} 100 {module} {task} {len(payload)} {checksum:08x}\n'.encode().ljust(128,b' ')
    return (header+payload+b'\nEND2 '+nonce.encode()+b'\n').ljust(memory.WIRE_SIZE,b' ')


def capsule(wires=None, **changes):
    options=dict(image_sha256=['c'*64]*3,input_sequence_before=7,input_sequence_after=7,elapsed_ms=1100,
                 save_inventory_initial=[],save_inventory_before=[],save_inventory_after=[],
                 runtime_provenance={'original_exe_sha256':memory.EXE_SHA256,'helper_sha256':memory.HELPER_SHA256})
    options.update(changes)
    return memory.capsule_from_wires(wires or [wire(),wire(nonce='b'*32)],**options)


class MemoryTests(unittest.TestCase):
    def test_owned_projection_matches_original_field_parser_with_honest_source(self):
        native=parse_save(bytes(fixture()[0]));actual=memory.parse_memory(capsule())
        self.assertEqual({k:v for k,v in actual.items() if k!='evidence'},
                         {k:v for k,v in native.items() if k!='evidence'})
        self.assertEqual(actual['evidence']['kind'],'live_memory')
        self.assertNotIn('save_sha256',actual['evidence'])
        self.assertEqual(actual['evidence']['observation_sha256'],hashlib.sha256(capsule()).hexdigest())
        self.assertNotIn('SECRET',json.dumps(actual))
        self.assertEqual([u['id'] for u in actual['visible_units']],[1])
        self.assertEqual(actual['map']['tiles'][0]['known_improvements'],['road'])

    def test_hidden_enemy_and_unexplored_changes_never_reach_model_state(self):
        data,_,city_base=fixture();base=memory.parse_memory(capsule())
        struct.pack_into('<I',data,2264+2*1396+2,999999)
        data[city_base+2*84+9]=99;data[city_base+2*84+57]=47
        other=memory.parse_memory(capsule([wire(data),wire(data,nonce='b'*32)]))
        base.pop('evidence');other.pop('evidence');self.assertEqual(base,other)

    def test_stale_truncated_corrupt_and_unexpected_wire_rejected(self):
        raw=wire()
        for value in [raw[:-1],raw[:800]+bytes([raw[800]^1])+raw[801:],raw[:-1]+b'!',wire(extra=b'EXTRA\n')]:
            with self.subTest(size=len(value)),self.assertRaises(memory.MemoryObservationError):memory.decode_wire(value)
        with self.assertRaisesRegex(memory.MemoryObservationError,'Stale'):memory.decode_wire(raw,'b'*32)

    def test_native_pointer_and_owner_are_bound(self):
        for value in [wire(map_owner=2048),wire(map_selector=4999)]:
            with self.assertRaisesRegex(memory.MemoryObservationError,'pointer'):memory.decode_wire(value)

    def test_modals_and_foreign_or_extra_child_windows_fail_closed(self):
        for change in ('city','modal','foreign','overlay','hit'):
            t=topology('a'*32)
            if change=='city':t['windows']=t['windows'][:1]
            elif change=='modal':t['active']=200
            elif change=='foreign':t['status']='unknown_foreground'
            elif change=='overlay':t['windows'].append(copy.deepcopy(t['windows'][-1]))
            else:t['hit_grid'][0][3]=999
            with self.subTest(change=change),self.assertRaises(memory.MemoryObservationError):memory.decode_wire(wire(tree=t))

    def test_state_image_or_input_change_and_repeated_nonce_are_rejected(self):
        data,_,_=fixture();data[2264+1396+2]+=1
        for args,kwargs in [([wire(),wire(data,nonce='b'*32)],{}),([wire(),wire()],{}),
                            (None,{'input_sequence_after':8})]:
            with self.assertRaises(memory.MemoryObservationError):capsule(args,**kwargs)

    def test_blinking_frames_do_not_claim_pixel_identity_or_weaken_state_binding(self):
        data=capsule(image_sha256=['c'*64,'d'*64,'c'*64])
        self.assertFalse(json.loads(data)['proof']['frame_images_identical'])
        self.assertEqual(memory.parse_memory(data)['turn'],1)
        changed=json.loads(data);changed['proof']['frame_images_identical']=True
        with self.assertRaisesRegex(memory.MemoryObservationError,'identity label'):
            memory.parse_memory(memory._canonical(changed))

    def test_campaign_start_is_explicit_one_shot_and_never_forgives_later_saves(self):
        auto={'name':'CA_AUTO.SAV','size':1000,'modifiedAt':'2026-09-16T00:00:00.000Z'}
        inventory=[]
        game=mock.Mock()
        def rpc(name,*args):
            if name=='listSaves':return copy.deepcopy(inventory)
            if name=='observerProvenance':return {'original_exe_sha256':memory.EXE_SHA256,'helper_sha256':memory.HELPER_SHA256}
            return {'inputSequence':7}
        game.rpc.side_effect=rpc
        with tempfile.TemporaryDirectory() as d:
            observer=memory.LiveMemoryObserver(game,d)
            inventory.append(auto)
            preferences={'autosave_disabled':True,'checkbox_after':{'Autosave each turn':False}}
            start=observer.begin_campaign(preferences)
            self.assertEqual(start['startup_inventory'],[])
            self.assertEqual(start['campaign_inventory'],[auto])
            self.assertEqual(len(start['startup_changes']),1)
            self.assertEqual(memory.parse_memory(capsule(save_inventory_initial=[auto],save_inventory_before=[auto],save_inventory_after=[auto],campaign_start=start))['turn'],1)
            with self.assertRaises(memory.MemoryObservationError):observer.begin_campaign(preferences)
            inventory[0]=auto|{'size':1100}
            with self.assertRaisesRegex(memory.MemoryObservationError,'save created'):observer.read()

    def test_campaign_start_cannot_forgive_non_autosave_or_follow_a_read(self):
        game=mock.Mock();inventory=[]
        game.rpc.side_effect=lambda name,*args: copy.deepcopy(inventory) if name=='listSaves' else {'original_exe_sha256':memory.EXE_SHA256,'helper_sha256':memory.HELPER_SHA256}
        with tempfile.TemporaryDirectory() as d:
            observer=memory.LiveMemoryObserver(game,d)
            inventory.append({'name':'manual.sav','size':10,'modifiedAt':'2026-09-16T00:00:00.000Z'})
            preferences={'autosave_disabled':True,'checkbox_after':{'Autosave each turn':False}}
            with self.assertRaisesRegex(memory.MemoryObservationError,'startup autosaves'):observer.begin_campaign(preferences)
            inventory.clear();observer._reads_started=True
            with self.assertRaisesRegex(memory.MemoryObservationError,'cannot be reset'):observer.begin_campaign(preferences)

    def test_persisted_boot_boundary_is_adopted_exactly_without_resetting_inventory(self):
        auto={'name':'CA_AUTO.SAV','size':1000,'modifiedAt':'2026-09-16T00:00:00.000Z'}
        boundary=dict(phase='after_verified_autosave_off_before_first_observation',startup_inventory=[],
                      campaign_inventory=[auto],startup_changes=[dict(name=auto['name'],before=None,after=auto)],preferences_sha256='a'*64)
        game=mock.Mock();inventory=[auto]
        game.rpc.side_effect=lambda name,*args: copy.deepcopy(inventory) if name=='listSaves' else {'original_exe_sha256':memory.EXE_SHA256,'helper_sha256':memory.HELPER_SHA256}
        with tempfile.TemporaryDirectory() as d:
            observer=memory.LiveMemoryObserver(game,d)
            self.assertEqual(observer.adopt_campaign_start(boundary),boundary)
            self.assertEqual(observer.campaign_start,boundary)
            self.assertEqual(observer.startup_save_inventory,[])
            with self.assertRaises(memory.MemoryObservationError):observer.adopt_campaign_start(boundary)
            inventory[0]=auto|{'size':2000}
            changed=memory.LiveMemoryObserver(game,d)
            with self.assertRaisesRegex(memory.MemoryObservationError,'boundary differs'):changed.adopt_campaign_start(boundary)
            with self.assertRaises(memory.MemoryObservationError):changed.adopt_campaign_start(None)

    def test_incomplete_mailbox_is_retried_but_never_returned(self):
        game=mock.Mock();responses=[RuntimeError('incomplete fixed mailbox'),{'encoding':'base64','data':base64.b64encode(wire()).decode()}]
        def rpc(name,*args):
            if name=='listSaves':return []
            if name=='observerProvenance':return {'original_exe_sha256':memory.EXE_SHA256,'helper_sha256':memory.HELPER_SHA256}
            if name=='observerRequest':return {'nonce':args[0],'inputSequence':7,'gameInput':False}
            result=responses.pop(0)
            if isinstance(result,Exception):raise result
            return result
        game.rpc.side_effect=rpc
        with tempfile.TemporaryDirectory() as d:
            observer=memory.LiveMemoryObserver(game,d)
            with mock.patch('civ2.memory.secrets.token_hex',return_value='a'*32),mock.patch('civ2.memory.time.sleep'):
                self.assertEqual(observer._read_wire(7),wire())

    def test_modern_inventory_hash_detects_same_size_edits(self):
        original=dict(name='AUTO.SAV',size=1000,modifiedAt=None,sha256='a'*64)
        self.assertEqual(memory._save_inventory([original]),[original])
        capsule(save_inventory_initial=[original],save_inventory_before=[original],save_inventory_after=[original])
        changed=original|{'sha256':'b'*64}
        with self.assertRaisesRegex(memory.MemoryObservationError,'save created'):
            capsule(save_inventory_initial=[original],save_inventory_before=[original],save_inventory_after=[changed])
        for bad in (original|{'sha256':'bad'},original|{'modifiedAt':'2026-09-16T00:00:00.000Z'},
                    {k:v for k,v in original.items() if k!='sha256'}):
            with self.assertRaises(memory.MemoryObservationError):memory._save_inventory([bad])

    def test_any_native_save_creation_or_change_is_fatal(self):
        entry={'name':'TEST New Save.SAV','size':1234,'modifiedAt':'2026-09-16T00:00:00.000Z'}
        with self.assertRaisesRegex(memory.MemoryObservationError,'save created'):capsule(save_inventory_after=[entry])
        old=entry|{'size':1000}
        with self.assertRaisesRegex(memory.MemoryObservationError,'save created'):
            capsule(save_inventory_initial=[old],save_inventory_before=[old],save_inventory_after=[entry])

    def test_capsule_pin_hash_canonical_and_decompression_limits(self):
        original=json.loads(capsule())
        for change in ('exe','helper','wirehash','zipbomb','duplicate'):
            c=copy.deepcopy(original)
            if change=='exe':c['original_exe_sha256']='0'*64
            elif change=='helper':c['helper_sha256']='0'*64
            elif change=='wirehash':c['snapshots'][0]['wire_sha256']='0'*64
            elif change=='zipbomb':c['snapshots'][0]['wire_zlib_base64']=base64.b64encode(zlib.compress(b'X'*(memory.WIRE_SIZE+1))).decode()
            else:c['proof']['runtime_provenance']['helper_sha256']='0'*64
            with self.subTest(change=change),self.assertRaises(memory.MemoryObservationError):memory.parse_memory(memory._canonical(c))
        with self.assertRaises(memory.MemoryObservationError):memory.parse_memory(capsule()+b' ')

    def test_observer_checks_guest_pins_and_inventory_before_any_read(self):
        game=mock.Mock();game.rpc.side_effect=[[],{'original_exe_sha256':'0'*64,'helper_sha256':memory.HELPER_SHA256}]
        with tempfile.TemporaryDirectory() as d,self.assertRaises(memory.MemoryObservationError):memory.LiveMemoryObserver(game,d)
        self.assertEqual([c.args[0] for c in game.rpc.call_args_list],['listSaves','observerProvenance'])

    def test_no_save_fallback_when_read_fails_and_pause_is_guaranteed(self):
        game=mock.Mock()
        game.rpc.side_effect=lambda name,*a: ([] if name=='listSaves' else
            {'original_exe_sha256':memory.EXE_SHA256,'helper_sha256':memory.HELPER_SHA256} if name=='observerProvenance'
            else {'inputSequence':7})
        with tempfile.TemporaryDirectory() as d:
            observer=memory.LiveMemoryObserver(game,d)
            with mock.patch.object(observer,'_read_wire',side_effect=memory.MemoryObservationError('TEST')), \
                 mock.patch.object(Path,'read_bytes',return_value=b'\x89PNG\r\n\x1a\n'+b'\0'*8+struct.pack('>II',640,480)):
                with self.assertRaises(memory.MemoryObservationError):observer.read()
        names=[c.args[0] for c in game.rpc.call_args_list]
        self.assertEqual(names[-1],'pause');self.assertFalse({'readSave','importSave','key','chord'}&set(names))


if __name__=='__main__':unittest.main()
