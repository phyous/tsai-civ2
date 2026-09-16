# Development record

The full-game objective remains open. No complete Civilization II victory has
been claimed or verified.

## Calibration before the campaign

- The linked browser game is the original Civilization II 1.06 Windows program,
  running inside Windows 3.1 and DOSBox. The harness serves those runtime files
  locally in its own iframe. Original game/Windows assets remain private.
- Initial mouse events were blocked by DOSBox's pointer-lock gate. Applying
  `autolock=false` before emulator initialization enabled the input path.
- A throwaway setup retained Chieftain, seven civilizations and a normal map:
  absolute SDL coordinates did not match the Windows guest cursor. The native
  save caught this before a model-controlled game began.
- Cursor feedback exposed Windows mouse acceleration and host coordinate limits.
  A separately hashed emulator derivative exports its existing SDL relative
  mouse-event function. It does not modify the game, a save, or guest memory.
- Keyboard setup produced a native save verifying small map (40×50 logical
  tiles), Prince, five civilizations, Restless Tribes, standard rules, male Rome,
  and an untouched 4000 BC start with two Settlers.
- Pilot 001 made one real Jev 1.13 API call: 4,488 input tokens, 154 output tokens,
  261.452 ms, choosing settlement at 94%. No command executed: the old emulator's
  main-loop resume API failed. This is an input calibration, not a battle or win.
- The emulator actually yields through Emterpreter callbacks. The bridge now
  gates that callback queue; live checks confirm it queues while paused and
  drains on resume. Main-loop-only mocks would have missed this distinction.
- Native bitmap-font OCR occasionally reads “Game saved” as “Game samed.” A
  bounded heading match plus the Roman leader notice is backed by reading and
  parsing the actual original save file.

## Evidence conventions

Each model session retains original saves, original screenshots, requests,
validated responses, ordinary input receipts and a hash-linked event ledger.
The continuous recording contains only real captured dashboard frames; capture
gaps repeat the preceding frame. A batch save delta is not attributed to an
individual command without additional evidence. Hidden foreign game information
is excluded from model observations.

An end-game text cue is only a candidate for inspection. Completion requires
the original game's Roman victory, the requested settings, a full recording and
a reviewed evidence bundle.
