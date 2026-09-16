"""Owned-city labor observations, with no unverified native UI actions.

Classic byte order: Read.ClassicSav.cs worker-bit decoding zipped with
MapNavigationFunctions.CityRadius in https://github.com/axx0/Civ2-clone .
The hex-format notes corroborate inner8/outer8/outer4 plus center. The initial Rome [0x20,0,0x10] case confirms center and the western worker.
All 20 non-center slots were subsequently clicked individually and read back
through native saves in labor-calibration-01; the center remains immutable.
"""
from __future__ import annotations

from copy import deepcopy
import re

from .save import parse_rules
from .revision import RevisionError, revision, observation_key


class CityLaborError(ValueError):
    pass


# (byte within city+48..50, bit, dx, dy) in the reference reader's slot order.
# Coordinates use the original doubled-X map, so this works on either parity.
WORKED_BITS = (
    (0,7,0,-2), (0,6,-1,-1), (0,5,-2,0), (0,4,-1,1),
    (0,3,0,2), (0,2,1,1), (0,1,2,0), (0,0,1,-1),
    (1,7,1,3), (1,6,3,1), (1,5,3,-1), (1,4,1,-3),
    (1,3,-2,-2), (1,2,-2,2), (1,1,2,2), (1,0,2,-2),
    (2,4,0,0), (2,3,-1,-3), (2,2,-3,-1), (2,1,-3,1), (2,0,-1,3),
)
OUTPUT_FIELDS=('food_stored','shields_stored','food_produced','shields_produced','net_trade','trade_icons','tax','science')


