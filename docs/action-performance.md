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
