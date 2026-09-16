# Offline evidence verification

Run from the repository root after an attempt stops:

```sh
python3 -m civ2.verify runs/attempt-002 --output verification.json
```

The command reads local evidence and optionally runs `ffprobe`. It does not contact Jev, read credentials, control the emulator, perform OCR, modify saves or publish files. The output file must be new. `verify_run(directory, terminal_review=None, ffprobe='auto')` offers the same checks to Python callers and raises `VerificationError` on invalid evidence. `--no-ffprobe` explicitly leaves encoded-media validation unavailable.

The report checks:

- Every journal hash, predecessor, sequence and elapsed-time ordering, starting with one `begin` event.
- Referenced artifact hashes and byte counts, confined relative paths, and retained original screenshots referenced by hashes inside input receipts. Paths or symlinks escaping the run are rejected.
- The actual initial classic save: small map, Prince, five civilizations, Restless Tribes, male Rome, standard rules, turn 1 / 4000 BC with no founded cities. Ledger claims alone do not establish setup. Checkpoint dates and stable settings are checked against their saved bytes.
- Each retained request and actual response using the client's strict probability validator, including its documented narrow rounded-Choice compatibility. The selected action must match the returned choice and criterion. Unit actors must match the selected owned unit in the referenced native save; dialog targets and empire commands retain their observed-image bindings.
- Dispatch receipts: exactly the selected ordinary keyboard command, or the selected dialog click and optional Enter. Mouse feedback targets, bounded relative movement and balanced key/button releases are checked. A model decision without a dispatch remains explicitly undispatched. Input delivery does not prove native acceptance or a strategic effect.
- Recording manifest/journal agreement, sample numbering/timing, frame count and duration. When available, `ffprobe` additionally checks the encoded video dimensions, frame rate, duration and reported frame count.

`dialog_keyboard_recovery` records are reported separately. They bind a manually reviewed keyboard selection to an existing model choice; they do not count as automatically verified dispatches or proof of an autonomous run. Unknown development events are counted and prevent the report's `release_review_ready` flag. Incomplete attempts can pass integrity checks while remaining incomplete and having no verified outcome.

Optional planning runs use separate `inference_started(stage="planning")`, `model_plan` and `plan_status` events. The verifier checks the actual `task_choice` response, selected actor/save binding, request target and its observation boundary. Planning events must declare `executes_input=false`; they cannot appear in command dispatches or native-effect batches. A later unit request's persistent-plan context must match its prior active plan status, but its separate unit-action answer still selects the only command. Reports count planning and command responses separately, include both in model usage totals, and never list a valid plan as a missing game dispatch. Earlier traces without planning fields retain their original command semantics.

## Terminal review

The verifier never derives a win from turn count, research, a save, scores, a `session_stopped` status or a journal claim. To add a terminal review, first inspect the original result screen visually, retain its unmodified 640 × 480 PNG, and create a new JSON artifact inside the run:

```json
{
  "schema_version": 1,
  "game": "original-civilization-ii-1.06",
  "source": "original_game",
  "review_method": "human_visual_review",
  "reviewed": true,
  "journal_last_sha256": "THE FINAL JOURNAL HASH",
  "outcome": "victory_conquest",
  "screenshots": [
    {"path": "terminal-screen.png", "sha256": "THE IMAGE SHA256", "bytes": 12345}
  ]
}
```

These are placeholders, not a completed review. Supported outcomes are `victory_conquest`, `victory_space`, `defeat`, `retired` and `game_over`. Pass the actual relative file with `--terminal-review terminal-review.json`. The declaration must bind the final journal hash. One to eight images are accepted; each must decode as a nonblank original-resolution PNG with matching hash and size. Use `human_visual_review` only when a person inspected the screen. An assistant that visually inspected it must use `assistant_visual_review`; the report distinguishes `human_reviewed` from `assistant_reviewed`. The tool checks the declaration and image integrity; it does not recognize victory pixels or independently authenticate the declared reviewer. Neither method bypasses the other recording, input, or completeness checks.

## Limits and release use

The current recorder journal records counts and timings, **not hashes of the MP4, recording manifest or sample ledger**. The verifier computes and reports those hashes now but labels them as not anchored in the journal. Original dashboard PNG samples were streamed to the encoder and not retained, so their ledger hashes cannot be compared with original source pixels afterward. Encoded-video timing checks do not establish that every frame is visually correct.

A local hash chain is not server-signed proof that a remote model generated its contents, or that no input occurred outside the journal. The report states these limits and reports accepted-response token usage separately from recorded rejected-response usage. It does not silently turn calibration work, manual recovery or pending input into a successful autonomous game.

The artifact inventory is for local verification. Original saves, game data and private calibration images do not become authorized public assets merely because they pass checks. Prepare the eventual public bundle separately, with a source revision, reviewed result images, appropriate recordings, and only redistributable evidence.

Run `python3 -m unittest tests.test_verify -v`. Tests use generated classic-format **TEST** bytes, visibly labeled synthetic images and a short generated test video when ffmpeg/ffprobe are available; they are not game or victory evidence.
