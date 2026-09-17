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

## Campaign-controller calibration

Attempt 001 began from the verified untouched start and records its development
pauses continuously. Jev founded Rome, selected Settlers in its actual production
menu, and skipped the remaining starting Settler's movement. A native save
confirmed Rome and the compacted unit roster. Jev selected Alphabet in the first research menu; a mouse failure before
button-down required a separately recorded, visually verified keyboard recovery.
The final native checkpoint is turn 2, 3950 BC, one city, Alphabet research.
The finalized 27:59 calibration video and ledger pass integrity checks, with
three automatic dispatches and one explicit recovery. No full-game outcome
exists yet.

The first city exposed several controller defects: an intermediate map repaint
preceded the city window; native bitmap OCR missed short OK controls and read
selected labels incorrectly; and mouse positioning stalled near the bottom edge.
The controller now waits for city transitions, uses separate OCR analysis copies
with original-coordinate provenance, preserves menu transactions across pauses,
and binds production reviews to each city's observed name and year. The original
Escape shortcut successfully closes the city screen. The boundary came from DOSBox choosing its unlocked absolute-motion path even
when SDL supplied relative deltas. The corrected export calls the original
DOSBox relative input handler; a fresh live menu selection reached pixel
(512,378) exactly in eight feedback steps. These are harness calibrations, not
model losses.

## Parallel controller experiments

Attempts 002 and 003 start from the same verified map and settings in separate
local browser runtimes. Attempt 002 uses immediate action choices; attempt 003
adds independent Jev-selected persistent objectives. Both retain continuous
recordings, including controller-development pauses. These are now finalized harness-development attempts,
not completed victories or defeats. Attempt 002 stopped on turn 10 after 25
model calls; its last research choice failed before button-down. Attempt 003
reached two cities, Rome and Veii, with a turn-5 native checkpoint and 19 calls
(5 plans and 14 commands). Their full recordings retain the development pauses.

The baseline repeatedly skipped its second starting Settler through turn 10.
In the planned run, Jev chose a frontier target and moved north, then proposed
a new city adjacent to Rome. The original game rejected that order with
“Cities cannot be built in adjacent squares.” The candidate builder had omitted
this rule. Both planning and immediate settlement choices now exclude squares
adjacent to observed cities, including across the world seam. The rejected call
and its native notice remain in the evidence; it is not counted as a founded city.

Other observed fixes include the original End of Turn cue's blinking white/gray
text, research-heading bitmap-font OCR, and city-locator text under the pointer.
Varied repaint waits avoid sampling the same unreadable blink phase and issue
no game input. Planning choices and dispatched commands have separate evidence
and HUD labels. A responsive read-only live theater at `/web/watch.html` displays
the recorder's complete composition without opening another emulator.

## Native city controls and runtime performance

City reviews now let Jev open production, request a purchase quote, or exit.
Opening Buy never authorizes spending: the original COMPLETE1 price and treasury
are supplied to a separate Jev choice between Complete it and Never mind. A
calibration with 9 gold verified a 2-gold Warrior quote, declined it, and restored
the previous Settlers production with identical parsed gameplay fields. An
unaffordable 110-gold quote had only its original acknowledgment button.

A separate labor calibration verified all 20 mutable Resource Map positions
through native clicks and original saves, then restored the baseline gameplay
state. City reviews now expose worker-to-entertainer and entertainer-to-tile
choices. Every reassignment is selected by Jev and checked against a fresh
native save before another city decision. Center-tile labor and specialist-type
cycling are not exposed. See [the calibration and transaction rules](labor-controls.md).

The automatic Civilopedia page after a discovery exposed slow emulator callbacks
in the embedded browser. Five-sample measurements in a dedicated local headless
Chrome process gave median running captures of 5.97 ms on the map and 14.96 ms
on the original Civilopedia, versus multi-second calls in the previous runtime.
The game and emulator source were unchanged. This deployment disables background
page throttling; the experiment does not isolate which browser difference caused
the improvement. A separate original Graphics Options calibration disabled only
“Civilopedia for Advances,” leaving all gameplay fields and the other five
graphics settings unchanged. The runner now applies that presentation setting
once at a verified map boundary.

The OCR adapter now keeps a private Vision worker process. Complete retained-frame
observations matched the one-shot adapter exactly; measured reading times fell
from 584–908 ms to 215–311 ms. No recognized text or image result is cached.
See [the measurements and fallback behavior](ocr-performance.md).

The council panel uses otherwise spare space for three clearly labeled previous
model evaluations. Current choices always take priority, and every probability
comes from a retained Jev response. Planning and command probabilities remain
separate.

## Parallel campaigns and strategic context

Attempts 004, 005 and 006 use separate emulator instances, native starting saves,
browser profiles, decision ledgers and continuous recordings. Each has founded
Rome, Veii and Antium in the original game. None has reached a verified victory.