def city_labor_projection(state,city_id,rules=None):
    """Project worker bits onto known tiles, not native screen coordinates.

    The whole city radius is supplied so missing and unworked squares remain
    explicit. A known tile's base RULES.TXT yields are unmodified specifications,
    never actual tile yields or a forecast. No map seed or foreign data is read.
    """
    if not isinstance(state,dict) or type(city_id) is not int or city_id<0:
        raise CityLaborError('An observed owned city ID is required')
    player=state.get('player',{}).get('id')
    if type(player) is not int or not 1<=player<=7:raise CityLaborError('Observed player required')
    matches=[c for c in state.get('cities',[]) if c.get('id')==city_id]
    if len(matches)!=1 or matches[0].get('owner')!=player:
        raise CityLaborError('City is not an unambiguous owned actor')
    city=matches[0]
    if any(type(city.get(k)) is not int or city[k]<0 for k in ('x','y','size')) or city['size']<1:
        raise CityLaborError('Invalid owned city coordinates/population')
    try:
        bound_revision=revision(state)
    except RevisionError as error:
        raise CityLaborError(str(error)) from None
    if bound_revision['turn']<1:raise CityLaborError('Positive observed turn is required')
    bits=city.get('worked_tiles_bits')
    if not isinstance(bits,(list,tuple)) or len(bits)!=3 or any(type(v) is not int or not 0<=v<=255 for v in bits):
        raise CityLaborError('Exactly three original worked-tile bytes are required')
    if bits[2]&0xe0:raise CityLaborError('Unsupported high bits in classic labor bitmap')
    if not bits[2]&0x10:raise CityLaborError('Original city-center worked bit is absent')
    world=state.get('map',{});width,height=world.get('coordinate_width'),world.get('height')
    if type(width) is not int or type(height) is not int or width<8 or width%2 or height<8:
        raise CityLaborError('Original map dimensions required')
    if not 0<=city['x']<width or not 0<=city['y']<height or (city['x']-city['y'])%2:
        raise CityLaborError('Owned city is outside the original coordinate grid')
    round_world=state.get('settings',{}).get('round_world') is True
    known={}
    for tile in world.get('tiles',[]):
        if not isinstance(tile,dict) or any(type(tile.get(k)) is not int for k in ('x','y')):
            raise CityLaborError('Malformed explored tile')
        point=tile['x'],tile['y']
        if point in known:raise CityLaborError('Duplicate explored tile')
        if not 0<=point[0]<width or not 0<=point[1]<height or (point[0]-point[1])%2:
            raise CityLaborError('Explored tile outside original coordinate grid')
        known[point]=tile
    if isinstance(rules,str):rules=parse_rules(rules)
    if rules is None:rules={}
    if not isinstance(rules,dict):raise CityLaborError('Original rules must be parsed data or text')
    terrain_rules={}
    for entry in rules.get('terrain',[]):
        if not isinstance(entry,dict) or type(entry.get('id')) is not int or entry['id'] in terrain_rules:
            raise CityLaborError('Ambiguous terrain rule')
        terrain_rules[entry['id']]=entry
    radius=[]
    for slot,(byte,bit,dx,dy) in enumerate(WORKED_BITS):
        x,y=city['x']+dx,city['y']+dy
        if round_world:x%=width
        in_map=0<=x<width and 0<=y<height
        tile=known.get((x,y)) if in_map else None
        cell=dict(slot=slot,source_byte=48+byte,source_bit=bit,relative=dict(dx=dx,dy=dy),
                  position=dict(x=x,y=y) if in_map else None,is_center=dx==dy==0,
                  worked=bool(bits[byte]&(1<<bit)),
                  knowledge='outside_map' if not in_map else 'explored' if tile is not None else 'unexplored',
                  terrain=None,river=None,remembered_improvements=None,original_base_yields=None,actual_yields=None)
        if tile is not None:
            terrain_id=tile.get('terrain_id')
            if type(terrain_id) is not int or not 0<=terrain_id<=10 or not isinstance(tile.get('terrain'),str):
                raise CityLaborError('Explored terrain identity is invalid')
            improvements=tile.get('known_improvements',[])
            if not isinstance(improvements,list) or any(not isinstance(v,str) for v in improvements):
                raise CityLaborError('Remembered improvements must be labels')
            cell.update(terrain=dict(id=terrain_id,name=tile['terrain']),river=tile.get('river'),
                        remembered_improvements=list(improvements))
            specification=terrain_rules.get(terrain_id)
            if specification is not None:
                if any(type(specification.get(k)) is not int or specification[k]<0 for k in ('food','shields','trade')):
                    raise CityLaborError('Invalid original base terrain yields')
                cell['original_base_yields']={k:specification[k] for k in ('food','shields','trade')}
        radius.append(cell)
    worked=sorted((c for c in radius if c['worked']),key=lambda c:(not c['is_center'],c['slot']))
    specialist_count=city.get('specialist_count')
    if type(specialist_count) is not int or specialist_count<0:
        raise CityLaborError('Observed specialist count required')
    typed=city.get('specialists',{})
    if (not isinstance(typed,dict) or any(k not in ('entertainer','taxman','scientist') for k in typed)
        or any(type(v) is not int or v<0 for v in typed.values())):
        raise CityLaborError('Invalid stored specialist types')
    typed_total=sum(typed.values());workers=sum(not c['is_center'] for c in worked)
    warnings=[]
    if workers+specialist_count!=city['size']:
        warnings.append('Worked non-center squares plus specialist count do not match saved population; do not repair or optimize this discrepancy automatically.')
    if typed_total!=specialist_count:
        warnings.append('Stored specialist type counts do not cover exactly the saved specialist count; individual type assignment is uncertain.')
    if any(c['knowledge']=='outside_map' for c in worked):
        warnings.append('Bitmap marks an out-of-map square as worked; no terrain or action is inferred for it.')
    if observation_key(state)=='observation_sha256':
        warnings=[text.replace('saved population','observed population').replace('saved specialist count','observed specialist count') for text in warnings]
    return dict(city={k:deepcopy(city.get(k)) for k in ('id','owner','name','x','y','size')},
        revision=bound_revision,worked_tiles_bits=list(bits),
        city_radius=radius,worked_positions=deepcopy(worked),
        labor_balance=dict(population=city['size'],non_center_workers=workers,specialists=specialist_count,
                           accounted_citizens=workers+specialist_count,consistent=workers+specialist_count==city['size']),
        specialists=dict(count=specialist_count,stored_type_counts=deepcopy(typed),
                         type_counts_complete=typed_total==specialist_count,
                         untyped_count=max(0,specialist_count-typed_total)),
        happiness={k:deepcopy(city.get(k)) for k in ('happy','unhappy','disorder','celebrating')},
        **{('city_totals_as_observed' if observation_key(state)=='observation_sha256' else 'city_totals_as_saved'):
            {k:deepcopy(city[k]) for k in OUTPUT_FIELDS if k in city}},warnings=warnings,
        yield_note='Original base yields are unmodified RULES.TXT terrain specifications, not actual tile yields. Specials, grassland shields, city-center rules, government, river/trade, improvements and other effects are not calculated. Do not sum these as city income or predict a reassignment gain.',
        knowledge_note='Only the supplied explored map and remembered improvements are joined. Missing or out-of-map squares remain unknown. No seed, hidden rival data, guessed worker destination or screen coordinates are used.',
        native_actions=[],native_action_status='This observation projection dispatches no actions. city_controls may offer calibrated worker/entertainer changes only from a fresh observed city screen; scientist/taxman type actions remain unavailable.',
        mapping_validation='All 20 non-center worker slots matched individual original-game native save readbacks in labor-calibration-01; center was not clicked.')


city_labor=city_labor_projection
