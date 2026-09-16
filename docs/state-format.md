# Original Civilization II state

`civ2.save.parse_save(data, rules_text=...)` reads a save created through the original game's normal Save command. It never writes a save or guest memory. The executable in the initial runtime reports **1.06, 27-Mar-96**. Supported saves have `CIVILIZE\0\x1a` followed by little-endian version `0x0027`. This version also covers early classic/CiC layouts; it is not a claim that an arbitrary file came from the pinned executable.

MGE (`0x002c`), Fantastic Worlds (`0x0028`) and Test of Time (`0x0031`/`0x0032`) are rejected. Freeciv saves and mechanics are unrelated. This distinction matters: MGE units are 32 bytes and cities 88 bytes; the original records here are **26 and 84 bytes**.

## Sources and confidence

The offset reference is [Civ2-clone's classic save reader](https://github.com/axx0/Civ2-clone/blob/master/Engine/src/OriginalSaves/Read.ClassicSav.cs), cross-checked against [Allard Höfelt/Jorrit Vermeiren's save-format notes](https://github.com/LukeGoodsell/civ2.pm/blob/master/doc/hexedit.rtf). The latter explains remembered improvements and warns that even undiscovered cities can have a city marker in the map block. These are reverse-engineering references, not a reimplementation of the game engine.

The bundled original `TUTORIAL.SAV` has SHA-256 `21b36d9a00aaf1941b124130ffd7225984d2d77a53e36d0a8e25c3c88557cc49`. Its layout decodes consistently as player 5, Americans, 50 gold, Despotism, Alphabet, one Settler at `(35,47)`, 21 explored tiles, no owned cities, and four unexposed rival city records. This validates structural offsets and this fixture's values. It is **not** validation of every late-game field or every foreign-unit visibility case.

| Data | Classic offset or layout | Confidence / restriction |
| --- | --- | --- |
| Turn | unsigned word at 28 | Reference and original fixture agree on turn 1. |
| Calendar field | signed word at 30 | Original tutorial and native Rome both show `-4000` / 4000 BC. Returned directly as `year` and `year_raw`, without deriving a date from the turn count. |
| Selected unit | word at 34; `65535` means none | Reference-backed; must refresh after native input. |
| Human / difficulty / barbarians | bytes 39 / 44 / 45 | Single-human masks validated. Prince = 2; Restless Tribes = 2. |
| Starting civilization count | population count of byte 46 masked with `0xfe` | Excludes barbarians. Returned only on turn 1; later survivor masks cannot recover the initial setup. |
| Standard HP/firepower combat | byte 12, bit `0x10` | **Set means standard HP/firepower; clear means simplified combat.** The general hex notes describe a toggle without its polarity; the classic reader explicitly inverts it into `Options.SimplifiedCombat`. |
| Civilization record | `2264 + player_id * 1396` | Only human funds, rates, government and research returned. |
| Owned technologies | 93 civilization-bit masks at `66 + 93` | Uses global ownership masks; avoids older ambiguous compact-tech packing. Other players' bits are discarded. |
| Map header | 7 little-endian words at 13432 | Doubled coordinate width, height, area, shape, resource seed, two minimap dimensions. Shape comes from option byte 13. |
| Remembered improvements | 7 arrays of `area` bytes after header | Read only the human array; never substitute current world improvements. |
| Terrain / exploration | 6-byte records after those arrays | Byte 0: terrain/river; byte 4: each player's explored bit. Unexplored records omitted. |
| Unit block | `13432 + 14 + 13*area + 2*locator_x*locator_y + 1024` | 26 bytes per slot, including reusable/dead slots. |
| City block | immediately after all unit slots | 84 bytes per slot. Production uses nonnegative unit IDs or negative improvement IDs. |
| Public wonder availability | 28 signed words at 252 | `-1` means unbuilt; nonnegative means built. Return status and whether owned, never a foreign city pointer or location. Equivalent to the accessible Wonders of the World report. |
| Cursor / last-click / zoom | after cities and 63 city-name-counter bytes | Cursor at `O`; last-click at `O+48+1314`, zoom two words later, for one human. These are not a proven viewport center. |

Coordinates are the original staggered grid: `0 <= x < coordinate_width`, `0 <= y < height`, and `x` and `y` have the same parity. Array column is `x // 2`. Immediate neighbors are `(±2,0)`, `(0,±2)`, `(±1,±1)`; horizontal wrapping applies on a round world. The map's `width` is the number of array columns, not the maximum original X coordinate.

The first native Rome setup save provided a useful setup check: it contained difficulty byte `0` (Chieftain), seven starting civilizations, and a `50 × 80` array map, despite an intended Prince/five/small selection. Restless Tribes, male Caesar and standard HP/firepower combat were correct. This is evidence that menu selection must be verified, not evidence of a date/layout failure: its turn-1 signed calendar field is again `-4000`. A small map is conventionally `40 × 50` (2000 tiles); `50 × 80` is normal, also documented in the [classic world-size handler](https://github.com/axx0/Civ2-clone/blob/master/Civ2/Dialogs/NewGame/WorldSizeHandler.cs).

Before counting a run, inspect the highlighted native selection at every setup prompt, then save and require Prince, Restless Tribes, five starting civilizations, male Romans, and the expected dimensions. For standard rules also check `bloodlust=false`, `simplified_combat=false`, round world and restart-eliminated enabled. Do not use the tutorial's difficulty as the requested game's setting. Preserve this initial count in the run manifest because later saves do not retain it reliably. Later-turn calendar progression remains a native-UI calibration item.

A native city calibration subsequently matched Rome's displayed size 1, treasury 50, total food 4 (2 consumed and 2 surplus), trade 1, science 1, taxes 0, production 2 and Palace. The saved production ID is 3: **Phalanx**, while Warriors is ID 2. This comparison did not have unit support costs, so it does not by itself establish gross-versus-net production semantics in a later supported army.

The view fields in both calibration saves were cursor `(42,40)`, last click `(42,40)`, and standard zoom `0`. `view.viewport_center` remains `null`: neither saved field is documented as the camera center. Original `MENU.TXT` identifies `C` for Center View and **`V`** to toggle Move/View Pieces; a manual OCR rendering of that second key as `0` is incorrect. The manual describes `A` to activate units under the cursor, with a chooser for a stack. Re-centering still needs a verified projection before a map click. Space skips a unit for the current turn and cannot be treated as harmless acknowledgement.

## City labor projection

`civ2.city.city_labor_projection(state, city_id, rules=None)` decodes an owned city's three worker bytes and joins its 21-square radius only to the parser's explored map. It returns the center and assigned workers, unassigned radius squares, specialist counts, happiness and stored city totals, bound to the save revision and city signature. Unknown or out-of-map squares remain unknown. It supplies no labor-click actions: Resource Map and specialist pixel coordinates have not been verified.

The bit order comes from the [classic reader's worker decode](https://github.com/axx0/Civ2-clone/blob/master/Engine/src/OriginalSaves/Read.ClassicSav.cs), paired with [`MapNavigationFunctions.CityRadius`](https://github.com/axx0/Civ2-clone/blob/master/Engine/src/MapObjects/MapNavigationFunctions.cs). The hex-edit notes corroborate the three-byte field; the ordered radius is needed to establish orientation. Offsets below are relative to the city record, and coordinates are original staggered-grid deltas.

| Worker byte | Bits, high to low | Corresponding `(dx, dy)` |
| --- | --- | --- |
| 48 | 7, 6, 5, 4, 3, 2, 1, 0 | `(0,-2)`, `(-1,-1)`, `(-2,0)`, `(-1,1)`, `(0,2)`, `(1,1)`, `(2,0)`, `(1,-1)` |
| 49 | 7, 6, 5, 4, 3, 2, 1, 0 | `(1,3)`, `(3,1)`, `(3,-1)`, `(1,-3)`, `(-2,-2)`, `(-2,2)`, `(2,2)`, `(2,-2)` |
| 50 | 4, 3, 2, 1, 0 | center `(0,0)`, `(-1,-3)`, `(-3,-1)`, `(-3,1)`, `(-1,3)` |

The native Rome calibration has bytes `[32, 0, 16]`, giving its center `(42,40)` and one worker west at `(40,40)`. The original city display is consistent with that west grassland assignment. This is one directional live comparison, **not** validation of all 21 positions by toggling workers. Tests cover the reference mapping, wrapping, boundaries and observation filtering with synthetic data.

Each known square may include its terrain, river flag, remembered improvements and `original_base_yields` from `RULES.TXT`. These are explicitly **not actual tile yields**: special resources, grassland shield patterns, government, city-center rules and improvements are not calculated. `actual_yields` remains `null`; the projection does not sum base values into a claimed city output. Specialist type totals are retained separately from the stored specialist count, with a warning when they disagree. Population/worker accounting mismatches are reported rather than silently repaired.

## Observation boundary

A save contains the whole world. The exported dictionary contains owned cities and units, the human treasury/government/research, contacted diplomatic relations, explored terrain, and remembered improvements. It does not contain undiscovered terrain, a map seed, AI plans or fertility, rival funds or technologies, foreign city production, current world improvement bytes, or a list of undiscovered civilizations and cities.

Foreign cities require both the city's known-to-human flag and an explored tile. They expose remembered size and location, not current ownership, current size, buildings or production. Names come from the city record; native historical-name behavior still needs calibration. Foreign units require their stored visibility bit, an explored tile, and immediate adjacency to an owned unit or city. This intentionally under-reports extended sight until it is tested against the original display. A remembered terrain/unit marker alone is never current vision. Previously observed enemies should be stored as dated observations, with uncertainty, by the policy layer.

Unit IDs are save slots and can **compact**, not merely be recycled. In the native founding test, removing Settler 0 changed the other owned Settler from slot 7 to slot 6. There is no verified generation counter. Bind an input to the observation revision (`evidence.save_sha256`), the slot and an actor signature including owner, type and position; refresh after any operation that can alter the list. A signature is a validation aid, not a permanent identity: two same-type units can occupy the same square. Never assume slot continuity across saves or transfer a hidden enemy's current record into historical memory.

`RULES.TXT` supplies original names, technology prerequisites and unit attack/defense/movement/HP/firepower/cost. These are unit specifications, not calculated battle odds. Legal research and production choices still come from the native UI: prerequisites alone do not prove a particular choice is currently offered.

`civ2.rules` provides `eligible_production(state, city_id, rules)`, `eligible_research(state, rules)` and `eligible_governments(state, rules)`. Every result carries `native_menu_verification_required=true`. Unit prerequisites and obsolescence, owned existing improvements, coastal restrictions and Fundamentalism's Fanatics restriction reduce the candidate set. Wonders require the public availability report; no hidden rival technology is read to infer expiration. Spaceship parts require an explicit observed unlock as well as public Apollo completion, because part caps and launch state are not yet decoded. Governments describe concepts available after the native revolution flow, not permission to change government instantly.

The rules output includes 54 units, 93 advances, 67 improvement entries and 11 basic terrain entries for the original file. Improvements 35–37 are spaceship parts, 38 is Capitalization and 39–66 are wonders. Terrain work results distinguish `yes` (add an improvement), `no` (unavailable), and a terrain code (transform to that terrain). For example, mining Plains changes it to Forest; it is not always a shield mine. Base terrain yield fields are specifications, not fully calculated tile yields: resources, grassland shields, government and improvements still matter. Current Rome's prerequisite-filtered candidates are Settlers, Warriors, Phalanx, Barracks, Granary, Hanging Gardens and Colossus; this list still requires the native Change Production check.

The parser rejects unknown versions, broken dimensions/record bounds, impossible active coordinates, invalid player/rates, multiplayer masks, and reveal/cheat-marked saves. It does not infer victory from scores, surviving-civilization masks or a spaceship field. Completion requires the original game's result UI, captured and visually verified.

## Full-game policy coverage

The [original manual](https://archive.org/details/civ2_manual), [1996 technical supplement](https://archive.org/details/sid-meiers-civilization-ii-technical-supplement), and [original unit/terrain chart](https://archive.org/details/sid-meiers-civilization-ii-advanced-chart-with-terrain-unit-specifications) are the rules references. [CivFanatics' combat guide](https://www.civfanatics.com/civ2/strategy/combatguide/) is useful secondary analysis. Strategy guides with Deity, raging barbarians, MGE multiplayer, or ToT scenarios describe different setups; do not silently adopt those settings.

Our requested setup is a small world, Prince, **five civilizations total including Rome**, Restless Tribes, standard rules, male leader. Barbarians are additional. The original `@LEADERS` table names Rome's male leader Caesar. Standard victory can come from conquest or the first successful Alpha Centauri colony; the 2020 retirement score is a distinct terminal result.

A useful decision graph separates compulsory UI responses from ordinary strategy:

| Context / intent | Required observation | Actions that must be expressible |
| --- | --- | --- |
| Native modal | Exact title, choices, affected actor/city and quoted costs | Science choice, production completion, diplomatic response, event acknowledgement, government choice, caravan/diplomat mission, outcome acknowledgement. |
| Expansion / exploration | Owned settlers, known food/production terrain, explored frontier, escorts and dated discoveries | Select unit; move one legal neighbor; wait, fortify/sentry, found/join city; roads, irrigation, mines and later terrain work; embark/disembark. |
| City economy | Size, food/shield storage and output, happiness, support, worked tiles, specialists, buildings | Production selection, affordable rush purchase, tile/specialist reassignment, improvement sale when legal. Civ II has one current production item; do not invent a later-game queue. |
| Science / government | Known technology, current native offers, treasury, rates, support and disorder | Research choice, tax/science/luxury rates, revolution and available government. |
| Diplomacy / trade | Contacted rivals, displayed treaty/attitude/offers, visible targets, caravan commodity | Meet/respond; peace/ceasefire/alliance, exchange or tribute; legal diplomat/spy and caravan actions. |
| Defense / war | Visible enemies, own strength/HP/movement, terrain/city defenses, endangered civilians, treaties | Attack by legal movement, reposition, reinforce, heal, fortify, escort, transport; deliberate treaty-breaking response. |
| Endgame | Original conquest or spaceship UI, available ship parts and launch status | Continue conquest or build/launch ship, then verify actual terminal outcome. |
| Turn completion | Active unit, pending orders, mandatory dialogs, city emergencies | Skip/wait a unit or explicitly end turn only after mandatory decisions are resolved. |

Keep each action's actor, target and native input semantics explicit. An intent graph can choose among city economy, exploration/settlement, science/government, diplomacy/trade and war; its conditional child selects a concrete offered action. A multi-question/vector request should represent independent priorities or conditional alternatives, not silently execute several stale orders after one observation. Re-observe after any move, founding, city change or diplomatic event that changes the legal menu. Probability bars are the model's reported decision probabilities, not combat or match-win probabilities.

Practical guidance is to establish defended food-surplus cities and roads, maintain income/support, resolve disorder or starvation before optional projects, and develop production and science together. Despotism subtracts one from a tile yield above two; Monarchy can remove that early economic constraint, while Republic improves trade at the cost of support, unhappiness and Senate constraints. Exact transition timing should follow observed conditions, not a fixed route. Civ II can destroy an entire stack outside a city or fortress when its defender loses; escort civilian and siege units and avoid presenting a vulnerable stack. Caravans, diplomats and sea transport are important capabilities rather than optional cosmetic menus.

The interface can automatically advance to another unit, interrupt with diplomacy, complete construction/research before movement, or ask a confirmation. A key valid on the map can mean something different inside a city or dialog. Verify the current context and actor before every command; “Enter” is not a universal safe dismissal. Saving itself is a native modal flow and must finish before reading the file. No hidden map or future-order information should be introduced to compensate for a difficult UI state.

Run `python3 -m unittest tests.test_save tests.test_rules tests.test_city -v`. Synthetic tests carry TEST labels. Original tutorial and city checks run only when the user's ignored calibration assets are present; no original fixture is distributed with the tests.
