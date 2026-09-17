# Optional modern DOSBox runtime

`python3 scripts/fetch_modern_runtime.py` fetches the pinned GPL js-dos
`emulators` 8.4.2 package. `modern-manifest.json` records the official archive and
individual asset sizes and SHA-256 hashes. The launcher selects this backend
with `--backend modern`; the legacy backend remains the default.

The original Civ II, Windows, and DOSBox WASM binary are unchanged. One derived
JavaScript asset fixes host pause scheduling. The source and resulting hashes,
exact replacement, and GPL license are recorded in
`modern-scheduler-patch.json`; the fetcher verifies the original package bytes
before applying that replacement and verifies the derived bytes afterward.

The original worker can receive a queued `wc-sync-sleep` after pause. Its handler
otherwise wakes the emulated CPU despite the pause flag, including after a future
`wakeUpAt` deadline. The derivative retains that original callback while paused,
checks the host pause flag with one bounded timer, and dispatches the callback
only after resume. It drops the timer if the worker exits. No guest memory or
save data is written by this fix.

The bridge additionally waits for two worker filesystem-read replies after
pause, so preceding original frame messages reach the canvas before capture.
Boot waits for the first valid original frame. Capture always copies that canvas;
it does not redraw or synthesize the game image. Existing already-loaded workers
need a fresh runtime to load the scheduler fix. A compatibility read fence can
reduce their queued-frame race, but the strict unchanged-screen guard is still
required and is never relaxed.

Run `node --test engine/modern*.test.cjs` and
`python3 -m unittest tests.test_fetch_modern_runtime` to check the bounded bridge,
the exact original and derived scheduler functions, and fetch integrity.

Native save imports use uppercase DOS filenames so the original Windows file dialog can find them on the case-sensitive browser filesystem. Import still refuses any case-insensitive existing filename and verifies all original bytes.
