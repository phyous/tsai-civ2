# Original city-unit activation

`--unit-activation` enables an additional Jev choice after a fresh city review.
A running Python session can call `session.enable_unit_activation()` while the
game is paused with clear inputs and no unobserved pending commands. The journal
records the capability; only subsequent native checkpoints include the extra
owned-unit stack metadata. Historical observations keep their original format.

Jev first chooses **Review labor**, which closes, observes and reopens the city.
That same fresh review permits both labor choices and eligible stationed-unit
activation choices. The review itself does not move or activate a unit. If Jev
chooses a particular fortified unit, the harness uses the original Units Present
icon, observes its Unit Information popup, selects **Activate Unit and Close City
Screen**, verifies the selected radio from original pixels, and confirms it.
A native checkpoint then checks the actual unit order and selected-unit identity.
Jev makes a separate decision about any subsequent movement or other order.

The icon's unit identity comes from the original linked stack order, not sorted
unit IDs or a guessed icon. Only complete reciprocal chains of living owned
units on the same tile are exposed. The initial calibration supports the observed
single row of one to five units with its Units Present heading, non-veteran
fortified ground units, and an observed owned home city. Other layouts and unit
variants remain unavailable until separately calibrated. Omission does not mean
an action is illegal in Civilization II.

The evidence distinguishes selecting an intent, partial ordinary inputs,
completed confirmation, and an observed native result. An uncertain input stops
the continuation; it is not automatically replayed. The verifier rechecks the
original source images, popup resources, radio pixels, stack identity and native
before/after state. No unit, order, game-memory or save-file writes are used.
