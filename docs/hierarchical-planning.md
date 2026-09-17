# Optional task-category planning

Flat planning remains the default. Enable the optional protocol for a new
session with `planning=True, hierarchical_planning=True`, or call
`session.enable_hierarchical_planning()` at a paused boundary with no held
inputs and no commands awaiting observation. Enabling the protocol sends no
game input and preserves existing active plans.

The original candidate builder still offers at most 64 leaves, including Hold.
The category request partitions that exact set by task kind. It retains every
offered target, its unchanged original criterion, and the original omission
summary. Counts describe availability;
the harness does not sum probabilities, rank categories, or choose a target.

1. Jev answers the real `task_category` question. Its response is recorded as
   `model_plan_category`, with canonical stage `planning_category` and
   `executes_input: false`.
2. If the chosen category contains several targets, Jev answers a separate
   `task_choice` question containing every original leaf in that category. The
   request records the prior category decision, actor, and observation revision.
3. A category containing exactly one target fully states that target in its
   criterion. Its actual category response establishes the plan directly;
   there is no fabricated singleton request or second response. This includes
   Hold and any other category with one offered target.
4. A later independent unit-action response selects each native command. A
   plan, including Hold, never dispatches a command or establishes an effect.

Target transport failures retain the selected category for a fresh target
inference on the same observation. They use the ordinary `inference_failed` record, with unavailable
usage. A changed actor or observation requires an explicit
`planning_category_invalidated` record before a new category choice. An
unchanged category cannot be discarded for another choice. The ordinary runner
may obtain a new checkpoint before retrying; its new revision invalidates the
prior category explicitly even when observed gameplay facts look unchanged.

The verifier checks the category partition, source-bound actor and leaves,
original response probabilities, complete target-choice membership and labels, and exact
prior decision and revision. An unfinished category blocks gameplay commands
and release readiness; separately verified pointer parking remains allowed.
Sole-target category responses count once in response and token
totals, even though they also establish a concrete plan. Category and target
choices never enter command-effect batches.

For dashboards already running in an unchanged game page, only published HUD
copies translate `planning_category` to `stage: planning` with
`planning_phase: category`. The canonical Session decision and journal retain
`planning_category`; vectors and input authority are unchanged. This avoids
reloading the original-game iframe.
