"""Policy-independent tests of observed original-rules eligibility."""
import unittest
import zipfile
from pathlib import Path

from civ2.rules import eligible_production,eligible_research,eligible_governments
from civ2.save import parse_rules,parse_save


def inputs():
    techs=[dict(id=i,name=code,code=code,prerequisites=['nil','nil']) for i,code in enumerate(['Bro','Pot','Map','Feu','Mon','Rep','Fun','SFl','Pla','Sup','Roc','Amp','Mas'])]
    def unit(uid,name,prereq='nil',obsolete='nil',domain=0):
        return dict(id=uid,name=name,prerequisite=prereq,obsolete_by=obsolete,domain=domain,role=1)
    def imp(i,name,prereq='nil',kind='building'):
        return dict(id=i,name=name,prerequisite=prereq,kind=kind)
    rules=dict(advances=techs,units=[unit(0,'TEST Settlers'),unit(2,'TEST Warriors',obsolete='Feu'),unit(3,'TEST Phalanx','Bro','Feu'),unit(8,'TEST Fanatics','Fun'),unit(32,'TEST Trireme','Map',domain=2),unit(45,'TEST Nuclear','Roc'),unit(51,'TEST Disabled','no')],
        improvements=[imp(0,'Nothing'),imp(1,'TEST Palace','Mas'),imp(2,'TEST Barracks'),imp(3,'TEST Granary','Pot'),imp(20,'TEST Hydro'),imp(28,'TEST Coastal'),imp(35,'TEST Structural','SFl','spaceship_part'),imp(39,'TEST Pyramid','Mas','wonder')])
    state=dict(player=dict(id=1,known_technology_ids=[0,1,2],government_id=1),
        cities=[dict(id=0,x=4,y=4,size=2,improvement_ids=[1])],
        settings=dict(round_world=True,bloodlust=False),map=dict(coordinate_width=32,tiles=[]),wonders=[])
    return state,rules


