# Strategic facts supplied to Jev

The controller supplies observed facts and original rules; Jev still selects every
strategic command and confirmation. Inspecting the early parallel campaigns
showed that government and military controls were available, but their consequences
were not always prominent in the compact observation.

One campaign knew Monarchy while retaining Despotism. Its end-turn menu offered
the revolution route on thirteen consecutive reviews, and Jev chose Finish Turn.
That was a model choice, not a missing command. Original government mechanics
require a revolution and separate government selection; discovering the advance
does not adopt it. Requests now state the current government and prerequisite-
satisfied alternatives together, with the possible intervening Anarchy. These
are concepts to consider, not automatically legal clicks or a prescribed switch.

The early production menus offered Warriors and Phalanx, but the old compact
unit-specification table only described types already owned. An empire with no
army therefore saw defender names without that structured comparison. Production
requests now join original RULES.TXT costs and specifications to exact options
actually present in the observed menu. Ambiguous or unmatched names remain
unmatched; no extra choice is added.

A compact empire summary also lists owned units at each city, counts units with
positive original base attack and worker-role units, and identifies cities
currently producing worker-role units. Unknown specifications stay explicit.
These are current native-checkpoint facts, not defense forecasts, completion
dates, claims that a city is safe, or information about hidden opponents.

Repeated records are submitted as readable tables with explicit column names
and missing-cell markers. Decoding preserves the supplied game facts, record
order, historical text and outcomes, including the difference between an absent
field and an explicit unknown value. Action choices are not pruned. Historical
audit hashes and wall-clock timestamps remain in the evidence journal instead
of consuming model context; the submitted compact request itself is retained
and hashed. Verification checks the decoded notice history against the original
observed events. This addressed a measured `max_tokens_exceeded` response in
attempt 010: its next compact planning call retained all 64 choices and used
23,361 input tokens.

The labor description now reflects the completed twenty-position calibration.
Only separately offered city actions after a fresh native checkpoint authorize
labor inputs; specialist-type cycling remains unavailable.

## Passenger transport

The original manual's **Ground Units** section describes boarding passenger
ships and the separate **Make Landfall** choice. The movement candidate builder
previously rejected every ground move into known Ocean, even when an owned
passenger transport was observed there. Ground units may now request that
ordinary directional move when the destination has an owned ship whose original
rules specify naval domain, passenger-transport role and positive capacity.
The action binds the current ship identities and original capacities; it does
not infer their cargo or free space. Carrier/submarine special cargo roles do
not qualify as ground passenger transports.

A passenger transport on observed Ocean may also request a direction toward
observed land. This only requests the original landfall interaction; it does not
claim the ship moved onto land or authorize a subsequent dialog choice. The
native unload command remains separate. Known land-to-water moves without an
observed own transport remain unavailable. These additions have policy and
stale-state tests; a complete original boarding-and-landing transaction has not
yet been observed in a live campaign. Unsupported follow-up dialogs still pause
before further input.
