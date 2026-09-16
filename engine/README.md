# Original Civilization II runtime

This page boots the exact game and emulator supplied by the user's
[PlayClassic link](https://playclassic.games/games/turn-based-strategy-dos-games-online/play-sid-meiers-civilization-ii-online/play/).
The executable is **Civilization II 1.06 27-Mar-96**, corroborated by its embedded
version string and bundled `PATCH.TXT`. It is a 16-bit Windows NE executable,
running in Windows 3.1 inside the site's Emscripten em-dosbox build. BottleShip's
PE32 loader cannot run this executable.

Run `python3 scripts/fetch_runtime.py` from the repository. It downloads the
unchanged emulator files into `engine/vendor/` and the unchanged 48 MB game/Windows
ZIP into `engine/game/`. Both directories are ignored. URLs, exact sizes, SHA-256
hashes and the executable hash are in [runtime-manifest.json](runtime-manifest.json).
The source site's download endpoint requires its ordinary page Referer; no login
or account data is used. The script checks every download and the executable
inside the ZIP. Proprietary game and Windows files are never repository source.
Setup also derives `vendor/dosbox-input.js` from the unchanged verified emulator.
[input-patch.json](input-patch.json) records the exact single export-table
addition and both hashes. It exposes the already-compiled `Mouse_CursorMoved`
and `SDL_SendMouseMotion` host input functions; no function body, game binary or
game rule is patched. The derived
emulator retains DOSBox/em-dosbox's GPL-2.0 terms and its third-party notices;
both original and derived emulator downloads remain ignored local assets.

Serve the repository using the parent harness server and open
`/engine/runtime.html`. The iframe loads `/transport.js`, supplied by that server,
after its game bridge. Assets need HTTP; opening `runtime.html` as a local file
does not work. The runtime does not auto-start unless `?autoboot=1` is present.
Start through the **Start game** button or `await Civ2Runtime.boot()`.
The spectator iframe uses `?embed=1`, which hides the standalone navigation and
fits the original 4:3 canvas into its available rectangle with letterboxing.

The original boot sequence mounts the ZIP as DOS drive C:, runs `windows.bat`,
starts Windows, then uses the bundled `WIN.INI` entry `run=c:\civ2\CIV2.EXE`.
No game executable, rules, map or native game state is patched. `boot()` resolves
when DOSBox starts; Windows and the game's opening screens still take time.
Before DOSBox initializes its display/input subsystem, the loader mounts our
small [dosbox.conf](dosbox.conf) and passes `-conf /emulator/dosbox.conf`. It sets
`[sdl] autolock=false`.
`sensitivity=100` retains the original mouse gain. The relative-input API avoids
host-coordinate limits, and the feedback click helper measures the actual visible
cursor instead of assuming an exact pixel mapping. An earlier development
configuration used200 to reach more of the guest screen through absolute input;
that also amplified Windows cursor quantization and is no longer used.
This changes the host mouse capture setting so standard absolute DOM mouse events
reach the guest. With its default autolock enabled, DOSBox ignores motion until
browser pointer lock succeeds; synthetic input cannot acquire that permission
through a real user gesture. The setting uses DOSBox's normal configuration
file, with no memory flag writes, and does not change game rules. Setting the
option later with a DOS command did not reliably change the initialized mouse
gate in the original runtime, so this must be startup configuration.

## Page interface

`window.Civ2Runtime` is a frozen interface owned by this iframe. The parent
transport should allow only the commands it needs and bind only to loopback.
There is no generic JavaScript evaluation or guest-memory write method.

```js
await Civ2Runtime.boot({profile: "run-01"});
Civ2Runtime.status();
Civ2Runtime.inputDiagnostics();
Civ2Runtime.pause();
Civ2Runtime.resume();
await Civ2Runtime.key("Enter", {holdMs: 60});
await Civ2Runtime.chord(["ControlLeft", "KeyS"], {holdMs: 70});
await Civ2Runtime.click(320, 240, {button: 0, holdMs: 60});
Civ2Runtime.mouse({type: "mousemove", x: 100, y: 200});
Civ2Runtime.moveRelative(4, -3);
Civ2Runtime.releaseInputs();
const pngDataURL = Civ2Runtime.capture();
const files = Civ2Runtime.listSaves();
const bytes = Civ2Runtime.readSave("ROME.SAV");
```

Keys use physical `KeyboardEvent.code` names: `KeyA`–`KeyZ`, `Digit0`–`Digit9`,
`Numpad0`–`Numpad9`, arrows, navigation keys, `F1`–`F12`, and left/right modifiers.
The helper sends ordinary bubbling keydown/keyup events to the original canvas.
Mouse events use original canvas pixels, with `0` left / `1` middle / `2` right.
The helper converts pixels to the displayed canvas rectangle and sends ordinary
mousemove/mousedown/mouseup events. Key and click holds are bounded to 1–1000 ms.
Each emitted input has a monotonically increasing receipt sequence number.
Helpers do not silently resume a paused emulator; the controller owns pacing.
`moveRelative(dx,dy)` accepts nonzero integer deltas bounded to ±32 per axis and
calls the original DOSBox host input function
`Mouse_CursorMoved(dx,dy,0,0,true)`. Its `emulate=true` mode accumulates relative
motion through the original scaling, PS/2 callback and event/IRQ handlers.
The wrapper does not assign emulator or guest memory. A receipt proves dispatch;
the screenshot feedback helper must verify the original guest cursor before clicking.
An earlier SDL relative-event export preserved SDL deltas but DOSBox's unlocked
handler still selected absolute cursor positioning, so it could saturate at the
host edge. The regression test now executes that original downstream handler too.
`chord` accepts one to three distinct Control/Shift/Alt physical modifiers and one
ordinary final key. It validates the entire request before input, holds the final
key for a bounded interval, and releases all modifiers in reverse order even if
dispatch fails. Keeping it within one transport command prevents other server
commands from interleaving with a key chord.

This synchronous DOSBox build yields through Emterpreter's async callback queue.
Pause/resume gate `Browser.pauseAsyncCallbacks()` / `resumeAsyncCallbacks()`,
including its deferred yield callback, so the interpreter's scheduled continuation
remains parked until resumed. Both commands are idempotent. The ordinary
`Module.resumeMainLoop()` is unsuitable here: the separate animation main loop
can be empty, leaving its scheduler null and throwing on resume. The site's
`EmscriptenRunner.pause()` is also an empty stub. `inputDiagnostics().scheduler`
reports the selected backend, async state, queued callbacks and any bounded
control error for local diagnosis.
The screenshot is the original game canvas PNG. The wrapper preserves this
canvas's WebGL drawing buffer if WebGL is used, so a capture after a rendered
frame remains available. It does not synthesize a game image or read the desktop.

## Native saves and persistence

The DOS C: drive is mounted at Emscripten `/emulator/c`. BrowserFS places writes in
an overlay and mirrors them into IndexedDB, under `tsai-civ2-v1-<profile>`.
Choose a new profile for a new isolated filesystem. Reusing a profile resumes its
filesystem, including normal saves; it does not resume CPU execution automatically.

`listSaves()` and `readSave(name)` inspect the actual files under
`/emulator/c/civ2/`. Saves must first be written by the game's ordinary Save menu.
Read access is restricted to simple `.sav` filenames, with a 4 MiB limit, and
case-insensitive lookup rejects ambiguous matches. Save bytes contain hidden
world data: the observation layer must apply the player's visibility and ownership
rules before presenting facts to Jev.

For explicit setup/recovery only, `importSave(name, Uint8Array)` can add a new,
bounded `.sav` file to that directory; it refuses overwrites. The pinned runtime's
binary stream API preserves all bytes, closes the stream on failure, and verifies
the complete readback before reporting success. Import does not load
or modify the running game. Loading remains an ordinary game-menu action. This
method is not a model action and should be excluded from the gameplay transport
allowlist. There are no arbitrary filesystem paths or memory writes in the API.

The Emscripten heap is not a flat address map for Civ II: DOSBox executes a
segmented Win16 process. Native save parsing is therefore the initial structured
observation route. Runtime input/capture hooks are source-tested; the harness must
also verify real game responses and visible state during its integration boot.

`inputDiagnostics()` is read-only and returns canvas geometry, registered mouse
event targets, the last dispatched mouse coordinates, the bounded startup config,
and fixed DOSBox/SDL input state recovered from the hash-pinned runtime. In the
original compiled SDL_MOUSEMOTION handler, byte406187 is `sdl.mouse.locked` and
byte406185 is `sdl.mouse.autoenable`; motion reaches DOSBox only when locked or
autoenable is false. The adjacent bytes406184/406186 hold autolock/requestlock.
SDL's cursor X/Y and buttons/relative mode are also reported. These are host
emulator input diagnostics, not Civ II game records, and there is no memory-write
operation or arbitrary address argument. They help distinguish emitted DOM
receipts from input that reached the original game.

```sh
node --test engine/bridge.test.cjs
node --test engine/input-patch.test.cjs
node --test engine/pause.test.cjs
python3 scripts/fetch_runtime.py
```
