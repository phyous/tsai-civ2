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

For the macOS OCR adapter:

```sh
mkdir -p .runtime
DEVELOPER_DIR=/Library/Developer/CommandLineTools swiftc scripts/ocr.swift -o .runtime/ocr
```

TypeSafe authentication is read by the Python client from `TYPESAFE_API_KEY` or
an explicitly selected private env file. Credentials never enter the page or run
evidence. Do not commit `.env`, downloaded games, profiles, or private files.

The current controller is experimental and pauses at unsupported native screens.
After building the OCR adapter, start and verify a fresh game with
`python3 -m civ2.boot`. A model session uses:

```sh
python3 -m civ2.run --initial-save .runtime/setup/initial.sav \
  --directory runs/attempt-001 --env-file /path/to/private/env
```

Install `ffmpeg` for continuous video capture.
The dense spectator panel can show 16 command probabilities and separate
independent Jev vectors in the same live/recording layout.

## Acknowledgments

TypeSafe's [System One / Jev demonstration](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
inspired the probability display. Runtime provenance, licenses and version
findings will be recorded in [engine/](engine/). Civilization II is the original
MicroProse game; this independent experiment is not affiliated with its owners.
