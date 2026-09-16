"""Synthetic TEST-only saves; no original game assets are checked in."""
import copy
import struct
import unittest
import zipfile
from pathlib import Path

from civ2.save import SaveFormatError, parse_rules, parse_save


def fixture():
    width2, height, area = 32, 16, 256
    unit_base = 13432+14+13*area+2*8*4+1024
    city_base = unit_base+26*4
    data = bytearray(city_base+84*3+64)
    data[:10] = b"CIVILIZE\0\x1a"
    struct.pack_into("<H",data,10,39)
    data[12]=16  # Standard HP/firepower combat is enabled by this bit.
    data[252:308]=b'\xff'*56  # No public wonders built in the TEST world.
    struct.pack_into("<HhH",data,28,1,-4000,0)
    struct.pack_into("<H",data,34,0)
    data[39]=data[40]=data[41]=1
    data[44],data[45],data[46],data[47]=2,2,0b111111,2
    struct.pack_into("<HH",data,58,4,3)
    struct.pack_into("<7H",data,13432,width2,height,area,0,39,8,4)
    p=2264+1396
    struct.pack_into("<I",data,p+2,50)
    data[p+19],data[p+20],data[p+21]=6,4,1
    data[p+10]=255
    data[159+1]=2
    def tile(x,y,known=True,memory=0,actual=0):
        i=y*16+x//2
        data[13432+14+i]=memory
        o=13432+14+7*area+6*i
        data[o:o+6]=bytes([2,actual,0,0,2 if known else 0,0])
    for x,y in [(2,2),(4,2),(6,2),(20,2)]:tile(x,y)
    tile(2,2,memory=16,actual=16|4|8)
    # Four unit slots: owned, genuinely adjacent-visible, far-known, hidden.
    for uid,(x,y,owner,visibility) in enumerate([(2,2,1,0),(4,2,2,2),(20,2,2,2),(22,2,2,2)]):
        o=unit_base+26*uid
        struct.pack_into("<hh",data,o,x,y)
        data[o+6],data[o+7],data[o+9]=0,owner,visibility
        data[o+15]=data[o+16]=255
        struct.pack_into("<hh",data,o+18,-1,-1)
    for cid,(x,y,owner,name) in enumerate([(2,2,1,b'TEST Rome'),(6,2,2,b'TEST Known'),(22,2,2,b'SECRET CITY')]):
        o=city_base+84*cid
        struct.pack_into("<hh",data,o,x,y)
        data[o+8],data[o+9],data[o+12],data[o+14]=owner,3,2,2
        data[o+32:o+32+len(name)]=name
        data[o+57]=254  # Barracks: inverse improvement index2.
    return data,unit_base,city_base


