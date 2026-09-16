"""Read-only, observation-filtered parser for original Civ II 0x27 saves.

Offsets are classic (1.x/CiC), not MGE. See docs/state-format.md. A save is
omniscient; the return value deliberately is not. No writer is provided.
"""
from __future__ import annotations

import hashlib
import re
import struct
from collections import Counter

VERSION = 0x27
MAP_OFFSET = 13432
CIV_OFFSET = 2264
CIV_SIZE = 1396
UNIT_SIZE = 26
CITY_SIZE = 84
GOVERNMENTS = ("Anarchy", "Despotism", "Monarchy", "Communism", "Fundamentalism", "Republic", "Democracy")
TERRAINS = ("Desert", "Plains", "Grassland", "Forest", "Hills", "Mountains", "Tundra", "Glacier", "Swamp", "Jungle", "Ocean")
DIFFICULTIES = ("Chieftain", "Warlord", "Prince", "King", "Emperor", "Deity")
BARBARIANS = ("Villages Only", "Roving Bands", "Restless Tribes", "Raging Hordes")


class SaveFormatError(ValueError):
    """Unsupported or inconsistent input; never silently guess a layout."""


def parse_rules(text: str) -> dict:
    """Read names and basic specifications from the user's original RULES.TXT."""
    sections: dict[str, list] = {}
    section = None
    for raw in text.splitlines():
        body, _, comment = raw.partition(";")
        body = body.strip()
        if body.startswith("@"):
            section = body.upper()
            sections.setdefault(section, [])
        elif section and body:
            sections[section].append(([s.strip() for s in body.split(",")], comment.strip()))
    def number(s: str) -> int:
        match = re.match(r"-?\d+", s)
        if not match:
            raise SaveFormatError("Invalid numeric RULES.TXT field")
        return int(match.group())
    units = []
    for index, (r, _) in enumerate(sections.get("@UNITS", [])[:54]):
        if len(r) < 14:
            raise SaveFormatError("Incomplete original unit rule")
        units.append(dict(id=index, name=r[0], obsolete_by=r[1], domain=number(r[2]),
                          movement=number(r[3]), attack=number(r[5]), defense=number(r[6]),
                          max_hp=10*number(r[7]), firepower=number(r[8]),
                          shield_cost=10*number(r[9]), transport_capacity=number(r[10]),
                          role=number(r[11]), prerequisite=r[12]))
    techs = []
    for index, (r, comment) in enumerate(sections.get("@CIVILIZE", [])[:93]):
        if len(r) < 5:
            raise SaveFormatError("Incomplete original advance rule")
        techs.append(dict(id=index, name=r[0], code=comment.split()[0] if comment else None,
                          prerequisites=r[3:5]))
    leaders = []
    for index, (r, _) in enumerate(sections.get("@LEADERS", [])[:21]):
        if len(r) < 7:
            raise SaveFormatError("Incomplete original leader rule")
        leaders.append(dict(id=index, male=r[0], female=r[1], tribe=r[5], adjective=r[6]))
    improvements = []
    for index, (r, _) in enumerate(sections.get("@IMPROVE", [])):
        if len(r) >= 4:
            improvements.append(dict(id=index, name=r[0], shield_cost=10*number(r[1]),
                                     upkeep=number(r[2]), prerequisite=r[3]))
    expiration = sections.get("@ENDWONDER", [])
    for item in improvements:
        item["kind"] = ("building" if item["id"] < 35 else "spaceship_part" if item["id"] < 38
                        else "capitalization" if item["id"] == 38 else "wonder")
        if item["id"] >= 39 and item["id"]-39 < len(expiration):
            item["obsolete_by"] = expiration[item["id"]-39][0][0]
    terrain=[]
    for index,(r,comment) in enumerate(sections.get('@TERRAIN',[])[:11]):
        if len(r)<15:raise SaveFormatError('Incomplete original terrain rule')
        terrain.append(dict(id=index,name=r[0],code=comment.split()[0] if comment else None,
                            movement_cost=number(r[1]),defense_halves=number(r[2]),
                            food=number(r[3]),shields=number(r[4]),trade=number(r[5]),
                            irrigation_result=r[6],irrigation_bonus=number(r[7]),irrigation_turns=number(r[8]),
                            mining_result=r[10],mining_bonus=number(r[11]),mining_turns=number(r[12]),
                            transform_result=r[14]))
    return dict(units=units, advances=techs, leaders=leaders, improvements=improvements,terrain=terrain)


