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
