# Original Foreign Minister report

The first supported contacted F3 layout is the original 640×480 window with
one selected contact and three visible buttons: **Check Intelligence**, **Send
Emissary**, and **Cancel**. Each is an actual model choice. A button dispatch
clicks its observed center without an added Enter key.

`foreign_report.py` requires the complete original `REPORTFOREIGN` resource,
the original LABELS power/reputation/relation strings, all six foreground text
rows, and a uniquely matching original RULES leader and tribe. It retains the
observed rank, attitude, relationship and “No Embassy” text. It never maps the
observed nation to a native civilization slot. The raw measured headings
“Foreign Winister” and “Foreign Minisber” are accepted only with all other
guards; the OCR text is not replaced.

The complete window edges, selected radio and separator band have identical
RGB hashes in two original captures: isolated3950 Vikings at 1200 BC and
attempt010 Germans. The source PNG hash is checked before those pixel regions.
Other layouts, missing text or controls, and changed calibration pixels
are unsupported; the separately measured two-contact extension is described below. Private original screenshots are not distributed.

In the isolated debug calibration, a real Jev response selected Check
Intelligence for the observed Vikings contact. The click completed but the
same report remained after additional native paint time. The next real Jev
response received that observed no-change fact and selected Cancel, which
returned to the map. Both requests, responses, source frames and actual input
receipts are retained privately. No intelligence or diplomatic effect is
inferred from a click. All three buttons use the same visible black text on
gray background, so this calibration does not establish disabled-button state.
The original manual explains that intelligence details require an embassy
(local transcription lines5804–5812).

The ordinary Send Emissary path remains a separate strategic model choice;
subsequent original emissary dialogs require their own existing source-bound
classification and decisions. Native intelligence reports, embassy-present
contacts remain outside these measured layouts.


The original two-contact report in attempt011 at AD220 adds explicit contact
selection. Both complete contact rows and all three report buttons remain
available. Each contact row is a `radio_selector`: its canonical action carries
`selection_only: true`, so dispatch clicks that row without Enter. A later,
fresh report and another actual model choice are required to send an emissary
or request intelligence. The prompt includes the currently selected named
contact and explains this separation.

This extension requires the exact original 602×142 foreground border and
separator hashes, all seven foreground text rows, and exactly two original
radio rings at the measured positions. Each radio's five-by-three center must
be uniformly selected black or unselected gray, with exactly one selected.
The complete option band is scanned independently for extra radio rings.
Only OCR boxes intersecting the exact bottom two border rows while centered
below the window may be retained as background; no foreground text is omitted.
The model request retains the source resource/image hashes and pixel proof.
The offline verifier independently recomputes the entire pixel proof for
**every** report action, including buttons, and rejects a selector receipt
containing Enter. The single-contact path retains its original three choices.

The initial two-contact frame and the subsequent selected-Spanish frame are
actual game captures. Jev decision683 selected Isabella with one click and no
Enter; the next retained frame independently shows the second radio selected.
Decision684 separately chose Cancel, then decision685 finished the turn.
Malformed-control and center-tampering tests are synthetic. No diplomatic
effect is inferred from selecting a contact or clicking a report button.
