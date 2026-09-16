# Native city labor controls

Jev may remove a worker from a known worked square to create an entertainer, or
assign a free entertainer to a known unworked square. These are ordinary Resource
Map clicks. The city center is immutable; taxman/scientist type changes are not
offered. Mixed or inconsistent specialist records also disable labor choices.
Other owned cities' worked squares, unknown terrain, map boundaries and visible
foreign-unit positions are excluded from assignment candidates.

Actions bind the exact owned city identity, native save SHA, original image SHA,
turn/year, labor bitmap, specialist counts and calibrated slot. A complete native
640×480 city screen must contain unique observed Resource Map/Citizens geometry
anchors. The model receives current labor facts and a per-city/year allowance:
at most twice population, capped at 40 dispatched labor inputs. Unchanged inputs
still consume the allowance. Omission due to this review budget does not imply
that a native action is illegal.

Before labor choices are enabled, the controller closes the city through its
observed Exit shortcut, writes and parses an original native save, then reopens
the same city through Shift+C and the observed city locator. After a chosen labor
click it repeats this transaction before offering another choice. This is
observation bookkeeping; it neither selects a labor target nor changes allocation
by itself. Outer empire/city review context is retained.

The follow-up save produces one explicit result: `observed_expected_change`,
`no_observed_change`, or `unexpected_change`. Expected means exactly the chosen
non-center bit and one entertainer changed in the specified direction, with the
same city/population/turn/year. An unexpected result pauses for inspection. Unknown
screens retain an incomplete transaction. The HUD's input receipt remains
*dispatched*; neither a click nor a visual repaint alone proves a labor result.
City yields are read from the subsequent native save, never predicted by summing
base terrain specifications.

## Calibration

The isolated `labor-calibration-01` run individually clicked all 20 non-center
positions in the original executable and read back each resulting native save.
The grid uses doubled-X map offsets: native pixel
`(104 + 24·dx, 192 + 12·dy)`. Every recorded slot matched its expected worker bit.
The original center slot 16 was never clicked. The local report and original
SAV/PNG receipts stay in ignored `.runtime/labor-calibration-01/`.

| Slot | Pixel | Native city byte / bit |
|---:|:---:|:---:|
| 0 | 104,168 | 48 / 7 |
| 1 | 80,180 | 48 / 6 |
| 2 | 56,192 | 48 / 5 |
| 3 | 80,204 | 48 / 4 |
| 4 | 104,216 | 48 / 3 |
| 5 | 128,204 | 48 / 2 |
| 6 | 152,192 | 48 / 1 |
| 7 | 128,180 | 48 / 0 |
| 8 | 128,228 | 49 / 7 |
| 9 | 176,204 | 49 / 6 |
| 10 | 176,180 | 49 / 5 |
| 11 | 128,156 | 49 / 4 |
| 12 | 56,168 | 49 / 3 |
| 13 | 56,216 | 49 / 2 |
| 14 | 152,216 | 49 / 1 |
| 15 | 152,168 | 49 / 0 |
| 17 | 80,156 | 50 / 3 |
| 18 | 32,180 | 50 / 2 |
| 19 | 32,204 | 50 / 1 |
| 20 | 80,228 | 50 / 0 |

The baseline worker-plus-center save SHA was
`d80f0f8be230bbf53c4df9dae3aad92b95c12cfd1df1354c46c9bc71cac12163`.
Removing that worker produced a center-only bitmap and exactly one entertainer
in save SHA `af0c17eb5d3453d713a2adf2a0f9b7c2c285954a890eeee4c01c1730f80e2a8e`.
Clicking the entertainer portrait in this size-one city produced the original
rule notice that taxmen/scientists require at least five population; it did not
change the specialist. No type-switch action is enabled by that rejection.

This calibration used one size-one city and the original 640×480 layout, including
observed ocean squares. It proves the slot mapping and measured transactions,
not a city-management strategy or campaign win. Optional local tests independently
compare the 20 retained native saves; public tests use explicitly synthetic data.
