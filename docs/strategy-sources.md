# Strategy supplied to Jev

The user requested researched Civilization II advice in the actual Jev prompt.
`civ2/strategy.py` contains the versioned synthesis; `model_state` includes it in
unit, planning, empire, production and other dialog requests. The exact request
and guide revision are retained with every API call. Advice does not choose
commands or rewrite returned probabilities.

Sources read September 16, 2026:

| Source | Advice retained | Limits applied |
|---|---|---|
| [Original Civilization II manual](https://archive.org/details/civ2_manual) | Government support and tile rules; city growth, happiness and resources; trade; passenger transport; conquest and successful spacecraft arrival | The original executable and observed menus remain authoritative. |
| [Lars and Jens Palsberg, How to Win Civ2 Before 1750 AD](https://civfanatics.com/civ2/strategy/win1750ad/) | Adopt early Monarchy; inexpensive initial garrison before repeated Settlers; productive connected cities; purposeful military research; concentrated attacks with defenders for captured cities | The article assumes Deity, large map, seven civilizations and raging hordes. Its happiness thresholds, exact city counts, dates, 23-advance sequence and four-wonder build are not imposed on Prince. |
| [Octagon's Strategy for Civ2](https://civfanatics.com/civ2/strategy/octagon/) | Monarchy, six-to-eight-city opening as a flexible aim, roads on useful worked land, city specialization, veteran forces, selective wonders, trade and practical diplomacy | It spans later editions and Deity. Claims that particular buildings/wonders are always best or that a fixed garrison is universally optimal are not treated as rules. |
| [Apolyton, Early Landing Games Strategy Guide](https://apolyton.net/forum/civilization-series/civilization-i-and-civilization-ii/95334-early-landing-games-strategy-guide) | Adapt to actual conditions; prepare food/happiness/support before Republic; trade-rich science core and supporting Caravans; prepare ship production while researching | Its detailed play assumes later 2.42/MGE and different settings. Fixed revolution calendars, city limits and deliberately undefended cities are not copied into this 1.06 Prince run. |

The sources disagree on some investments. The conquest guide minimizes buildings
and avoids the Great Library, while Octagon likes a broader economic/wonder
build. The prompt retains the common principle: invest for the chosen victory
plan and current bottleneck, rather than collect every improvement or wonder.
It offers conquest and space as alternatives without forcing an unobserved path.

The most immediate lessons from the debug runs are explicit: a whole empire of
Settler queues with no army needs a better production mix; researching Monarchy
does not adopt it; irrigation on ordinary Grassland does not improve its food
yield under Despotism. These are recommendations tied to observed facts, not
automatic production changes or a hard-coded opening script.

Revision v4 also explains that completed unit builds repeat automatically.
A city still producing Warriors may already have finished several; with no
Settlers/Engineers and no worker in production, ending turns cannot create an
expansion pipeline. The empire review reports observed garrisons and current
worker builds, and labels the city route as an opportunity to change production.
Jev decides whether that intervention is worthwhile; the harness does not switch
the queue or impose a garrison target.

Revision v5 adds the original home-city support arithmetic and the risk of a
Settler completion reducing both population and output. Revision v6 clarifies
the original emissary workflow: receiving the audience is a decision to hear
the proposal, not acceptance of a treaty, tribute, technology transfer or war
demand. The subsequent terms remain separate observed model choices. This
addresses a possible decision-framing problem; the earlier American attack
does not prove that refusing its audience caused the loss.
