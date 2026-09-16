# Read-only native observer build

The no-save playthrough reads original Civilization II 1.06 data with the Windows 3.1 ToolHelp `MemoryRead` API. The helper is a separate hidden Win16 program. It does not patch `CIV2.EXE`, write game memory, select units, or issue gameplay commands. Its fixed mailbox accepts a nonce rather than an arbitrary address. The Python decoder applies the same own/visible-state filtering as the debug save decoder before model requests.

First fetch the hash-pinned original runtime, then build the helper:

```sh
python3 scripts/fetch_runtime.py
python3 scripts/build-observer.py
```

Docker must support Linux amd64 containers. The build uses:

| Input | Pinned value |
| --- | --- |
| Compiler | [Official Open Watcom 2.0 Linux x64 installer](https://github.com/open-watcom/open-watcom-v2/releases/download/Current-build/open-watcom-2_0-c-linux-x64), September 14, 2026 build |
| Compiler SHA-256 | `b51ad127b52c44ddcc9451e4960674b9b31b1457b84c798521dcf3f84c494273` |
| Container | `debian@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171`, platform `linux/amd64` |
| Helper source SHA-256 | `ce82cdd26379bdd2817fb1fd87b34474a21753b3a043046dcdee84da74760dc5` |
| Compiled helper SHA-256 | `b2ca27df1f3c15d6cdbcc8411be761e4d96fd018425bc23c65df329490432236` |
| Original `CIV2.EXE` SHA-256 | `b5a64ecbd8ebdd37e3ca2391c57319fec7ac227fcd2c3b9c96498969ea51ef96` |

`Current-build` is a mutable upstream URL. A different download is rejected. If it has moved, supply an existing copy of that exact official installer with `--compiler-archive PATH`; the checksum is still mandatory. There is no automatic fallback to another compiler. The Open Watcom distribution has its own [license](https://github.com/open-watcom/open-watcom-v2#readme); the compiler is not vendored into this repository.

The script extracts only the required compiler headers, libraries, and Linux tools under ignored `.runtime/observer-build/`. Every cached toolchain file is compared against the pinned installer. Compilation runs without container network access and with read-only source/toolchain mounts:

```text
wcl -bt=windows -ms -zW -fe=civ2obs.exe /src/civ2_observer.c toolhelp.lib
```

The resulting binary must equal the calibrated helper hash. A source or compiler change requires a separately reviewed calibration and pin update.

The script writes ignored `engine/game/civ2-win31-observer.zip`. Compared with the downloaded original archive, it adds `CIV2OBS.EXE` and changes only the empty `WINDOWS/WIN.INI` load entry to `load=c:\CIV2OBS.EXE`. It then checks every decompressed archive member: all other original bytes, including `CIV2.EXE`, Windows binaries, game rules and artwork, must remain identical. The original archive is retained. Build provenance is written to ignored `engine/game/observer-build.json`. Do not publish either game archive, Windows files, compiler bundle, or private observation capsules.

A runtime boot with `observer: true` selects this private archive. Fresh setup supports:

```sh
python3 -m civ2.boot --port 3930 --profile final-001 --directory .runtime/final-001-setup --no-saves
```

Use a fresh dedicated runtime, with the local server/browser already connected. Setup makes the original menu selections, explicitly disables **Autosave each turn**, and verifies all eleven Game Options checkboxes. It reads the untouched initial state through the observer and writes host-side `initial-observation.json` and image evidence. This command never invokes the game's Save dialog. The original game may create its startup autosave before the preference can be changed; its presence must be declared in the campaign's starting file inventory. From the verified setup boundary onward, the live observer rejects a new or changed game save. The requirement is no saves during the playthrough, not a claim that the original installation has no pre-existing `.SAV` files.

`load_setup_report(directory, require_no_saves=True)` checks the packaged images, native initial-state capsule, original settings, and explicit autosave-off readback before the campaign copies them into its audit journal. Image capture and these host-side evidence files are observations, not game saves.
