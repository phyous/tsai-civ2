# Jev × Civilization II

## Objective and completion evidence

Play the original game to an original-game victory: small map, Prince, five
civilizations including the player, restless tribes, standard rules, male Roman
leader. Record the entire successful game with the same polished display used
live. The game settings, model decisions, commands, saves, final result, and video
must be independently inspectable. Development tests and abandoned attempts are
kept separate from the successful run. A completed dashboard is not completion
of the task; the original game's victory must be verified.

## Runtime findings

The supplied PlayClassic page uses Emularity and Emscripten DOSBox. Its bundle
runs the 16-bit Windows Civilization II executable under Windows 3.1. BottleShip
from the StarCraft harness only supports PE32, so it cannot run this executable.
The selected route is a local embed of the supplied emulator and game. Game and
Windows files are downloaded into ignored local directories, never committed.
Runtime URLs, hashes, notices and version findings are recorded separately.

## Architecture

1. A local web server serves the dashboard and an isolated game iframe. The
   original emulator receives ordinary key and mouse events. The runtime bridge
   exposes bounded boot, pause, resume, input, capture and save-file operations.
2. Observation combines original pixels and original save files. A versioned
   decoder validates the save layout and projects only the Roman player's own
   information, discovered map and visible or legitimately remembered facts.
   Other civilizations' hidden maps, city internals and plans cannot enter the
   model prompt. Decoder uncertainty stops dependent actions.
3. A modal-aware controller constructs legal, concrete actions, bound to actor,
   turn and observed revision. Blocking dialogs take priority. Actual menu and
   dialog choices cover diplomacy, research, government, production, city labor,
   trade, unit orders, settlement, improvements, exploration and warfare.
4. Jev supplies named Choice probability vectors. Independent choices may share
   a call; dependent choices receive fresh state. A deterministic route selects
   the relevant vector without pretending independent marginals are a joint
   distribution. End Turn is explicit and guarded against duplication.
5. Inputs execute through the original UI, with before/after evidence and
   command receipts. Checkpoints permit technical recovery, documented in the
   run. Gameplay does not edit saves, memory, RNG, difficulty or game rules.
6. The web display shows original game pixels, empire facts, actual Jev
   probabilities, execution receipts, turn history, latency and usage. Missing
   information is shown as unavailable. Waiting displays retain the evaluated
   revision of prior probabilities. No displayed probability means win chance.
7. A recorder captures original game frames and the dashboard continuously,
   with a manifest, source hashes, exact request/response ledger and receipt
   trail. A verifier checks settings, chronology, binding, original outcome,
   and retained victory-screen evidence before publication.

## Interfaces and ownership

- `engine/runtime.html`, `engine/bridge.js`: original emulator adapter.
- `civ2/server.py`, `civ2/engine.py`: loopback server and constrained Python client.
- `civ2/save.py`: original-format validation and visibility projection.
- `civ2/observe.py`, `actions.py`, `policy.py`, `run.py`: observation and decisions.
- `civ2/typesafe.py`: hardened TypeSafe client reused from tsai-sc.
- `web/`: Roman-themed live display and replay surface.
- `civ2/recording.py`, `verify.py`: evidence and successful-run validation.

API credentials stay server-side in the existing private configuration. The
browser never receives them. Public source and release artifacts are audited
for credentials and proprietary runtime files before pushing.

## Alternatives and risks

An external iframe alone would prevent reliable state and recording access.
Freeciv would change the game, and BottleShip cannot run this binary. Save-based
observation is preferable to speculative segmented-memory decoding, but must
be tested against this early executable version. UI automation is vulnerable to
unexpected dialogs and exhausted movement; bounded retries, original pixels,
save validation and per-command receipts prevent silent drift. Model quality
on a full campaign is unproven: analyze actual losses and improve the harness
without presenting technical restarts as successful games.

## Implementation and verification sequence

Prove boot and capture first. Decode a real tutorial/save and cross-check in-game
facts. Verify the exact new-game setup. Exercise each command family on retained
test saves, including modal/stale-state failures. Then run Jev with checkpoints,
review strategy failures, and iterate to a full win. Review the visual design
at recording resolution, check live/video legibility, and publish source plus
the full successful game and its evidence only after verification.

Remaining implementation questions: validated save offsets for this version,
reliable fresh snapshots during dialogs, emulator save persistence, and the
original end-game result representation. Resolve these from actual runtime
evidence rather than assuming compatibility with later Civ II editions.
