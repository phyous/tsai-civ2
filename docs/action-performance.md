# Action timing

Timing must distinguish model latency, observation, ordinary input, native
painting, and pauses to add support for an unfamiliar original screen.

September 16, 2026 development measurements:

| Operation | Observed duration | Scope |
| --- | ---: | --- |
| Jev inference | about 0.28–0.30 s | Actual recent calls, not an API guarantee |
| Native debug save | about 3.72 s | Original Save dialog and file read |
| Live memory observation | 1.3–1.6 s | Successful first-attempt paired observations |
| Cross-screen pointer movement | about 1 s | Eight observed steps in each direction |

The live reader no longer retries just because the original cursor animation
changes pixels. It retains all three actual images and their hashes, explicitly
reports whether they match, and still requires matching native state, window
topology, unchanged ordinary-input sequence, and an unchanged save inventory.
The model display has no artificial hold after a response: its real vectors
remain visible while the selected action executes.

Attempt 007's first 50 responses took 385 seconds of recorded elapsed time.
Eight city inspection transactions used 231 seconds (60% of that interval).
Six labor preparation cycles used 76 seconds, although no labor change was
selected. These are overlapping categories, not additive timings. The campaign
also exposed misread city dates that incorrectly entered the newly founded city
path. Thus faster inference alone would not address the main delay.

The strategy prompt now explicitly explains that a useful build already in
progress needs turns to accumulate shields, and that current city facts are
already supplied. Jev retains the choice to inspect and change production.
Labor preparation now requires Jev's explicit “Review labor” choice. Exit,
production review and purchase review avoid its close/read/reopen cycle.
That preparation clicks the actual observed Exit, refreshes state, reopens the
same city, and then asks Jev to choose any actual labor reassignment separately.
Do not present menu visits or an unchanged production selection as progress,
and do not infer a total-game speedup before measuring actual play.

September 17 isolated follow-up: a 300.5-second pause on the old engine did
not reproduce the slowdown (five baseline reads median 1.40 s, ten resumed
reads median 1.46 s). The slow campaign also had a successful 1.87 s read after
its long pause, before the later slowdown. Long pauses alone are therefore not
a supported explanation.

An isolated modern DOSBox WebAssembly prototype loaded the identical original
debug save through the game's Load dialog. Ten complete observer envelopes
passed checksums, region bounds and native window checks; paired regions agreed
and their public projection matched the original save. Individual reads had a
295 ms median, with paired reads about 0.54–0.66 s. This is an observation
benchmark, not yet a measured full-campaign speedup. The modern backend remains
optional while input handling and browser integration are validated.

A later recorded map stall had identical pixels everywhere except the original
blinking “End of Turn / (Press ENTER)” footer. The map fallback now accepts
this specific presentation change only when both complete footer crops equal
the pinned white/gray members of the same original calibration and every pixel
outside that crop is identical. It retains and recognizes the actual current
PNG, checks that the emulator remains paused at the same input sequence, and
checks the current PNG again after recognition. The independent verifier repeats
the pixel comparison from both retained images. Unknown footer layouts, changed
map artwork, other status changes and dialog changes still fail this proof.
This removes that measured false rejection; it does not establish a whole-game
speedup or authorize an end-turn command.

A later read-only sample covered 100 actual responses from each of attempts
012 (decisions 387–486) and 011 (500–599), including task categories and targets.
API latency totaled 48.5 and 46.8 seconds, with medians of 0.438 and 0.416 seconds.
The corresponding journal windows lasted 1,615 and 3,501 seconds, including
development pauses. Inter-event gaps longer than 30 seconds accounted for
1,093 and 2,962 seconds; those gaps are not attributed to inference. There were
64 and 66 failed map-proof attempts, largely preceding the footer repair above,
and no city-inspection/navigation decisions in either sample. Repeated city
visits were therefore not the current bottleneck.

One small classifier cost was independently measurable without touching the
game: `classify_dialog` reparsed the same supplied GAME catalog up to 14 times
on the retained original `NOSPACESHIPS` notice. It now parses lazily once per
classification. The public parser still returns fresh records, and no catalog
is cached across calls or source changes. In 50 offline calls on that notice,
median classification time decreased from 34.4 to 5.1 milliseconds. This is a
single-frame classifier benchmark, excluding OCR, input, painting, recording
and model time; it is not a measured campaign speedup. Tests retain the existing
map, strategic-choice and information semantics, verify that helpers leave the
catalog unchanged, and check source-change isolation and branches needing no
catalog.

The timing review made no campaign inputs or saves. All 155 successful native
read receipts in those two windows retained identical before/after campaign
save inventories. Both active video ledgers began at time zero, had contiguous
samples and monotonic frame numbers, no sample gap over one second, and empty
encoder logs when checked. They were still recording, so this is not final
video verification. Faster processing must preserve continuous real-time
recording, every actual model choice, all ordinary-input receipts, and the
no-saves-during-playthrough boundary.

Retained native-map images now use the same bounded OCR cache as ordinary UI
captures. The key includes the complete PNG SHA-256, recognizer identity and
OCR executable metadata. A cache hit returns a deep copy with the current
artifact path; it does not reuse a native snapshot, actor binding, classification,
input receipt or old capture. All original before/after status and image checks
remain in place. Failed OCR analyses are not cached.

A read-only sample of 100 successful responses from each of attempts 010–012
found 67 native-map middle images identical to their already-recognized trigger.
Six offline image measurements took 239–696 ms for cold OCR and 51–55 ms for
cached analysis. These are component measurements, not a claimed end-to-end
speedup; development pauses and newly encountered dialogs still dominate.

Large repeated arrays, especially city labor radii, can also use lossless column
matrices. Each column is either a full vector or an explicit default with indexed
exceptions. The submitted prompt explains the format; decoding preserves every
value, type, null, row order and choice. It is selected only when the complete
state including those instructions becomes at least 1% smaller. Both older
record-table formats remain readable.

An offline roundtrip check of 90 retained successful requests (30 per campaign)
preserved every question and decoded state exactly. Median JSON character savings
were 6.26%, 4.42% and 4.28% for attempts 010–012 respectively; encoding took a
median 7.6–9.1 ms. These are character and local processing measurements, not
measured API-token savings or an end-to-end speedup.
