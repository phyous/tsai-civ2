# Dashboard contract

`web/index.html` is a fixed 1920×1080 live/replay composition. The same Canvas2D
function paints the live HUD and recording PNGs; original game pixels are rendered
by the same-origin iframe at `/engine/runtime.html`. No runtime implementation,
game files, credentials, fonts, or other remote assets live in this directory.

## Delivery and controls

Serve `/web/index.html`, `/web/dashboard.css`, `/web/dashboard.js`, and the runtime
from the same local origin (parent server: port3920). The dashboard polls
`GET /api/state` every500ms after the previous request completes. Requests time
out after4seconds. Disconnection leaves the last real observation visible and
marks telemetry disconnected. A malformed probability map is not displayed.

The only control requests are `POST /api/control` with JSON
`{"action":"start"}`, `{"action":"pause"}`, or `{"action":"resume"}`.
**Start game starts the emulator; it does not claim to start the Jev controller.**
Button success does not manufacture a state transition: `/api/state` remains
authoritative. Replay disables every control. The iframe is a spectator view;
mouse/keyboard operation belongs to the backend adapter.

## Snapshot v1

All game values are optional. Missing values display an em dash or explicit
unobserved state. The following is a schema description, not seeded demo data:

```typescript
type Snapshot = {
  status: 'setup'|'starting'|'running'|'paused'|'victory'|'defeat'|'error';
  mode?: 'live'|'replay';
  runtime_ready?: boolean; // displays iframe before running, if appropriate
  civilization?: string;
  turn?: number;
  year?: string;
  settings?: {label:string,value:string}[]; // actual selected settings, at most6
  empire?: {
    cities?:number; population?:number; treasury?:number; net_income?:number;
    science?:number; research?:string; research_turns?:number;
  };
  decision?: {
    id?:string|number; model?:string; latency_ms?:number;
    observed_turn?:number; observed_revision?:string|number;
    input_tokens?:number; // cumulative, when supplied
    answers?: Record<string, {
      type:'choice'; choice:string;
      probabilities:Record<string,number>; confidence?:number;
    }>;
    labels?: Record<string,Record<string,string>>; // question -> option -> label
    selected_question?:string; // root question, if a decision graph was used
    selected_action_question?:string; // selected child question, if present
    selected_intent?:string; // must match selected root answer
    action_label?:string;
    receipt?:'pending'|'accepted'|'refused';
    metadata?:object; // existing decision_graph/latency/token metadata supported
  };
  chronicle?: {id?:string,turn?:number,year?:string,label:string,kind?:string}[];
  message?:string; // short, safe operator text; never raw exceptions/server bodies
  playback_speed?:number;
};
```

Only supplied Choice probabilities are displayed. The chosen option must equal
a maximum probability, including a valid tied maximum. Exact totals of1 are
accepted; cent-quantized totals of0.99/1.01 are preserved and labelled, matching
the existing Jev client compatibility rule. Other totals or malformed options
hide the distribution. Multiple question groups require an explicit selected
question or graph path; a speculative companion is never silently presented as
the chosen action. Categories and child probabilities stay separate. The
command vector shows up to16 options; larger spaces use two columns when other
vectors are present. Up to three actual vectors have distinct panels labelled
command, routing, or companion (not dispatched). Further vectors and omitted
options are explicitly noted. The empty council names six strategic domains
without assigning probabilities. Labels use canvas text, never HTML interpolation.

## Injection, replay and capture

```javascript
window.Civ2Dashboard.render(snapshot); // normalized snapshot, paints immediately
window.Civ2Dashboard.setPolling(false); // offline playback/injected snapshots
window.Civ2Dashboard.setReplay(true); // stops polling, disables controls
await window.Civ2Dashboard.capture(); // PNG data URL, exactly1920×1080
await window.Civ2Dashboard.captureGame(); // original runtime PNG data URL
```

`capture()` awaits `iframe.contentWindow.Civ2Runtime.capture()`, which may be
synchronous or asynchronous and must return a PNG data URL. It uses the same HUD
paint function and preserves game aspect ratio without cropping. Concurrent calls
share one pending capture rather than building an unbounded queue. It fails if no
snapshot or original game capture exists; it never exports a fake game frame.
Backend recording should first obtain its stable game observation and publish
the corresponding snapshot, then capture. This UI cannot make asynchronously
supplied state and game pixels atomic by itself.

For live/export parity, the iframe container is4:3 (1120×840). The runtime should
fit its original canvas into its iframe using aspect-preserving letterboxing.
Recording omits interactive DOM controls. All information rendered on the HUD,
including connectivity/receipt state and evaluated turn, is retained.

## Implementation decisions and checks

The original StarCraft renderer is offline-only, so a unified canvas HUD avoids
maintaining independent CSS and Pillow recording layouts. DOM is limited to the
iframe, three accessible buttons, and screen-reader announcements. The imperial
palette and geometry are procedural; system serif/sans/mono fonts avoid remote
assets. The design is fixed16:9 and scales to the viewport.

Core normalization and geometry tests run without a server or model call:
`node --test web/dashboard.test.cjs`. The backend must separately validate legal
actions, authoritative receipts, victory evidence, and telemetry provenance.
Unknown game settings never default to an alleged civilization or difficulty.
