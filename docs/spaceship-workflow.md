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

## Remaining complete-game path

The original manual's “Construction,” “Components,” “Modules” and “Spaceships”
sections explain that part delivery is automatic; completed parts trigger type
choices and a spaceship display. There is no placement editor to invent.
Original RULES improvement IDs 35–37 are SS Structural, SS Component and
SS Module; Apollo Program is 64. The current production dialog already offers
all exact, actually observed RULES names through the ordinary independent
model choice. The conservative `eligible_production` helper requires an
explicit space-race unlock, but it is not called by that runtime path.

The next minimal capability is the original **F12 report workflow**:

1. Offer a genuine empire choice to open Spaceships via F12, sourced from
   original `MENU.TXT` line 82 (`&Spaceships|F12`). Add that exact command to
   the runner's observation bookkeeping and independent verifier mapping.
2. Capture the original `SPACESHIPS` civilization selector and `SPACESHIP`
   report, including every observed alternative and actual report control.
   The report's selected civilization, displayed specifications and Launch
   control need real foreground geometry; the raw GAME template alone is
   insufficient. A model choice to open the report does not authorize launch.
3. A separate model-selected observed Launch control reaches `LAUNCH`, whose
   two-choice confirmation is supported by this batch. Then observe the
   original response and continue ordinary turns; do not predict arrival.
4. Review the original final arrival/winner presentation and record the
   player's terminal outcome. Launch or a generic arrival sentence alone is
   insufficient victory evidence.

The current harness has no F12 empire action, no spaceship selector/report
classifier and no report Launch-control calibration. Consequently this batch
does **not** establish a complete executable space-victory path. Reports may
also appear automatically after part completion and block there until that
workflow is added.

Original private sources: `GAME.TXT` lines 1073–1077 (`BADSPACE`), 3272–3337
(space race, report, confirmations, components/modules and ship notices), and
3813–3816 (`NOSPACESHIPS`); `MENU.TXT` line 82; the original manual's space-race
and construction sections. No game text file, font atlas or screenshot is
distributed by these tests or documentation.
