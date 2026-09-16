"""Conservative original-rules eligibility; the native menu remains authoritative.

These functions neither choose strategy nor perform input. They only use the
player observation and the original RULES.TXT definitions. In particular they
cannot use a hidden rival's technology, cities, routes, or plans.
"""
from __future__ import annotations

from .save import GOVERNMENTS, parse_rules

# Original @IMPROVE numbering. These restrictions are additional to technology.
COASTAL_IMPROVEMENTS = {28, 30, 31, 34}  # Coastal Fortress, Harbor, Offshore, Port.
GOVERNMENT_TECH = {2: 'Mon', 3: 'Cmn', 4: 'Fun', 5: 'Rep', 6: 'Dem'}


def known_advance_codes(state: dict, rules: dict) -> set[str]:
    known=set(state['player'].get('known_technology_ids',[]))
    return {str(t['code']).casefold() for t in rules.get('advances',[])
            if t['id'] in known and t.get('code')}


def _met(code: str, known: set[str]) -> bool:
    normalized=code.casefold()
    return normalized=='nil' or (normalized!='no' and normalized in known)


def eligible_research(state: dict, rules: dict) -> list[dict]:
    """Technology prerequisites satisfied; not the exact currently offered menu.

    Classic Civ II may withhold a prerequisite-satisfied technology in a given
    research dialog. Only choose an item also confirmed in the native dialog.
    """
    known=known_advance_codes(state,rules)
    ids=set(state['player'].get('known_technology_ids',[]))
    return [dict(t,native_menu_verification_required=True) for t in rules.get('advances',[])
            if t['id'] not in ids and all(_met(c,known) for c in t['prerequisites'])]


def eligible_governments(state: dict, rules: dict) -> list[dict]:
    """Government concepts available after a native revolution, not instant orders."""
    known=known_advance_codes(state,rules)
    liberty=any(w.get('improvement_id')==58 and w.get('owned') and w.get('status')=='built'
                for w in state.get('wonders',[]))
    return [dict(id=gid,name=GOVERNMENTS[gid],native_menu_verification_required=True,
                 revolution_may_be_required=True)
            for gid in range(1,7)
            if gid==1 or liberty or _met(GOVERNMENT_TECH[gid],known)]


def _known_coast(state: dict, city: dict) -> bool:
    # Native owned-city capability flags take precedence. If absent, only an
    # actually explored adjacent Ocean tile can establish the coastal condition.
    if 'can_build_ships' in city:
        return city['can_build_ships'] is True
    coordinate_width=state['map']['coordinate_width']
    for tile in state['map']['tiles']:
        if tile.get('terrain_id')!=10:continue
        dx=abs(tile['x']-city['x'])
        if state['settings'].get('round_world'):dx=min(dx,coordinate_width-dx)
        dy=abs(tile['y']-city['y'])
        if dx+dy<=2:return True
    return False


def eligible_production(state: dict, city_id: int, rules: dict) -> list[dict]:
    """Return candidates passing known prerequisites, pending native verification.

    Wonders need the public availability report. Spaceship parts require public
    Apollo completion and an explicit observed space-race unlock, because build
    caps and launch state are not decoded yet. Do not call this an exact legal
    menu; native Change Production handles additional rules and confirmations.
    """
    city=next((c for c in state['cities'] if c['id']==city_id),None)
    if city is None:raise ValueError('production actor is not an observed owned city')
    known=known_advance_codes(state,rules)
    coast=_known_coast(state,city)
    candidates=[]
    for unit in rules.get('units',[]):
        if not _met(unit['prerequisite'],known):continue
        expiry=unit['obsolete_by'].casefold()
        if expiry=='no' or expiry in known:continue
        if unit['domain']==2 and not coast:continue
        # Fanatics are restricted to Fundamentalism in original Civ II.
        if unit['id']==8 and state['player']['government_id']!=4:continue
        item=dict(unit,kind='unit',native_menu_verification_required=True)
        if unit.get('role')==5 and city['size']==1:
            item['warning']='Settler completion at size 1 needs the original population/abandonment prompt.'
        if unit['id']==45:
            if not any(w.get('improvement_id')==62 and w.get('status')=='built' for w in state.get('wonders',[])):
                continue
        candidates.append(item)
    present=set(city.get('improvement_ids',[]))
    wonder_status={w['improvement_id']:w for w in state.get('wonders',[])}
    for building in rules.get('improvements',[]):
        bid=building['id']
        if bid==0 or not _met(building['prerequisite'],known):continue
        if bid<=34 and bid in present:continue
        if bid in COASTAL_IMPROVEMENTS and not coast:continue
        if bid==20 and city.get('can_build_hydro') is not True:continue
        if 35<=bid<=37:
            if state['settings'].get('bloodlust') or state.get('space_race_building_unlocked') is not True:continue
            if not any(w.get('improvement_id')==64 and w.get('status')=='built' for w in state.get('wonders',[])):continue
        if bid>=39:
            if wonder_status.get(bid,{}).get('status')!='not_built':continue
            # Do not use hidden rival technology to decide expiration.
            if building.get('obsolete_by','nil').casefold() in known:continue
        candidates.append(dict(building,kind='improvement',production_class=building.get('kind','building'),
                               native_menu_verification_required=True))
    return candidates
