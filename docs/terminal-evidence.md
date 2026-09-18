# Terminal evidence and final recording

A full win requires the original game's result for the recorded player, plus
an intact recording and input/model audit. A score, launch, arriving ship,
surviving-civilization mask, or `release_review_ready` flag alone is insufficient.
The latter also permits a completely reviewed defeat or retirement artifact;
check `outcome.outcome` explicitly for `victory_conquest` or `victory_space`.

The original manual, “The Space Race” (page 131) and “Conquering the World”
(page 135), distinguishes first successful Alpha Centauri colonization from
control of the only settled civilization. It warns that eliminated cultures
may restart. Barbarians are not ordinary rival civilizations. Do not infer a
win by counting remembered rivals, excluding an unseen city, or assuming that
one destroyed-civilization notice ended the game.

For conquest, visually retain the original `SLAM` result, “Your civilization
has conquered the entire planet!” (GAME.TXT lines 3869–3870), and bind “your”
to the same uninterrupted recorded Roman player and initial setup. The original
result is the authority; a private reconstruction of enemy holdings is not.
Preserve any adjoining player/leader and final result screens that resolve
identity. Do not dismiss the result before capturing it.

For space victory, `EAGLEHASLANDED` (3323–3326) names an arriving civilization,
but by itself does not prove the player won. Retain the named colonists/leader
and the winning `CENTAURI3` narrative (4376–4378): “your people have fulfilled
the dream of countless generations” and “Your name will live forever in the
annals of CIVILIZATION!” The rival-winning sequence uses `CENTAURI_BEATEN3/4`
(4400–4410), which says the player has a long history and “Perhaps one day”
will also be recorded. Those are different outcomes. Generic introductory
space scenes and an estimated arrival date do not establish first colonization.

`DORETIRE` (3864–3867) announces the end of the dynasty, while `KEEPPLAYING`
(3872–3880) offers continuing after final scoring. Neither establishes conquest
or space victory. `PLANRETIRE` is only a warning twenty years ahead. The original
F9 score display is also available during play, so a high score screen alone
is not evidence of a terminal win.

The current runner stops without any further key, mouse click, model choice,
or automatic acknowledgement on a conquest/winning-narrative candidate or
Game Over. Arrival, retirement and unsupported score/presentation layouts fail
closed and retain their original screenshot. These cues are not automated
outcome verification. Space arrival may therefore stop before the later winning
narrative; its subsequent original presentation must be inspected and its
non-strategic continuation separately supported before proceeding. This audit
has not exercised a complete original victory sequence.

## Preserving the final recorded state

`Recorder.stop()` now waits for the existing recording thread to sample a newly
captured, exact current dashboard. Original 640×480 game captures and unchanged
paused input status bracket this operation. The sample must be newer than the
final-capture request, its hash must equal the retained dashboard PNG, and its
full encoded frame interval must elapse in real time. The original game is
checked again after the thread and encoder finish. Only dedicated game and
harness-dashboard endpoints are read; no desktop or credentials are captured.

The original game PNG and dashboard PNG are retained under `video/`, with their
hashes, byte counts and matching sample/frame/time in the manifest and
`recording_finalized` event. The verifier independently decodes the PNGs and
checks the dashboard hash and timing against the actual sample ledger. This
anchors those final images, not every streamed video frame; the existing MP4
and complete-sample integrity limitations remain. A synthetic ffmpeg drill
checks that the encoded ending contains the changed final frame, without
restarting the recording thread or fabricating source pixels.

If the current frame cannot be matched, input is held, the original game
changes, or capture fails, no successful final proof is returned. A failure
before the stop signal leaves the recorder running. `Session.finish()` does
not append `session_stopped` or close its journal before recorder finalization
succeeds. Later encoder/capture failures remain failures, with partial artifacts
available for inspection. No terminal outcome is inferred from preservation.

This stop path also works for an existing thread executing the older capture
loop. At a safe boundary, reload `recording_final`, `recording` and `session`,
then adopt the new Recorder and Session classes on the existing objects; keep
the same thread, encoder, game, journal and recording. Do not restart a campaign
or recording to adopt this change.

After finalization, visually inspect the retained original result and the
recording's start, ending and continuity. Create the explicit terminal review
only then, bound to the final journal hash, using `assistant_visual_review` for
an assistant inspection or `human_visual_review` for a person's inspection.
The independent verifier checks declaration/image integrity and distinguishes
the outcomes; it does not authenticate the reviewer or recognize winner pixels.
See [evidence-verification.md](evidence-verification.md) for the review schema
and release limitations. No campaign inputs or victory claims were made to
implement these preservation checks.
