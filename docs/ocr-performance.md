# Local OCR transport

`scripts/ocr.swift` supports the original `ocr IMAGE.png` command and a private
JSON-lines worker mode. `civ2.ocr_worker` keeps one worker per executable revision
and serializes requests through its stdin/stdout pipes. It opens no network port.
Each image still receives a new `VNRecognizeTextRequest` and
`VNImageRequestHandler`, with accurate recognition, language correction disabled,
and `en-US`. Only framework startup and internal framework caches are reused.

No OCR results are cached. Crops, resizing, white-glyph analysis, conditional
passes, row merging, source hashes, and provenance remain in `observe.py`.
Per-request autorelease pools release temporary Vision objects. Workers recycle
after 256 images to bound opaque framework-cache lifetime across long campaigns.
Closing the Python process reaps its worker. An atomic executable replacement
retires the old child on the next request.

Build normally, or build a separate candidate before replacing a live binary:

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools swiftc scripts/ocr.swift -o .runtime/ocr.next
```

After validation, replace `.runtime/ocr` atomically at an operationally safe
boundary. Existing old binaries remain compatible: unsupported worker mode is
detected once, then the original one-shot CLI is used. A crashed worker,
malformed response, or mismatched request identity is discarded and uses the
one-shot CLI within the remaining request deadline. A timeout fails rather than
starting a second full timeout. A valid image-recognition failure is reported to
the existing observation error handling. No replacement text is generated.

## Retained-frame measurements

Measured offline on September 16, 2026, using original campaign captures and
three repetitions per frame. The worker was shared across frames; the first
map observation includes cold worker startup (339 ms). Values below are medians
in milliseconds, including original image analysis and Python processing.

| Retained frame | Vision passes | One-shot total | Worker total | Reduction |
|---|---:|---:|---:|---:|
| Attempt 004, UI 230, map | 5 | 849 | 229 | 73% |
| Attempt 005, UI 219, city | 3 | 642 | 274 | 57% |
| Attempt 005, UI 112, production | 5 | 908 | 311 | 66% |
| Attempt 004, UI 62, research | 3 | 584 | 215 | 63% |

All 12 complete observation JSONs matched the baseline exactly, including
text, confidence, geometry, conflicts, and per-row provenance. This measures OCR
only; emulator input, native rendering, model inference, and recording have
separate costs.

Median per-pass elapsed time (one-shot / worker):

| Frame | Native | Nearest 2× | Additional actual-image analyses |
|---|---:|---:|---|
| Map | 173 / 49 | 210 / 96 | Status 147 / 26; map label 147 / 18; grayscale label 149 / 16 |
| City | 199 / 69 | 246 / 129 | City caption 168 / 50 |
| Production | 199 / 80 | 248 / 129 | City caption 165 / 48; selected name 130 / 15; stats 143 / 15 |
| Research | 184 / 57 | 232 / 108 | Status 152 / 37 |

Private benchmark receipts are retained under `.runtime/ocr-benchmark/` and are
excluded from source releases. They contain the per-pass timings, observation
hashes, and original analysis images. The transport tests use isolated local
test children and cover concurrent callers, changed images at the same path,
legacy binaries, crashes, stale identities, bounded responses, timeouts,
per-image failures, atomic binary replacement, and child cleanup.

A separate 160-image check across all 16 distinct source analyses also matched
every one-shot result exactly. Worker RSS grew from 74 MiB after 16 images to
90 MiB after 160; this short check does not establish long-term memory stability.
The 256-image recycling limit bounds the lifetime of such framework allocations.
