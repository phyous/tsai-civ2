# Caravan workflow coverage

Every offered strategic choice remains a separate Jev decision. Recognizing an
arrival does not deliver cargo, add shields, infer revenue, or establish a route.

`caravan.py` covers three original GAME resources:

| Stage | Required native choices |
| --- | --- |
| `CARAVANBUILT` | Every offered commodity, including Food, plus the actual Supply And Demand button |
| `CARACONFIRM` | Confirmed, Reconsider, and the actual Confirm and Zoom button |
| `CARAVANMENU` | Keep moving and every actually offered trade-route or wonder option |

The commodity catalog must match the original sixteen RULES `@CARAVAN` entries;
Food and the arrival labels are independently bound to original LABELS entries.
The completion prompt must name an original land trade unit (role7). The prompt,
all foreground text, each visible option and every required button must agree
with the source. No commodity or available destination is filled in from state.

A PNG hash check precedes native-frame and radio checks. The complete black
frame, its original light/dark bevel, and the full option band are inspected.
Every detected original radio must match one observed option in the same column
and at the original row spacing. An OCR-missed option whose radio remains visible
therefore rejects the dialog. Any extra foreground row, missing control, damaged
frame, unknown commodity or changed source also rejects it. The model selects a
radio followed by normal Enter, or an actual button click without extra Enter.

These caravan layouts currently have original-source and synthetic frame tests.
The shared frame/radio primitives also pass a retained original Foreign Minister
capture; that is **not live caravan calibration**. No caravan encounter was
available in the retained debug campaigns, and no campaign inputs were issued
for this implementation. A differing real layout remains unsupported until it
is observed and reviewed.

The resulting `CARAVAN`, `FOODCARAVAN`, `CARAVANOTHER` and `CARAVANHOME` notices
require complete exact original bodies and a sole observed OK. Acknowledgement
records the visible statement; subsequent native observations establish state.

Production of an offered Caravan/Freight already uses the existing production
chooser. Ordinary movement already permits an original role7 unit to request
entry into an occupied, known foreign city. Transport boarding/landfall remains
separate native input and decision handling. The original manual describes
city entry, naval carriage, trade and wonder contribution (local transcription
lines6973–7014); GAME resources2943–2984 supply the dialogs.

The planner separately offers `trade_delivery` and `assist_wonder` objectives to
living original Caravan/Freight units. Delivery uses owned or remembered city
coordinates on explored land, excluding the current square and the uniquely
observed home city. Wonder assistance uses an owned city's exact current wonder
production and the public `not_built` status. Original unit rules and observed
HP are corroborated. Unknown cargo demand, prospective revenue and foreign
ownership are never supplied as facts.

The existing category/target selection retains each offered leaf and its full
label. The candidate budget still reserves Hold and uses the same documented
round-robin ordering and omission counts. Objectives do not prune or execute
movement commands. Reaching the target completes only the travel objective;
the original arrival choice remains a separate model decision. Changed wonder
production, lost city/home identity or removed unit slots invalidate the plan
without claiming delivery or shield contribution. Offline verification binds
each new target to the native records and the actual model request.

Trade entry into an occupied remembered city no longer requires a foreign-owner
field: the native observation deliberately withholds that field. It requires a
unique remembered city coordinate on observed land and excludes an owned city.
The move label explicitly states that the present owner is unverified. An enemy
unit on a bare square does not enable a civilian trade interaction.

The Supply And Demand inquiry/report (`SUPPLYSEARCH`/`SUPPLYSHOW`) still lacks
live layout support and will pause if encountered. No home-city change is
introduced; the original game rejects changing a trade unit's home city.
