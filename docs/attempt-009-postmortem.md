# Attempt 009: confirmed defeat

The original game displayed “Centuries later, archeologists discover the remains
of your ancient civilization.” Two agents independently inspected the original
640×480 frame. The campaign recording was then finalized without another game
input. This is a loss; it supplies no evidence of a complete-game win.

## Retained evidence

The ignored run directory is `runs/attempt-009/`. Its `terminal-review.json`
binds the final journal and `screens/ui-0000601.png` (SHA256
`83dc5a16405cc41ee2a98e1481f2c9f76f30a3f0c63724ed201a6db29881631d`).
The full `verification.json` reports:

| Evidence | Result |
| --- | --- |
| Jev responses | 96: 89 command decisions and 7 planning decisions |
| Command dispatches | 89; no forced strategic commands or manual selection recoveries |
| Model | `jev-1.13.0` |
| Tokens | 1,246,807 input; 13,537 output; no rejected responses |
| Native observations | 74 successful checkpoints; last artifact ordinal 75 |
| Video | 1920×1080, 4 fps, 13,150 frames, 3,287.5 seconds; ffprobe passed |
| Save policy | Autosave disabled before model play; no between-turn game saves |

The recording includes development pauses and source reloads. One failed
observer read consumed a checkpoint number in the earlier Session code without
creating a checkpoint event. Verification now distinguishes artifact ordinals
from successful observation counts; no historical files or journal entries
were renumbered. Future failed reads do not consume the successful counter.

The recorder journal anchors frame counts, not the video file hash. The audit
computes the retained MP4 hash; streamed dashboard PNGs were not individually
retained. A local hash chain is not independent authentication of every input.

## Economy and decisions

The initial owned roster contained one Settler. Jev founded Rome, selected
Warriors, and fortified each of the four completed Warriors. Their planning
choices selected defending Rome over offered survey targets. Unit production
repeated until decision 39, when Jev selected a city inspection with probability
0.75; a separate production choice changed the build to Settlers.

At turn 40 / 2050 BC, Rome was size 2 with six gross food, two gross shields,
one science and zero treasury. It supported four Warriors and a newly completed
Settler. The native support notice explicitly reported that Rome could not
support Settlers and the unit was disbanded. The original manual's Despotism
support rule explains the observed shortage: five home units minus the size-2
free allowance required three shields. Moving the Settler away did not change
its home city. The current guide's support arithmetic and population-change
advice were added after this failure.

By turn 62 / 975 BC, the campaign still had only Rome, four Warriors and no
worker. Rome was size 3, producing another Settler, with four gross shields,
one science and zero treasury. The known advances were Alphabet, Bronze
Working, Code of Laws, Currency, Trade and Writing; Ceremonial Burial was being
researched. Monarchy was not yet an available government. Guide v5 was adopted
at this late boundary; it was not used from the beginning of attempt 009.

Jev declined the observed American emissary at decision 87 (0.61). This was a
real choice between granting an audience and sending him away. The evidence
does not establish that accepting an audience would have prevented war.

The second Settler completed, reducing Rome to size 2. Jev chose to survey east
and moved the Settler onto the adjacent known Jungle. At decision 91, a visible
American Horsemen entry stood one square north of Rome, with 10 HP and original
base attack 2 / defense 1. Jev inspected the city, then chose Phalanx at decision
93 (0.29, ahead of Warriors at 0.26). This changed production only: the next
checkpoint showed zero stored shields and no completed Phalanx. Current home
support still exceeded the recorded gross shields.

## Observed attack and the readiness bug

Decision 95 issued Finish Turn from native turn 63 / 950 BC. The original
Defense Minister then announced a sneak attack by American forces. After its
acknowledgement, another read still reported turn 63 and the status text still
said End of Turn, but the underlying records had changed:

| Observable field | Before the attack notice | Later same-turn read |
| --- | --- | --- |
| Rome size | 2 | 1 |
| Warriors records at Rome | Four at 10 HP each | Two at 10 HP and one at 0 HP |
| Visible American Horsemen entry north of Rome | 10 HP, non-veteran | 7 HP, veteran |
| Selected unit | No owned unit selected | Native selection identified the visible enemy entry |

Unit IDs compact when records are removed, so these are roster observations,
not a claim that a particular persistent unit died. The zero-HP record and
enemy selection indicate an intermediate combat observation. They do not
establish final casualties or a completed player-turn boundary. The garrison
summary also counted that zero-HP record as armed, which overstated living
defenders in that intermediate request.

The runner subsequently allowed another Finish Turn, decision 96, from the
same source turn. The later defeat screen is conclusive; the evidence does not
show that this extra command caused the defeat. The readiness fix retains a
pending Finish Turn across intervening dialogs, lets the game resolve with no
additional map input, and requires a later native turn plus a freshly supported
map before another ordinary map decision. Modal decisions remain genuine Jev
choices. A bounded unresolved wait pauses rather than sending Enter again.

## Strategic follow-up

Two improvements are supported by this attempt, without prescribing the model's
next move:

1. Keep sustainable expansion visible in planning and production requests.
   Repeated garrison production delayed the first worker until turn 40, and its
   support loss delayed any second settlement further. The v5 guide and current
   home-support facts address the missing explanation; native labor, production
   and government choices remain separate decisions. Merely changing the next
   build does not repair an existing support deficit.
2. Make existing military units available for reconsideration. Fortified
   Warriors were not offered as actors by the earlier action path, so the model
   could not choose to reactivate and redirect them for scouting or other roles.
   A calibrated, independently selected activation path restores that option;
   it must not automatically move, attack, disband or declare a garrison safe.

Original support and combat rules are documented in the
[Civilization II manual](https://archive.org/details/civ2_manual); offered base
unit statistics come from the unchanged original `RULES.TXT`. Neither a larger
army, earlier settlement, different research nor accepting diplomacy is claimed
to guarantee a win.
