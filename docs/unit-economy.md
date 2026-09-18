# Selected-unit disband and home-city orders

The ordinary unit question retains its existing alternatives and additionally
offers two native economic commands when the current observation establishes
their preconditions. Neither is chosen by the controller or by a planning vector.

* **Review disbanding** sends only original **Shift+D** for a unique, living,
  selected owned unit. The complete native `DISBAND` warning names that unit's
  type and offers **No** and **Yes**. A separate genuine Jev response chooses
  one of those observed alternatives. There is no default or mechanical Yes.
* **Set home city** sends original **H** only when the unit occupies exactly one
  owned city, has a different known owned home city, and is not an original
  trade-role unit. The command requests support transfer; later native state
  determines what happened.

Both commands bind the current actor's native slot, owner, type, position,
movement, order and observation revision. Unknown/dead health, duplicate city
identity, a foreign or missing home, and Caravan/Freight rehoming are excluded.
Every other offered unit action remains available. Current home and destination
budgets and supported-unit counts are supplied as facts, without declaring any
garrison adequate or forcing an economic choice.

The disband warning retains a pending context derived only after the actual
Shift+D dispatch. It must match the still-pending actor and native revision.
Another command, a different supported modal or a new checkpoint invalidates
that context. The verifier reconstructs it from the recorded model response,
exact modifier/key receipts and original standard unit facts, and separately
verifies the warning response and click. The existing event schemas are used;
no model vector or input receipt is synthesized.

Original sources are `MENU.TXT` Orders (`Disband|Shift+D`, `Set Home City|h`),
`GAME.TXT` `DISBAND`, `SETHOMECITY` and `CARAVANHOME`, and the
[original manual](https://archive.org/details/civ2_manual), printed pages 15 and
59. The manual says disbanding within a city adds half the unit's production
cost to its current project. H transfers which city supports the unit. Actual
paid support depends on each city's government allowance and supported roster.
Neither ordinary movement nor fortification changes a home city.

An isolated operator calibration under `.runtime/operator-unit-calibration`
used an unmodified debug save. H moved Warrior 39's home from 6 to 16 with its
other unit fields and city project shields unchanged. Shift+D followed by No
left the saved native bytes identical. A separate Shift+D followed by Yes
reduced the unit count from 47 to 46 and increased the occupied city's shields
from 5 to 10. Original unit slots compacted and next-unit scheduling changed
selection, so no persistent identity or successful disband is inferred from a
missing slot number. These were explicitly operator-selected calibration inputs,
not model decisions or inputs in a recorded no-save campaign.

Guide v8 explains the alternatives and their opportunity costs. Confirmation
can remove defense or martial law; a home transfer may improve one city's
support budget while burdening another. Actual model requests retain all choices
and the recorded native state remains the source of outcome evidence.
