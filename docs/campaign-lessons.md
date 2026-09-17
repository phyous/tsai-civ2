# Campaign lessons

No complete-game victory has been verified yet. These are development findings,
not claims that the model has beaten Civilization II.

## Runtime and evidence

Attempt 008 used the first modern backend before its host scheduler correction.
Its paused canvas sometimes changed between inference and dispatch. The source
image guard refused those commands before input; the unused choices remain in
the journal. The attempt stopped at 78 model responses and turn 44. Its original
game is preserved paused, and its recording was finalized without a victory.

An earlier failed pointer park in that attempt also omitted five input-sequence
values from its receipt. The available evidence cannot independently account for
those motions. The verifier rejects that incomplete history; it has not been
rewritten or presented as a clean recording. Subsequent cursor failures retain
partial motion receipts, runtime sequence bounds and original failure images.

Fresh runtimes load the hash-bound host scheduler correction described in
[modern runtime notes](../engine/modern-runtime.md). Original game and Windows
bytes remain unchanged. Attempts 008 and 009 disabled autosave before model play
and used read-only observations rather than between-turn game saves.

## Production and support

The early prompt encouraged useful waiting but did not explain clearly enough
that completed unit production repeats. Both early modern campaigns accumulated
Warriors in their capital. Revision v4 explains repeat production and exposes
the absence of any worker or worker build. Both campaigns subsequently chose
to inspect Rome and switch production to Settlers through separate Jev choices.

Attempt 009 then lost a Settler to support costs. Before completion, Rome had
population three, four gross shields and four home Warriors. After completion,
population fell to two, gross shields to two, and five units needed home-city
support. Under Despotism, the three-shield support cost exceeded that output.
Moving the Settler away did not transfer its support burden to another city.

Revision v5 distinguishes home-city support from physical garrison location,
describes population and support changes on worker completion, and exposes
conservative current support arithmetic. It does not forecast unobserved future
tile yields or force a production, labor, government or unit choice. The guides
and their limitations are documented in [strategy sources](strategy-sources.md).

## First completed loss

Attempt 009 ended in defeat after 96 model responses. The original game displayed
the message about archeologists discovering the remains of the civilization.
Its full recording and terminal screenshot are retained. American Horsemen had
attacked Rome; the earlier production and support problems left this campaign
with one city. This is a confirmed loss, not a successful full-game run.

A read during combat also contained a zero-HP owned unit and a selected enemy
unit while the status panel still said End of Turn. That intermediate state
cannot establish final casualties or show that the following command caused the
loss. Turn-resolution handling needs to distinguish an unfinished battle from a
new opportunity for the player to act.

## Current campaign and remaining evidence limitation

Attempt 010 began with strategy guide v5 and reached two cities by turn nine.
Autosave was disabled before model play; observations do not save the game.
There is no verified victory yet.

Decision 37 encountered a cursor-positioning failure before a mouse-button
press. Its partial motion receipts were lost. The journal explicitly records
that gap; the verifier reports incomplete input coverage and does not certify
it as a fully audited release. Decision 38 encountered another positioning
failure, but its three actual relative motions were retained and recorded as
an interrupted command. Neither failed attempt is reported as an executed city
command. The campaign continues with this limitation disclosed.

Edge-directed movement now uses smaller steps to accommodate the original
mouse acceleration. Text recognition can reuse analysis of an identical PNG,
but the harness still captures the current screen and checks its full hash
before using that analysis. Neither change supplies a strategic game action.