class RulesTests(unittest.TestCase):
    def test_production_uses_known_tech_and_excludes_disabled_existing(self):
        s,r=inputs();result=eligible_production(s,0,r)
        self.assertEqual([(a['kind'],a['id']) for a in result],[('unit',0),('unit',2),('unit',3),('improvement',2),('improvement',3)])
        self.assertTrue(all(a['native_menu_verification_required'] for a in result))

    def test_sea_units_require_observed_coast_or_owned_native_flag(self):
        s,r=inputs();s['map']['tiles']=[dict(x=6,y=4,terrain_id=10)]
        self.assertIn(32,[a['id'] for a in eligible_production(s,0,r) if a['kind']=='unit'])
        s['cities'][0]['can_build_ships']=False
        self.assertNotIn(32,[a['id'] for a in eligible_production(s,0,r) if a['kind']=='unit'])
        s['cities'][0]['can_build_ships']=True;s['map']['tiles']=[]
        self.assertIn(32,[a['id'] for a in eligible_production(s,0,r) if a['kind']=='unit'])

    def test_obsolete_unit_removed_and_fanatics_government_checked(self):
        s,r=inputs();s['player']['known_technology_ids'] += [3,6]
        ids=[a['id'] for a in eligible_production(s,0,r) if a['kind']=='unit']
        self.assertNotIn(2,ids);self.assertNotIn(3,ids);self.assertNotIn(8,ids)
        s['player']['government_id']=4
        self.assertIn(8,[a['id'] for a in eligible_production(s,0,r) if a['kind']=='unit'])

    def test_wonders_require_public_availability_not_hidden_world(self):
        s,r=inputs();s['player']['known_technology_ids'].append(12)
        self.assertNotIn(39,[a['id'] for a in eligible_production(s,0,r)])
        s['wonders']=[dict(improvement_id=39,status='not_built',owned=False)]
        self.assertIn(39,[a['id'] for a in eligible_production(s,0,r)])
        s['wonders'][0]['status']='built'
        self.assertNotIn(39,[a['id'] for a in eligible_production(s,0,r)])

    def test_ship_parts_need_apollo_explicit_unlock_and_no_bloodlust(self):
        s,r=inputs();s['player']['known_technology_ids'].append(7)
        s['wonders']=[dict(improvement_id=64,status='built',owned=False)]
        self.assertNotIn(35,[a['id'] for a in eligible_production(s,0,r)])
        s['space_race_building_unlocked']=True
        self.assertIn(35,[a['id'] for a in eligible_production(s,0,r)])
        s['settings']['bloodlust']=True
        self.assertNotIn(35,[a['id'] for a in eligible_production(s,0,r)])

    def test_nuclear_unit_requires_public_manhattan(self):
        s,r=inputs();s['player']['known_technology_ids'].append(10)
        self.assertNotIn(45,[a['id'] for a in eligible_production(s,0,r)])
        s['wonders']=[dict(improvement_id=62,status='built',owned=False)]
        self.assertIn(45,[a['id'] for a in eligible_production(s,0,r)])

    def test_research_eligibility_not_native_menu_claim(self):
        s,r=inputs();r['advances'] += [dict(id=20,name='TEST Both',code='X',prerequisites=['Bro','Pot']),dict(id=21,name='TEST No',code='Y',prerequisites=['no','nil']),dict(id=22,name='TEST Missing',code='Z',prerequisites=['NOTKNOWN','nil'])]
        candidates=eligible_research(s,r)
        self.assertIn(20,[c['id'] for c in candidates]);self.assertNotIn(21,[c['id'] for c in candidates]);self.assertNotIn(22,[c['id'] for c in candidates])
        self.assertTrue(all(c['native_menu_verification_required'] for c in candidates))

    def test_government_and_statue_of_liberty(self):
        s,r=inputs();self.assertEqual([g['id'] for g in eligible_governments(s,r)],[1])
        s['player']['known_technology_ids'] += [4,5]
        self.assertEqual([g['id'] for g in eligible_governments(s,r)],[1,2,5])
        s['wonders']=[dict(improvement_id=58,status='built',owned=False)]
        self.assertEqual([g['id'] for g in eligible_governments(s,r)],[1,2,5])
        s['wonders'][0]['owned']=True
        self.assertEqual([g['id'] for g in eligible_governments(s,r)],list(range(1,7)))

    def test_unknown_city_cannot_be_action_actor(self):
        s,r=inputs()
        with self.assertRaises(ValueError):eligible_production(s,99,r)

    def test_terrain_capabilities_come_from_original_fields(self):
        r=parse_rules('''@TERRAIN
TEST Plains,1,2,1,1,0,yes,1,5,1,For,0,15,0,Grs ; Pln
''')['terrain'][0]
        self.assertEqual((r['irrigation_result'],r['irrigation_turns']),('yes',5))
        self.assertEqual((r['mining_result'],r['mining_turns']),('For',15))
        self.assertEqual(r['transform_result'],'Grs')

    def test_optional_private_original_rome_city_and_build_candidates(self):
        root=Path(__file__).resolve().parents[1]
        path=root/'.runtime/rome-city.sav';bundle=root/'engine/game/civ2-win31.zip'
        if not path.exists() or not bundle.exists():self.skipTest('private calibration assets not supplied')
        with zipfile.ZipFile(bundle) as z:text=z.read('civ2/RULES.TXT').decode('cp1252')
        state=parse_save(path.read_bytes(),rules_text=text);rules=parse_rules(text)
        city=state['cities'][0]
        self.assertEqual((city['name'],city['size'],city['food_produced'],city['shields_produced']),('Rome',1,4,2))
        self.assertEqual(city['production']['name'],'Phalanx')
        self.assertEqual(city['improvement_ids'],[1])
        self.assertEqual((city['science'],city['tax'],city['net_trade']),(1,0,1))
        self.assertEqual(state['units'][0]['id'],6)
        self.assertEqual(state['view']['last_clicked'],{'x':42,'y':40})
        self.assertEqual(state['view']['zoom'],0)
        choices=eligible_production(state,0,rules)
        self.assertEqual([a['name'] for a in choices],['Settlers','Warriors','Phalanx','Barracks','Granary','Hanging Gardens','Colossus'])
        self.assertEqual(len(rules['terrain']),11)


if __name__=='__main__':unittest.main()
