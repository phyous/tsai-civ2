# Jev × Civilization II

An original Civilization II browser harness for TypeSafe Jev, with live decision
probabilities and a Roman-themed spectator display. **Under development; no
complete-game victory has been verified yet.**

The target is a full win as a male Roman leader, on a small map at Prince
difficulty with five civilizations, restless tribes and standard rules.

The runtime uses the original Windows game in DOSBox/Windows 3.1, matching the
[browser version supplied for this project](https://playclassic.games/games/turn-based-strategy-dos-games-online/play-sid-meiers-civilization-ii-online/play/).
Original game and Windows binaries stay in ignored local storage. This repository
contains the harness, not those proprietary assets.

See [the architecture plan](docs/plans/architecture.md) and
[development record](docs/development-log.md). The controller uses
player-observable state, original game pixels and ordinary keyboard/mouse inputs.
Named Jev Choice vectors cover empire policy, cities, research, diplomacy, units,
exploration and warfare. Displayed values are action probabilities, not a
probability of victory.

## Local development

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
python3 scripts/fetch_runtime.py
python3 -m civ2.server
# Open http://127.0.0.1:3920
```

For long campaigns, use the [dedicated Chrome launcher](docs/runtime-launcher.md).
It gives each parallel game its own local server and isolated browser profile,
with background page throttling disabled. The game remains embedded in the same
spectator dashboard; `/web/watch.html` provides the read-only browser view.

For the faster optional WebAssembly backend, fetch its pinned assets and start
a fresh runtime:

```sh
python3 scripts/fetch_modern_runtime.py
python3 -m civ2.launcher start --name campaign-modern --port 3930 --backend modern
```

The [modern runtime notes](engine/modern-runtime.md) describe the verified asset
hashes and host pause fix. This changes the emulator host, while retaining the
original game and the same observation, input and recording interfaces.

For the macOS OCR adapter:

```sh
mkdir -p .runtime
DEVELOPER_DIR=/Library/Developer/CommandLineTools swiftc scripts/ocr.swift -o .runtime/ocr
```

TypeSafe authentication is read by the Python client from `TYPESAFE_API_KEY` or
an explicitly selected private env file. Credentials never enter the page or run
evidence. Do not commit `.env`, downloaded games, profiles, or private files.

The current controller is experimental and pauses at unsupported native screens.
After building the OCR adapter, a debugging session can use native saves:

```sh
python3 -m civ2.boot
python3 -m civ2.run --initial-save .runtime/setup/initial.sav \
  --directory runs/attempt-001 --env-file /path/to/private/env
```

Install `ffmpeg` for continuous video capture.
The dense spectator panel can show 16 command probabilities and separate
independent Jev vectors in the same live/recording layout, plus recent evaluations
when there is room. [Native city labor](docs/labor-controls.md) includes calibrated
worker reassignment and a fresh state check after every change. The
[persistent OCR worker](docs/ocr-performance.md) reduces observation overhead.
The [researched strategy guide](docs/strategy-sources.md) is included in actual
Jev requests, with its revision and sources retained in the decision evidence.

The recording path uses a [read-only Win16 observer](docs/observer-build.md),
which reads the original game's state without a Save dialog or game-memory
writes. Build its ignored runtime overlay, then use a fresh runtime:

```sh
python3 -m civ2.boot --port 3930 --profile final-001 \
  --directory .runtime/final-001-setup --no-saves
python3 -m civ2.run --port 3930 --no-saves \
  --setup-directory .runtime/final-001-setup --directory runs/final-001 --planning
```

Setup verifies that native autosave is off before model play. The original
startup autosave, if created before that setting can be changed, is recorded
explicitly; later new or modified game saves stop the run. Host observation
capsules, screenshots and video are evidence files, not game saves. Native
save-based debugging remains available separately.

## Optional observed-target planning

The default controller asks Jev for each current unit command. The experimental
Python option `Session(..., planning=True)` first lets Jev choose a persistent
task and observed target, then makes a separate call for the next unit command.
Every unit order is still independently model-selected from the same canonical
actions. Planning executes no input, forces no path and uses no hidden map data.

Task choices and command choices have distinct evidence events, probability
displays and counts. Plans are reviewed after observed completion, invalidation
or bounded expiry. Add `--planning` to the CLI to enable it, and `--port 3921`
to select a separately prepared runtime. See
[planning setup, comparison and limitations](docs/planning.md) for the Python
entry point and parallel-runtime requirements. Neither mode has a verified
complete-game victory yet.

Open `/web/watch.html` on a running server for a responsive, read-only live view
without creating another emulator connection.

## Acknowledgments

TypeSafe's [System One / Jev demonstration](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
inspired the probability display. Runtime provenance, licenses and version
findings will be recorded in [engine/](engine/). Civilization II is the original
MicroProse game; this independent experiment is not affiliated with its owners.
