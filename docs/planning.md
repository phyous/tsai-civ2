# Observed-target planning

`Session(planning=True)` enables an experimental, persistent task choice before
the ordinary unit-action choice. Planning proposes a task and observed target;
it executes no input and supplies no path. `planning=False` is the default and
retains the baseline policy.

| Behavior | Baseline | Planning enabled |
| --- | --- | --- |
| Selected unit | Jev chooses one current legal command | Jev first chooses a task if the unit has no active plan, then independently chooses one current legal command |
| Later observations | Recent orders and fresh player-observable state | The same observations, plus that unit's active Jev-selected task |
| Command candidates | Existing canonical unit actions | The same canonical unit actions; the plan does not force a direction or filter alternatives |
| Task review | No persistent task | Observed completion, invalidation or bounded expiry; a new task is requested when that unit is next selected |
| Evidence | Command choices and input receipts | Separate planning choices/status events, plus unchanged command choices and input receipts |

`python -m civ2.run` uses the baseline by default. Add `--planning` to enable
observed-target planning and `--port 3921` for a separately prepared runtime.
Once that runtime has loaded the matching original initial save, use:

```sh
python3 -m civ2.run --planning --port 3921 \
  --initial-save .runtime/setup/initial.sav --directory runs/planning-attempt \
  --env-file /path/to/private/env
```

The same options are available through Python:

```python
from civ2.engine import Game
from civ2.run import run_steps
from civ2.session import Session

session = Session(
    "runs/planning-attempt", ".runtime/setup/initial.sav",
    game=Game(port=3921),  # A separately prepared runtime for this attempt.
    env_file="/path/to/private/env", planning=True,
)
outcome = None
try:
    outcome = run_steps(session, max_decisions=10000)
finally:
    session.finish(reason=(outcome or {}).get("reason", "Controller stopped; inspect evidence."))
```

Use separate runtime ports and evidence directories for parallel attempts. A
comparison should record the original initial-save hash, settings, model and
budgets; matching settings alone do not establish identical starting worlds.
No complete-game win or strategic advantage from planning has been verified.

## Decision and evidence contract

The session stores each planning request and raw response under a unique
decision ID, records `model_plan`, then records `plan_status` at creation and
subsequent native checkpoints. Planning IDs never enter pending command/effect
batches. The later `unit_action` request receives `state.persistent_plan` and
independently binds its chosen command to the fresh save and selected actor.
It may detour, wait or choose another legal action. Even a Hold task does not
automatically dispatch Skip.

The dashboard displays the real `task_choice` vector as an objective choice,
with `stage="planning"`, `executes_input=false` and no command receipt. The next
action has its own real distribution. Do not multiply these independent stage
probabilities or present either as a win prediction. `Session.ledger()` and the
stopped-session event distinguish started model calls, returned planning
decisions, returned command decisions and active plans.

Every unit order remains independently model-selected. Saving, opening already
selected native menus and acknowledging verified informational dialogs retain
their explicit mechanical handlers; a plan authorizes none of these inputs.

## Pure planning helpers

Use `request_for(state, rules, recent_actions=None, limit=64)` to obtain a Jev
request and canonical candidates. The sole `task_choice` selects a task and
target. Pass that actual selected candidate to
`make_plan(candidate, state, rules, limit=64, max_turns=8)`, then include the active
plan in a **later** unit-action request. The session performs this integration;
the helpers themselves do not call Jev or the game.

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
Plans expire after the helper's configured 1–20-turn interval (default 8) or 32
checkpoint observations. The session uses these defaults. Expiration never
selects an order; the next selection of that unit permits a new Jev task choice.

## Long-game limits

- The 32-observation bound counts every native checkpoint, including other
  units' orders and empire menu reviews. A large empire can therefore review
  tasks before eight turns elapse. Each newly selected task adds a model call.
- A removed roster slot can mean ID compaction, so it invalidates other active
  plans conservatively. Identical stacked actors, unexplained movement and
  changed actor fingerprints also cause review rather than guessed identity.
- Task targets are capped at 64 in the session and ordered locally. Reachable
  distant goals may be omitted, while included goals may have no useful route.
  There is no route solver or automatic progress toward the target.
- Plans are per unit. The action request includes that unit's task, not a shared
  assignment ledger for every other unit. Multiple Settlers can choose competing
  sites, and all ordinary action alternatives remain available.
- `run_steps(max_decisions=...)` counts both stages, not executed orders. Its
  outer-loop check can be crossed by one command decision after a planning
  decision. The separate API request cap still applies. Compare command counts
  and token usage as well as total model calls.
- Plans persist within the live `Session` and are recorded for audit; no automatic
  plan restoration after a process restart is implemented.

Tests cover offline choice contracts, stage accounting and conservative
continuity. They do not establish that the resulting strategy can win.
