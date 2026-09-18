# Exact original GDI text fallback

The optional herald fallback compares source-backed whole option rows against the original Windows3.1 Times New Roman bold font. It accepts zero missing or extra black foreground pixels, while requiring every other pixel to belong to the grayscale background palette measured in all three original calibration screens. It does not compare the texture background pixel for pixel. It does not change a decision's words, choose an option, issue input, or replace the general OCR path.

The atlas is generated locally from the original private Windows bundle. No font, glyph atlas, Windows file, game asset, or compiled probe is distributed in this repository.

## Local generation

First install the normal original runtime assets and `python3 scripts/fetch_modern_runtime.py`. With Docker supporting Linux amd64 and Node.js installed, run:

```sh
python3 scripts/build-font-atlas.py --compiler-archive /path/to/pinned/open-watcom-linux-x64
```

The compiler installer is the same hash-pinned official release documented in [observer-build.md](observer-build.md). Omitting `--compiler-archive` downloads that pinned release; a changed mutable upstream build is rejected. The generator verifies the original bundle and emulator assets, compiles the separate `scripts/gdi_atlas.c`, then boots a private Node js-dos instance. Only that private archive's startup entry changes; Civ2 and the pinned observer do not run. No browser or campaign is controlled. The instance exits after extraction, with a60second hard bound.

Generated bold and regular masks and metrics go under ignored `engine/game/gdi-fonts/`; build products stay under ignored `.runtime/gdi-font-build/`. Do not publish these derived font assets. Missing or modified atlas/metrics bytes disable the optional fallback safely. All four hashes are pinned in `civ2/gdi_text.py`. The generator verifies both styles before installing either.

## Proven scope and rejection rules

The original GDI font is `CreateFont(-16,...,700,...)`, Times New Roman, ANSI/default precision. Atlas512×240: ASCII32–126,16columns,32×40cells, TextOut origin4,4, original integer advances. Original historian header and subtitle matched exactly; composing individual glyphs reproduced complete-string GDI output. Quoted options in original development frames010/521,547,563 also matched exactly, including quote punctuation that native OCR corrupted.

The fallback is limited to original EXCHANGE0/EXCHANGE1 and PROPOSEPEACE options, including EXCHANGE0's original LABELS counteroffer. All alphanumeric tokens must equal the observed row. Variables are retained observed tokens, then checked against their own exact rendered pixels. Fixed punctuation comes from the original source and is accepted only when those pixels actually exist.

An independently observed herald title/soleOK, every native radio ring,25pixel row spacing, final row position, and one complete dotted focus boundary are mandatory. Each complete option interior is compared, including blank space outside the rendered label; missing black text, extra black foreground marks, off-palette pixels, extra/missing radios, extra OCR rows, different colors/font/layout, partial paint, or changed source resources cause abstention. The proven focus perimeter is excluded as control artwork. Every expected alternative must be present and the existing classifier must independently accept one full original body and all options before any row is replaced. Choices remain model-required.

Original screenshot hashes and dimensions stay unchanged. An internal classifier preflight uses an explicitly RGB-derived identity placeholder; its result is discarded, and the normal later classifier binds the unchanged original PNG hash. Raw OCR readings are preserved, with added atlas/source hashes, actual radio and text geometry, pixel-region hashes, and zero-error match evidence. Unsupported characters, wrapped labels, other fonts/scales, unknown bodies, and ambiguous matches continue through existing conservative handling. This is not an unrestricted text decoder or a general guarantee that a screen is complete.

## Production captions

The production caption uses the separately pinned regular Times New Roman font, `CreateFont(-16,...,400,...)`. The original caption paints the glyphs in black and overpaints the same glyphs in gray134 at fixed offsets `(-1,-1)` and `(-2,-1)`. This one composition matched original development frames010/786 (Cumae),005/112 (Rome),003/136 (Veii), and006/653 (Antium), with zero extra or missing black pixels and zero missing predicted gray pixels. No font or offsets are fitted per screen.

Observation adds state-independent masks for a bounded caption region only when the original Auto/Help/OK control geometry and measured grayscale palette are present. It retains the original OCR text, source PNG hash, row geometry, RGB region hash, and black/gray masks. This annotation can be cached without incorporating current city state.

The classifier's optional `gdi_titles` helper tries the exact original `PRODUCTION` source title against owned city names from a hashed native observation, or names from source-bound founding notices corroborated by the current city caption's year. It does not use spelling similarity to choose a candidate. Exactly one whole-region black-mask match is required, every predicted gray134 pixel must be present, and off-palette pixels cause abstention. Gray background texture may contain additional gray134 pixels; this is deliberately not a full RGB equality claim. Missing or changed font assets, foreign or ambiguous city identities, stale founding evidence, extra black marks, and altered source templates cannot supply a title.

