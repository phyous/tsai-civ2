# Exact original GDI text fallback

The optional herald fallback compares source-backed whole option rows against the original Windows3.1 Times New Roman bold font. It accepts zero missing or extra black foreground pixels, while requiring every other pixel to belong to the grayscale background palette measured in all three original calibration screens. It does not compare the texture background pixel for pixel. It does not change a decision's words, choose an option, issue input, or replace the general OCR path.

The atlas is generated locally from the original private Windows bundle. No font, glyph atlas, Windows file, game asset, or compiled probe is distributed in this repository.

## Local generation

First install the normal original runtime assets and `python3 scripts/fetch_modern_runtime.py`. With Docker supporting Linux amd64 and Node.js installed, run:

```sh
python3 scripts/build-font-atlas.py --compiler-archive /path/to/pinned/open-watcom-linux-x64
```

The compiler installer is the same hash-pinned official release documented in [observer-build.md](observer-build.md). Omitting `--compiler-archive` downloads that pinned release; a changed mutable upstream build is rejected. The generator verifies the original bundle and emulator assets, compiles the separate `scripts/gdi_atlas.c`, then boots a private Node js-dos instance. Only that private archive's startup entry changes; Civ2 and the pinned observer do not run. No browser or campaign is controlled. The instance exits after extraction, with a60second hard bound.

Generated masks and metrics go under ignored `engine/game/gdi-fonts/`; build products stay under ignored `.runtime/gdi-font-build/`. Do not publish these derived font assets. Missing or modified atlas/metrics bytes disable the optional fallback safely. Both hashes are pinned in `civ2/gdi_text.py`.

## Proven scope and rejection rules

The original GDI font is `CreateFont(-16,...,700,...)`, Times New Roman, ANSI/default precision. Atlas512×240: ASCII32–126,16columns,32×40cells, TextOut origin4,4, original integer advances. Original historian header and subtitle matched exactly; composing individual glyphs reproduced complete-string GDI output. Quoted options in original development frames010/521,547,563 also matched exactly, including quote punctuation that native OCR corrupted.

The fallback is limited to original EXCHANGE0/EXCHANGE1 and PROPOSEPEACE options, including EXCHANGE0's original LABELS counteroffer. All alphanumeric tokens must equal the observed row. Variables are retained observed tokens, then checked against their own exact rendered pixels. Fixed punctuation comes from the original source and is accepted only when those pixels actually exist.

An independently observed herald title/soleOK, every native radio ring,25pixel row spacing, final row position, and one complete dotted focus boundary are mandatory. Each complete option interior is compared, including blank space outside the rendered label; missing black text, extra black foreground marks, off-palette pixels, extra/missing radios, extra OCR rows, different colors/font/layout, partial paint, or changed source resources cause abstention. The proven focus perimeter is excluded as control artwork. Every expected alternative must be present and the existing classifier must independently accept one full original body and all options before any row is replaced. Choices remain model-required.

Original screenshot hashes and dimensions stay unchanged. An internal classifier preflight uses an explicitly RGB-derived identity placeholder; its result is discarded, and the normal later classifier binds the unchanged original PNG hash. Raw OCR readings are preserved, with added atlas/source hashes, actual radio and text geometry, pixel-region hashes, and zero-error match evidence. Unsupported characters, wrapped labels, other fonts/scales, unknown bodies, and ambiguous matches continue through existing conservative handling. This is not an unrestricted text decoder or a general guarantee that a screen is complete.
