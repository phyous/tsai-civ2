# Cosmetic throne-room presentation

The original Civilization II manual, **Throne Room**, explicitly says additions
may be ignored “with no repercussions” and that disabling **Throne Room** in
Graphics Options hides them. It separately describes clicking the colored
schematic elements to select decorations. Source:
[original manual](https://archive.org/details/civ2_manual).

The original `GAME.TXT` resources distinguish the complete `@THRONE` narrative
from `@ADDTOTHRONE`, “Which section shall we improve?” The normal runner may
acknowledge the complete source-matched narrative. It does not automatically
choose a decoration from the following graphical room.

Attempt 004 encountered that graphical boundary during development. The
operator used the following ordinary, individually recorded cosmetic inputs:

| Original captures | Ordinary input | Observed result |
|---|---|---|
| 350 → 351 | Escape | Pixels unchanged; no dismissal claimed |
| 352 → 353 | Click observed question heading | Pointer moved; chooser remained |
| 355 → 356 | Click the visible central chair at (302, 286) | Room presentation changed |
| 357 | Three seconds of painting, no ordinary input | Wooden chair visibly rendered |
| 358 → 359 | Click completed room floor at (320, 380) | Original map returned, displaying 3300 BC |

The records are separate `native_cosmetic_escape_attempted`,
`native_cosmetic_click_attempted`, `native_cosmetic_section_clicked`, and
`native_cosmetic_display_click_attempted` events. They retain actual source and
result image hashes, ordinary input receipts, and reviewed visual references.
The section selection is explicitly **operator-selected cosmetic decoration**;
it is not a Jev choice or evidence of autonomous gameplay. Failed probes do not
claim success. The guarded development helpers did not alter game memory,
rules, saves, or model probabilities.

At a recognized native-map boundary,
`civ2.preferences.configure_throne_presentation(ui)` can disable future **Throne
Room** presentations through the original Ctrl+P menu. It reads all six
checkboxes before and after, changes only Throne Room if needed, and refuses to
confirm if any other checkbox changes. Its `graphics_preferences_configured`
receipt has the explicit scope `Original cosmetic Throne Room presentation
only; no gameplay command`. On a fresh run, the runner performs the existing
Civilopedia-only setup and this Throne Room toggle as two separate verified
transactions at the first recognized map boundary, reobserving after each.
Neither is opened over a research, production, or other mandatory dialog.

Attempt 004 verified Throne Room **True → False**. Diplomacy Screen, Animated
Heralds, High Council, and Wonder Movies stayed True; Civilopedia for Advances
stayed False. The original post-configuration image SHA-256 was
`e0061c11b35605f6a96afe23ee664cd6d4c25819e10ec9e8c3fda972e96e58cb`.

No permanent palace-selection policy is implemented. Cosmetic receipts remain
distinct from model decisions and native gameplay checkpoint evidence.