Only a local prepared title row is replaced. Raw OCR, screenshot bytes, and hashes remain unchanged; evidence records both raw and exact text, source/city provenance, atlas pins, the mask proof hash, and zero-error counts. The ordinary production classifier still validates the original options, statistics, native controls, and any existing same-year founding guard. Recovering a caption does not authorize an action or infer missing choices.

## Treaty body word

The optional `gdi_treaty` fallback handles one measured body-row error: `hetween` instead of the original source word `between`. It preserves every other observed word, including both civilizations and the withdrawal terms. The complete row in original development frame011/1218 matched the same bold atlas at RGB48 with zero extra or missing foreground pixels. The full interior region must use the measured grayscale palette, and exactly one glyph-mask placement must match; it does not compare background texture pixel for pixel.

Recovery also requires the complete four-line treaty, its sole observed OK, and an independent final classification against the pinned original `TREATY` resource. Raw OCR provenance remains attached. Missing font assets, altered words or terms, additional choices, changed source text, or a single damaged/extra foreground pixel cause abstention. The normal later classification uses the unchanged original PNG hash.

## Herald paragraph punctuation

`gdi_bodies` reuses the existing bold atlas for four measured source templates: `PROPOSECEASE`, `CRUSADE`, `GREETINGS00`, and `GREETINGS03`. It changes punctuation only. Every observed alphanumeric token, including its case, names and numbers, must remain identical. Variables come exclusively from those observed tokens, with exactly one source binding; an ambiguous division of adjacent variables is rejected. Repeated variables must agree, including the crusade target repeated in the actual declaration-of-war option. The observed division of words into rows is retained.

Original development frames010/2955,011/2900,010/2672 and011/2888 establish the finite layouts. Every side of the native window border, the complete sole-OK widget RGB hash, and all observed native radio rings must match. The window independently fixes the paragraph origin; the matcher cannot slide or shrink its crop to ignore text. The complete paragraph region, including interline and trailing space, must have exactly the rendered RGB48 foreground mask and the measured grayscale palette. Original line pitch is20pixels, negative left glyph bearings are clipped at the shared TextOut origin, and original `_._._.` markup renders as spaced periods. Background texture itself is not compared pixel for pixel.

Retained original cease-fire, crusade, and greeting punctuation failures pass this proof with zero missing or extra foreground pixels. The raw `Isahella` reading in011/2888 deliberately fails: this helper cannot replace a leader's name. The separately recovered `Isabella` reading can participate only after independent pixel reading; tests then simulate loss of the closing quote against that unchanged original image. Other word errors, fonts, window sizes, missing lines, missing controls and unmeasured layouts still abstain. These calibrations are retained-screen tests, not a new live campaign encounter or a general full-dialog decoder.

The ordinary full-source classifier must still accept the complete paragraph and every unchanged alternative. Cease-fire and crusade decisions remain model choices; the greeting remains a sole-OK informational acknowledgement. Raw OCR and source/atlas/region proofs remain attached, and the normal pipeline retains the original PNG hash. No new font assets, emulator operations, game inputs or hidden state are involved.

## Promotion notice heading

Original012/2712 reads `Detense Mfinister` in OCR. `promotion_notice` recovers `Defense Minister` only above the complete two-line original `PROMOTED` notice and its sole aligned OK button. The same regular-font caption composition used for production titles matches the full fixed title band with zero extra or missing black pixels and every predicted gray134 pixel present. A unique placement, measured grayscale palette, pinned full source record, unchanged observed unit-name/body text, and successful final informational classification are required. Raw heading provenance remains attached; no spelling alias is added. The notice records what was displayed and does not assert a native unit mutation or battle outcome.

## City caption dates

`gdi_dates` changes only year digits within an already observed city caption above the production controls. It uses the observed era and number length, enumerating at most one digit substitution; it receives no native state, expected year, or city-name candidate. The original literal `City of` must match uniquely and anchor the baseline. The complete date field, including the preceding city separator comma and trailing comma, must uniquely match the original regular-font black mask, all predicted gray134 pixels and measured palette. Blank top, bottom and right margins exclude adjacent or truncated numeric fields. The caption's left bevel has four additional measured gray background colors; the date field retains the stricter caption palette.

In original012/2872 the complete date field proves `A.D. 840` while OCR repeatedly reads `A.D. 340`. The prepared caption keeps its observed `Fispalis` spelling and all other text unchanged. The separate existing production-title proof then uses a same-year founding notice to identify Hispalis, with all16 choices still required. Previous OCR readings and prior date-consensus metadata remain attached alongside the exact date proof. BC ordering has synthetic coverage; the measured live example is AD. Unknown layouts, competing matches, changed era/length, multiple changed digits, missing punctuation or altered foreground pixels abstain. No action or choice is authorized by this recovery alone.