def _improvements(value: int) -> list[str]:
    # Stored per-player knowledge, never substitute the world's current byte.
    result = []
    if value & 4:
        result.append("farmland" if value & 8 else "irrigation")
    elif value & 8:
        result.append("mine")
    if value & 16:
        result.append("railroad" if value & 32 else "road")
    if value & 64:
        result.append("airbase" if value & 2 else "fortress")
    if value & 128:
        result.append("pollution")
    return result


def parse_save(data: bytes, *, rules_text: str | None = None) -> dict:
    """Return only the human player's owned/known observation.

    Foreign unit visibility is additionally limited to immediate own-unit/city
    adjacency. This conservatively under-reports extended sight, rather than
    treating an explored tile or a remembered unit marker as current vision.
    """
    if not isinstance(data, bytes):
        raise TypeError("save data must be bytes")
    if len(data) < MAP_OFFSET + 14 or data[:10] != b"CIVILIZE\0\x1a":
        raise SaveFormatError("Not a complete original Civilization II save")
    def u16(offset): return struct.unpack_from("<H", data, offset)[0]
    def i16(offset): return struct.unpack_from("<h", data, offset)[0]
    def string(offset, length): return data[offset:offset+length].split(b"\0", 1)[0].decode("cp1252", errors="replace")
    if u16(10) != VERSION:
        raise SaveFormatError("Only classic save version 0x0027 is supported; MGE/ToT need different layouts")
    player_id = data[39]
    if not 1 <= player_id <= 7 or data[47] != 1 << player_id:
        raise SaveFormatError("Expected exactly one human civilization")
    if data[44] > 5 or data[45] > 3:
        raise SaveFormatError("Invalid difficulty or barbarian setting")
    if data[43] or data[15] & 128 or data[20] & 16:
        raise SaveFormatError("Revealed-map or cheat-marked saves are not accepted")
    width2, height, area, _shape, _seed, locator_x, locator_y = struct.unpack_from("<7H", data, MAP_OFFSET)
    if not (8 <= width2 <= 512 and width2 % 2 == 0 and 8 <= height <= 512 and area == width2*height//2 and area <= 32767):
        raise SaveFormatError("Invalid classic map dimensions/area")
    if locator_x != (width2+3)//4 or locator_y != (height+3)//4:
        raise SaveFormatError("Invalid classic minimap dimensions")
    unit_count, city_count = u16(58), u16(60)
    if unit_count > 2048 or city_count > 256:
        raise SaveFormatError("Record counts exceed original-game limits")
    known_base = MAP_OFFSET + 14 + (player_id-1)*area
    terrain_base = MAP_OFFSET + 14 + 7*area
    unit_base = MAP_OFFSET + 14 + 13*area + 2*locator_x*locator_y + 1024
    city_base = unit_base + unit_count*UNIT_SIZE
    if city_base + city_count*CITY_SIZE > len(data):
        raise SaveFormatError("Truncated map/unit/city records")
    rules = parse_rules(rules_text) if rules_text is not None else {}
    bit = 1 << player_id
    width = width2//2
    def valid_xy(x, y): return 0 <= x < width2 and 0 <= y < height and (x-y)%2 == 0
    def tile_index(x, y): return y*width + x//2
    def explored(x, y): return valid_xy(x, y) and bool(data[terrain_base+6*tile_index(x,y)+4] & bit)
    def rule_name(table, index):
        rows = rules.get(table, [])
        return rows[index]["name"] if 0 <= index < len(rows) else None
    own_units, foreign_units = [], []
    for unit_id in range(unit_count):
        o = unit_base + unit_id*UNIT_SIZE
        x, y = i16(o), i16(o+2)
        if x < 0:  # Original dead/reusable record slot, not an active actor.
            continue
        owner, type_id = data[o+7], data[o+6]
        if owner > 7 or type_id >= 54 or not valid_xy(x, y):
            raise SaveFormatError("Invalid active classic unit record")
        if owner != player_id and not (data[o+9] & bit and explored(x,y)):
            continue
        unit = dict(id=unit_id, owner=owner, type_id=type_id, type=rule_name("units",type_id), x=x, y=y,
                    veteran=bool(data[o+5]&32), hp_lost=data[o+10])
        if rules.get("units") and type_id < len(rules["units"]):
            unit["specification"] = dict(rules["units"][type_id])
            unit["hp"] = max(0, unit["specification"]["max_hp"]-unit["hp_lost"])
        if owner == player_id:
            unit.update(movement_thirds_spent=data[o+8], order_id=data[o+15],
                        home_city_id=None if data[o+16] == 255 else data[o+16],
                        counter_or_commodity=data[o+13], waiting=bool(data[o+5]&64),
                        goto=None if i16(o+18)<0 or i16(o+20)<0 else dict(x=u16(o+18),y=u16(o+20)))
            own_units.append(unit)
        else:
            foreign_units.append(unit)
    own_cities, known_cities = [], []
    for city_id in range(city_count):
        o = city_base + city_id*CITY_SIZE
        x, y = i16(o), i16(o+2)
        if x < 0:
            continue
        owner, size = data[o+8], data[o+9]
        if owner > 7 or not valid_xy(x,y) or not 1 <= size <= 127:
            raise SaveFormatError("Invalid active classic city record")
        if owner != player_id:
            if data[o+12]&bit and explored(x,y):
                # Current owner, size, production, buildings and resources may
                # have changed outside sight. Only remembered size is returned.
                known_cities.append(dict(id=city_id, name=string(o+32,16), x=x, y=y,
                                         last_known_size=data[o+13+player_id], current_information=False))
            continue
        specialist_codes = [(data[o+22+j//4] >> (2*(j%4))) & 3 for j in range(16)]
        specialists = Counter(("none","entertainer","taxman","scientist")[v] for v in specialist_codes if v)
        production_id = struct.unpack_from("<b",data,o+57)[0]
        production = dict(kind="unit" if production_id>=0 else "improvement", id=production_id if production_id>=0 else -production_id)
        production["name"] = rule_name("units" if production_id>=0 else "improvements", production["id"])
        own_cities.append(dict(id=city_id,name=string(o+32,16),owner=owner,x=x,y=y,size=size,
                               disorder=bool(data[o+4]&1),celebrating=bool(data[o+4]&2),
                               can_build_coastal=bool(data[o+4]&128),can_build_hydro=bool(data[o+5]&8),
                               can_build_ships=bool(data[o+6]&32),
                               food_stored=u16(o+26),shields_stored=u16(o+28),net_trade=u16(o+30),
                               specialists=dict(specialists),specialist_count=data[o+51]//4,
                               worked_tiles_bits=list(data[o+48:o+51]),
                               improvement_ids=[i for i in range(1,35) if data[o+52+i//8]&(1<<(i%8))],
                               production=production,trade_route_count=data[o+58],
                               science=u16(o+74),tax=u16(o+76),trade_icons=u16(o+78),
                               food_produced=data[o+80],shields_produced=data[o+81],
                               happy=data[o+82],unhappy=data[o+83]))
    sources = [(u["x"],u["y"]) for u in own_units] + [(c["x"],c["y"]) for c in own_cities]
    round_world = not bool(data[13]&128)
    def immediate_sight(x,y):
        for sx,sy in sources:
            dx=abs(x-sx)
            if round_world: dx=min(dx,width2-dx)
            dy=abs(y-sy)
            if dx+dy <= 2:
                return True
        return False
    visible_units = [u for u in foreign_units if immediate_sight(u["x"],u["y"])]
    tiles=[]
    for index in range(area):
        o=terrain_base+6*index
        if not data[o+4]&bit:
            continue
        terrain_id=data[o]&15
        if terrain_id >= len(TERRAINS):
            raise SaveFormatError("Unknown terrain ID on explored tile")
        y,x=divmod(index,width)
        tiles.append(dict(x=2*x+y%2,y=y,terrain_id=terrain_id,terrain=TERRAINS[terrain_id],
                          river=bool(data[o]&128),known_improvements=_improvements(data[known_base+index])))
    p=CIV_OFFSET+CIV_SIZE*player_id
    government=data[p+21]
    science,tax=data[p+19]*10,data[p+20]*10
    if government>=len(GOVERNMENTS) or science>100 or tax>100 or science+tax>100:
        raise SaveFormatError("Invalid human government/rates")
    tech_ids=[i for i in range(93) if data[66+93+i]&bit]
    tribe_id=data[p+6]
    if tribe_id>=21 or data[p+1] not in (0,2):
        raise SaveFormatError("Invalid human tribe/gender")
    n=570+242*(player_id-1)
    custom_leader,custom_tribe=string(n+2,24),string(n+26,24)
    default_leader=rules.get("leaders",[])[tribe_id] if len(rules.get("leaders",[]))>tribe_id else {}
    player=dict(id=player_id,tribe_id=tribe_id,gender="male" if data[p+1]==0 else "female",
                leader=custom_leader or default_leader.get("male" if data[p+1]==0 else "female"),
                tribe=custom_tribe or default_leader.get("tribe"),treasury=struct.unpack_from("<I",data,p+2)[0],
                government_id=government,government=GOVERNMENTS[government],science_rate=science,
                tax_rate=tax,luxury_rate=100-science-tax,research_progress=u16(p+8),
                researching_id=None if data[p+10]==255 else data[p+10],
                known_technology_ids=tech_ids,known_technologies=[dict(id=i,name=rule_name("advances",i)) for i in tech_ids])
    diplomacy=[]
    for other in range(1,8):
        if other==player_id: continue
        o=p+32+4*other
        if not data[o]&1: continue
        diplomacy.append(dict(civ_id=other,contact=True,cease_fire=bool(data[o]&2),peace=bool(data[o]&4),
                              alliance=bool(data[o]&8),embassy=bool(data[o]&128),war=bool(data[o+1]&32)))
    # The original Wonders of the World report exposes whether each wonder
    # exists. Export that public aggregate, never its foreign city pointer.
    own_city_ids={city['id'] for city in own_cities}
    wonders=[]
    for wonder_id in range(28):
        city_id=i16(252+2*wonder_id)
        wonders.append(dict(id=wonder_id,improvement_id=39+wonder_id,
                            name=rule_name('improvements',39+wonder_id),
                            status='not_built' if city_id==-1 else 'built' if city_id>=0 else 'destroyed',
                            owned=city_id>=0 and city_id in own_city_ids))
    # These are documented cursor/last-click fields, NOT a proven camera center.
    # A native Center View command still needs a screen/projection calibration.
    other_base=city_base+city_count*CITY_SIZE+63
    view=dict(cursor=None,last_clicked=None,zoom=None,viewport_center=None)
    def view_point(offset):
        x,y=i16(offset),i16(offset+2)
        return dict(x=x,y=y) if valid_xy(x,y) else None
    if other_base+4<=len(data):view['cursor']=view_point(other_base)
    click_base=other_base+48+1314  # Exactly one human, validated above.
    if click_base+6<=len(data):
        view['last_clicked']=view_point(click_base)
        zoom=i16(click_base+4)
        if -7<=zoom<=8:view['zoom']=zoom
    # The alive mask is a starting-player count only on the initial turn.
    # Later it changes with eliminations/restarts and cannot recover setup.
    starting_civilizations=(data[46] & 0xfe).bit_count() if u16(28)==1 else None
    return dict(version=VERSION,turn=u16(28),year=i16(30),year_raw=i16(30),view=view,
                selected_unit_id=None if u16(34)==65535 else u16(34),
                settings=dict(difficulty=DIFFICULTIES[data[44]],barbarians=BARBARIANS[data[45]],
                              # Bit 4 ENABLES HP/firepower. The original clone's
                              # reader inverts it into Options.SimplifiedCombat.
                              bloodlust=bool(data[12]&128),simplified_combat=not bool(data[12]&16),
                              restart_eliminated=not bool(data[13]&1),round_world=round_world,
                              human_civilizations=1,starting_civilizations=starting_civilizations,
                              scenario=bool(data[20]&64)),
                player=player,units=own_units,visible_units=visible_units,cities=own_cities,known_cities=known_cities,
                diplomacy=diplomacy,wonders=wonders,map=dict(width=width,height=height,coordinate_width=width2,
                    explored_count=len(tiles),tiles=tiles,knowledge="explored terrain and remembered improvements; not current fog"),
                evidence=dict(save_sha256=hashlib.sha256(data).hexdigest(),save_bytes=len(data),
                              classic_layout=True,year_semantics="signed raw field; validate against displayed year",
                              foreign_units="visibility mask AND immediate own-unit/city adjacency only",
                              outcome="not inferred from save; require original result UI"))
