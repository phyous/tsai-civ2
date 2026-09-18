# Original spaceship choices

`civ2/spaceship.py` recognizes three original GAME.TXT prompts. Every actual
alternative becomes a separate Jev choice; the classifier never selects one.

| Resource | Required observed choices |
| --- | --- |
| `COMPONENT` | Propulsion and Fuel, each with its displayed “so far” count |
| `MODULE` | Habitation, Life Support and Solar Panel, each with its displayed count |
| `LAUNCH` | No Launch. and Launch CONFIRMED!, with the complete displayed success percentage |

The source records must equal the original pinned records. Component/module
records also require the literal `@options` directive and exact original option
lines: the older generic GAME parser represents these lines as body text, so
the parsed record alone does not establish that they are options.

The observation must contain an exact title, all text and a sole aligned OK.
A hash-checked original PNG must show a complete native frame and exactly one
native radio for each observed option. The scan includes the entire option
band, so an OCR-omitted radio cannot silently remove an alternative. All rows
intersecting the foreground must belong to the complete recognized dialog.
Extra choices, missing counts, altered probability terms, additional controls,
incomplete frames, low confidence and mismatching source records fail closed.
Observed option text and counts remain in the model request and evidence.
The displayed percentage is reported as text from the game, not calculated.

These are source and synthetic pixel tests, **not live spaceship calibration**.
The reused frame/radio primitives were measured on the original game's other
native dialogs. A different actual spaceship layout will stop for inspection.
No campaign inputs were issued to develop this batch.

Seven original informational resources are separately pinned in
`native_events.py` and `verify.py`: `BADSPACE`, `SPACERACE`, `LAUNCHED`,
`NOFURTHER`, `SPACERETURNS`, `SPACEDESTROYED` and `NOSPACESHIPS`. Only the
complete original body and sole observed OK permit acknowledgement. Their
observed words can be retained as public notices; no ship, launch, arrival or
victory state is inferred. `EAGLEHASLANDED` remains the existing unsupported
arrival review, because a rival's arrival is not proof of a player victory.

## F12 selector and report

`spaceship_report.py` now supplies guarded classifiers for the original
`SPACESHIPS` selector and `SPACESHIP` text report. The empire choice
`open_spaceships` sends only F12. It appears after an observed public Apollo
completion or current owned spaceship-part production, and is suppressed in
Bloodlust games. Its independent verifier checks the same original command
against native public/owned records. A review completes only after the actual
selector/report or the original `NOSPACESHIPS` notice is observed and the
transaction returns to the map.

The selector requires every actual radio, an original RULES tribe/adjective
label per row, and both observed OK/Cancel buttons. Even a one-ship selector
has two genuine choices: inspect that observed ship or Cancel. Neither F12 nor
a civilization selection authorizes a launch.

The text report requires its original ship header, all six part-count rows and
all seven displayed statistics: Population, Support, Energy, Mass, Fuel,
Flight Time and Prob. of Success. Aligned nonoverlapping OCR columns may join
into a readout, preserving every original source row. Values are read from the
screen, never computed. Unknown extra text or incomplete statistics stop the
classifier. Optional original post-launch status remains observed prose.

Every bottom button must have an independently observed native black border,
white top bevel and gray right bevel. These generic button primitives were
checked against all three buttons of the original F3 report. The entire bottom
band is counted, so a button omitted by OCR cannot silently disappear from the
model's alternatives. Both Launch and OK become model choices if present;
clicking either button sends no trailing Enter. A complete report with only an
actual OK may be acknowledged without fabricating a model distribution.
Launch requests the separate `LAUNCH` confirmation described above.

Static original executable evidence corroborates the resource connection.
The unmodified 1.06 executable SHA-256 is
`b5a64ecbd8ebdd37e3ca2391c57319fec7ac227fcd2c3b9c96498969ea51ef96`.
NE segment 22, offset `09a4`, constructs the `SPACESHIP` report; `0af4` begins
the six part rows; `0be0`–`1008` adds the statistics; `1127` references the
original Launch label; and `118f` names the separate `LAUNCH` confirmation.
The F12 selector begins at `22:1d29`, uses `SPACESHIPS` at `1d6b`, and calls the
report at `1e57`. This is bounded read-only static corroboration, not a full
decompilation or proof of the runtime layout.

## Complete-game path and remaining validation

The original manual's “Construction,” “Components,” “Modules” and “Spaceships”
sections explain that part delivery is automatic; completed parts trigger type
choices and a spaceship display. There is no placement editor to invent.
Original RULES improvement IDs 35–37 are SS Structural, SS Component and
SS Module; Apollo Program is 64. The current production dialog already offers
all exact, actually observed RULES names through the ordinary independent
model choice. The conservative `eligible_production` helper requires an
explicit space-race unlock, but it is not called by that runtime path.

The intended original **F12 report workflow** is now wired as follows:

1. A genuine empire choice opens Spaceships via F12, sourced from original
   `MENU.TXT` line 82 (`&Spaceships|F12`). The runner and verifier retain the
   distinction between opening a screen and choosing its controls.
2. The selector and complete text report pass the source, label, native-frame,
   complete-radio and button-border guards above. A model choice to open the
   report does not authorize launch.
3. A separate model-selected observed Launch control reaches `LAUNCH`, whose
   two-choice confirmation is supported by this batch. Then observe the
   original response and continue ordinary turns; do not predict arrival.
4. Review the original final arrival/winner presentation and record the
   player's terminal outcome. Launch or a generic arrival sentence alone is
   insufficient victory evidence.

The selector/report and new F12 route have source, synthetic native-frame and
offline action-binding tests. They have **not** been exercised on an actual
spaceship. The original manual's page 132 also shows a separate graphical ship
display; that surface is not misclassified as the text report, and its actual
transition still needs calibration. Unknown layouts will pause. Reports may
appear automatically after part completion as well as through F12. This batch
does **not** claim an end-to-end verified space victory. The next validation is
an isolated original late-game save: select each available ship, inspect its
actual report, request Launch through a real model choice, then verify that the
separate confirmation and subsequent original response are observed. No
production campaign inputs or synthetic state changes were used here.

Original private sources: `GAME.TXT` lines 1073–1077 (`BADSPACE`), 3272–3337
(space race, report, confirmations, components/modules and ship notices), and
3813–3816 (`NOSPACESHIPS`); `MENU.TXT` line 82; the original manual's space-race
and construction sections. No game text file, font atlas or screenshot is
distributed by these tests or documentation.
