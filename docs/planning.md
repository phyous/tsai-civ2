# Observed-target planning

`civ2.planning` proposes tasks; it never executes inputs or chooses paths. It is
not wired into the runner yet. The existing unit-action policy remains unchanged.

Use `request_for(state, rules, recent_actions=None, limit=64)` to obtain a Jev
request and canonical candidates. The sole `task_choice` selects a task and
target. Pass that actual selected candidate to
`make_plan(candidate, state, rules, limit=64, max_turns=8)`, then include the active
plan in a **later** unit-action request. Every movement, construction, combat,
wait and replanning decision still needs an actual model choice. Do not multiply
planning and action probabilities or present either as a win prediction.

Candidates cover known frontiers, observed Plains/Grassland settlement proposals,
rule-compatible roads/irrigation/mines, friendly-city defense for military land
units, currently visible units belonging to declared enemies or barbarians, and
Hold for one turn. Original-game legality and reachability remain authoritative;
these are known-compatible proposals, not guaranteed legal or safe destinations.
City-center improvements are omitted. No unknown terrain, foreign orders or
private rival state is used.

`task_candidates(state, rules, limit)` returns `(candidates, summary)`. The limit
is 2–255. Hold is reserved; other categories rotate, each ordered by geometric
distance and coordinates/ID. The summary reports omitted counts by task. This
bounded, local ordering can omit worthwhile distant targets; it is not an
optimal-site ranking or a complete map search. A singleton never gets a fake
Choice distribution.

After each fresh native checkpoint, call
`advance_plan(plan, before, after, action=None, rules=None)`. Supply the exact
canonical unit action when this actor moved; unexpected movement invalidates.
The tracker accepts only one matching observed actor, and conservatively
invalidates on removed roster slots/possible ID compaction. It does not remap
unit IDs. New slots may be added, but an indistinguishable stacked actor causes
invalidation. Save observations cannot prove the absence of an otherwise
indistinguishable death/replacement; plans provide context, never input binding.
The ordinary action still binds the fresh save and selected actor independently.

Completion means an observed result: a new owned city at the target, a reported
improvement, newly observed terrain beside a frontier, or an elapsed one-turn
hold. Arrival alone does not found a city. Defender tasks persist until review;
an enemy leaving visibility invalidates its target without implying destruction.
Plans expire after the configured 1–20-turn interval (default 8) or 32 checkpoint
observations. Expiration requests another model plan and never selects an order.

Record the planning request/response, selected candidate, creation checkpoint,
and subsequent status changes. No live model/game run has validated this module's
strategic effectiveness; its tests are offline contract and continuity checks.