The early campaigns exposed a context gap: production choices named units that
were not yet owned, but the compact statistics table described only owned unit
types. Actual production options now include their exact original rules
specifications. Current city garrisons, worker production and available government
concepts are summarized together. These facts guide Jev without selecting its
commands. See [the strategic context changes](strategy-context.md).

Source-matched original public notices are retained in a bounded recent-event
memory and included in subsequent Jev requests. Their exact observed text,
original screenshot hash, resource hash and last-checkpoint reference are logged.
An old destruction notice does not establish present ownership or the current
number of surviving civilizations. Evidence verification checks the same retained
notice sequence against the actual model requests.

The native warning about completing Settlers in a size-one city now presents both
original alternatives to Jev: delay production or build anyway and disband the
city. It is a strategic decision, never an automatic acknowledgment. Cosmetic
throne-room handling and its separately recorded development inputs are described
in [the presentation record](throne-presentation.md).

## Evidence conventions

Attempt 007 started a fresh verified game with a read-only Win16 memory
observer. Native autosave was disabled before model play; its ledger retains
the original startup save inventory and rejects any subsequent save changes.
Initial paired observations took roughly 1.5 seconds. The campaign exposed
redundant city reviews, unconditional labor preparation, and a city-date OCR
error; these led to the [action timing changes](action-performance.md).

On turn 12, generic emulator operations became much slower. A later observation
on turn 13 took about 54 seconds. Interrupting the controller also interrupted
its encoder, so this attempt is now debugging evidence and cannot be presented
as a continuous final recording. Future encoders run in an independent process
session. The original game state was retained without a save or restart while
the host timing issue was investigated. None of these campaigns has yet
established victory.

Each model session retains original saves, original screenshots, requests,
validated responses, ordinary input receipts and a hash-linked event ledger.
The continuous recording contains only real captured dashboard frames; capture
gaps repeat the preceding frame. A batch save delta is not attributed to an
individual command without additional evidence. Hidden foreign game information
is excluded from model observations.

An end-game text cue is only a candidate for inspection. Completion requires
the original game's Roman victory, the requested settings, a full recording and
a reviewed evidence bundle.

## September 17 continuation

The paused debug campaigns resumed in their original runtimes and recordings.
Historian notices now retain only the ranks actually visible, and their full
original resource structure and sole acknowledgement are checked. Additional
pixel-based recovery covers city captions, footer text and save confirmations;
these fixes do not choose game strategy. Attempt 005 reached five cities and
Horseback Riding. It remains a debug campaign, not a completed game.

The optional modern DOSBox WebAssembly backend passed an isolated public-state
comparison against the identical original debug save and a five-minute paused
gap without slow recovery. Its relative mouse motion was measured against the
actual Windows cursor. Browser integration is being validated separately before
a fresh no-save campaign; this is not yet a full-playthrough speed measurement.

## Fresh modern campaigns

Attempts 010, 011 and 012 subsequently started independently verified original
games with the requested settings and native autosave disabled. They retain
continuous dashboard recordings and compare the native save inventory during
read-only observations. No between-turn save/load is used in these campaigns.
They remain unfinished; the repository does not claim a victory.

Attempt 010 reached five cities and Monarchy. Its expanding planning request
received an explicit `max_tokens_exceeded` API error; this is a harness context
limit, not a lost battle. Attempt 011 discovered Monarchy, began the original
revolution, and selected peace with Spain in its native diplomacy dialog.
Attempt 012 reached a second city after recovering a split production caption.
These are intermediate observations, not forecasts of success.

Two input-evidence limitations are retained explicitly: 010 lost some cursor
approach receipts, and 012 lost an informational acknowledgement receipt when
the following OCR pass failed. Actual surrounding screenshots and observed input
sequence bounds remain available. The verifier marks their input coverage
incomplete; it does not reconstruct missing inputs or certify those runs as
complete release evidence. Post-input OCR failures now retain the captured
image so actual returned input receipts can still be logged.

## Continued campaign debugging

Attempt 012 reached four cities and Monarchy by the ancient era. Its production
caption and status dates required additional paired reads of the original
pixels. These reads preserve raw OCR provenance and do not insert native-state
values into the screenshot text. Narrow repairs also cover original treaty
warnings, withdrawal notices, greetings and map labels.

Attempt 011 repeatedly attempted the same move without a change in its observed
position, movement spent or order. The next requests now summarize such
individually bound, consecutive failures explicitly, while retaining every
command. Jev then skipped, advanced the turn and later chose another direction.
Subsequent diplomacy included a real choice to withdraw troops and an original
notice confirming withdrawal. The earlier unchanged attempts alone did not
establish their cause or illegality.

API failures now have bounded status/category records and unavailable usage,
without invented token counts or remote error text. Historical known failures
can be declared late without rewriting their original requests. These changes
improve accounting; they do not repair previously missing input receipts or
constitute a completed victory.