class SaveTests(unittest.TestCase):
    def test_public_wonder_status_does_not_expose_foreign_city_pointer(self):
        data,_,_=fixture()
        struct.pack_into('<hhh',data,252,2,0,-2)
        s=parse_save(bytes(data));w=s['wonders']
        self.assertEqual(len(w),28)
        self.assertEqual((w[0]['status'],w[0]['owned']),('built',False))
        self.assertEqual((w[1]['status'],w[1]['owned']),('built',True))
        self.assertEqual(w[2]['status'],'destroyed')
        self.assertEqual(w[3]['status'],'not_built')
        self.assertTrue(all('city_id' not in item and 'x' not in item for item in w))

    def test_view_fields_are_not_claimed_as_viewport_center(self):
        data,_,city_base=fixture();other=city_base+84*3+63
        data.extend(bytes(1500))
        struct.pack_into('<hh',data,other,2,2)
        struct.pack_into('<hhh',data,other+48+1314,6,2,0)
        s=parse_save(bytes(data))
        self.assertEqual(s['view'],dict(cursor={'x':2,'y':2},last_clicked={'x':6,'y':2},zoom=0,viewport_center=None))
        self.assertEqual(s['year'],-4000)

    def test_standard_combat_bit_is_inverted_not_checked_box_polarity(self):
        data,_,_=fixture()
        self.assertFalse(parse_save(bytes(data))['settings']['simplified_combat'])
        data[12] &= ~16
        self.assertTrue(parse_save(bytes(data))['settings']['simplified_combat'])

    def test_starting_civilizations_excludes_barbarians_and_not_inferred_later(self):
        data,_,_=fixture()
        self.assertEqual(parse_save(bytes(data))['settings']['starting_civilizations'],5)
        data[46] &= ~1  # The barbarians do not count as a selected civilization.
        self.assertEqual(parse_save(bytes(data))['settings']['starting_civilizations'],5)
        struct.pack_into('<H',data,28,2)
        self.assertIsNone(parse_save(bytes(data))['settings']['starting_civilizations'])

    def test_original_layout_owned_actor_and_settings(self):
        data,_,_=fixture();s=parse_save(bytes(data))
        self.assertEqual((s['version'],s['turn'],s['year_raw']),(39,1,-4000))
        self.assertEqual(s['settings']['difficulty'],'Prince')
        self.assertEqual(s['settings']['barbarians'],'Restless Tribes')
        self.assertEqual(s['settings']['starting_civilizations'],5)
        self.assertFalse(s['settings']['simplified_combat'])
        self.assertEqual(s['player']['treasury'],50)
        self.assertEqual(s['player']['government'],'Despotism')
        self.assertEqual(s['player']['known_technology_ids'],[1])
        self.assertEqual([u['id'] for u in s['units']],[0])
        self.assertEqual(s['cities'][0]['production'],{'kind':'improvement','id':2,'name':None})

    def test_knowledge_is_not_omniscient_map_or_memory_as_sight(self):
        data,_,_=fixture();s=parse_save(bytes(data))
        self.assertEqual(s['map']['explored_count'],4)
        self.assertEqual([u['id'] for u in s['visible_units']],[1])
        self.assertEqual([c['name'] for c in s['known_cities']],['TEST Known'])
        self.assertNotIn('owner',s['known_cities'][0])
        self.assertNotIn('production',s['known_cities'][0])
        self.assertEqual(s['known_cities'][0]['last_known_size'],2)
        self.assertEqual(s['map']['tiles'][0]['known_improvements'],['road'])
        self.assertNotIn('SECRET',str(s))
        self.assertNotIn('goto',s['visible_units'][0])

    def test_hidden_world_changes_do_not_change_observation(self):
        data,_,city_base=fixture();original=parse_save(bytes(data))
        ai=2264+1396*2
        struct.pack_into('<I',data,ai+2,29999)
        data[ai+88:ai+100]=b'\xff'*12
        data[city_base+84*2+9]=99
        data[city_base+84*2+57]=47
        result=parse_save(bytes(data))
        original.pop('evidence');result.pop('evidence')
        self.assertEqual(original,result)

    def test_unit_mask_alone_cannot_reveal_unknown_tile(self):
        data,_,_=fixture();s=parse_save(bytes(data))
        self.assertNotIn(3,[u['id'] for u in s['visible_units']])

    def test_known_city_marker_alone_does_not_reveal_city(self):
        data,_,city_base=fixture()
        # Unknown foreign city marked known by city record; terrain still dark.
        data[city_base+2*84+12]=255
        self.assertNotIn('SECRET',str(parse_save(bytes(data))))

    def test_dead_record_does_not_become_actor(self):
        data,unit_base,_=fixture()
        struct.pack_into('<h',data,unit_base,-1)
        self.assertEqual(parse_save(bytes(data))['units'],[])

    def test_round_world_sight_wraps(self):
        data,unit_base,_=fixture()
        struct.pack_into('<hh',data,unit_base,0,2)
        struct.pack_into('<hh',data,unit_base+26,30,2)
        data[13432+14+7*256+6*(2*16+15)+4]=2
        self.assertEqual([u['id'] for u in parse_save(bytes(data))['visible_units']],[1])
        data[13]=128
        self.assertEqual(parse_save(bytes(data))['visible_units'],[])

    def test_diplomacy_only_human_contacted_relations(self):
        data,_,_=fixture();p=2264+1396
        data[p+32+4*2]=1|4|128
        data[p+32+4*3]=8  # Unknown relation should not leak.
        d=parse_save(bytes(data))['diplomacy']
        self.assertEqual(len(d),1);self.assertEqual(d[0]['civ_id'],2)
        self.assertTrue(d[0]['peace']);self.assertTrue(d[0]['embassy'])

    def test_mge_tot_and_other_versions_rejected(self):
        for version in (0,40,44,49,50,295):
            with self.subTest(version=version):
                data,_,_=fixture();struct.pack_into('<H',data,10,version)
                with self.assertRaises(SaveFormatError):parse_save(bytes(data))

    def test_bad_header_truncation_and_counts_rejected(self):
        data,_,_=fixture()
        for bad in (b'',bytes(data[:100]),bytes(data[:-65]),b'WRONG'+bytes(data[5:])):
            with self.subTest(length=len(bad)):
                with self.assertRaises(SaveFormatError):parse_save(bad)
        struct.pack_into('<H',data,58,9999)
        with self.assertRaises(SaveFormatError):parse_save(bytes(data))

    def test_invalid_maps_rejected(self):
        for offset,value in [(13432,31),(13432+4,255),(13432+10,99)]:
            data,_,_=fixture();struct.pack_into('<H',data,offset,value)
            with self.assertRaises(SaveFormatError):parse_save(bytes(data))

    def test_cheat_revealed_multiplayer_and_bad_rates_rejected(self):
        for offset,value in [(43,1),(15,128),(20,16),(47,6),(39,0),(2264+1396+19,11)]:
            data,_,_=fixture();data[offset]=value
            with self.assertRaises(SaveFormatError):parse_save(bytes(data))

    def test_invalid_active_actor_rejected(self):
        data,unit_base,_=fixture();data[unit_base+7]=9
        with self.assertRaises(SaveFormatError):parse_save(bytes(data))

    def test_rules_stats_and_codes_not_from_later_game(self):
        rules=parse_rules('''@UNITS
TEST Settler,nil,0,1.,0,0a,1d,2h,1f,4,0,5,nil,0000
@CIVILIZE
TEST Alphabet,5,1,nil,nil,0,3 ; Alp
@LEADERS
TEST Caesar,TEST Livia,0,1,1,TEST Romans,TEST Roman
@IMPROVE
Nothing,1,0,nil
TEST Palace,10,0,Mas
TEST Barracks,4,1,nil
''')
        self.assertEqual(rules['units'][0]['max_hp'],20)
        self.assertEqual(rules['units'][0]['shield_cost'],40)
        self.assertEqual(rules['advances'][0]['code'],'Alp')
        self.assertEqual(rules['improvements'][2]['name'],'TEST Barracks')

    def test_optional_private_original_tutorial(self):
        # Runtime owns this ignored asset. Reproduction needs user's own bundle.
        path=Path(__file__).resolve().parents[1]/'engine/game/civ2-win31.zip'
        if not path.exists():self.skipTest('original assets not supplied')
        with zipfile.ZipFile(path) as archive:
            data=archive.read('civ2/TUTORIAL.SAV')
            rules=archive.read('civ2/RULES.TXT').decode('cp1252')
        s=parse_save(data,rules_text=rules)
        self.assertEqual(s['evidence']['save_sha256'],'21b36d9a00aaf1941b124130ffd7225984d2d77a53e36d0a8e25c3c88557cc49')
        self.assertEqual((s['player']['tribe'],s['player']['treasury']),('Americans',50))
        self.assertEqual([(u['type'],u['x'],u['y']) for u in s['units']],[('Settlers',35,47)])
        self.assertEqual(s['map']['explored_count'],21)
        self.assertFalse(s['settings']['simplified_combat'])
        self.assertEqual(s['cities'],[]);self.assertEqual(s['known_cities'],[])


if __name__=='__main__':unittest.main()
