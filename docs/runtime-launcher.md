# Dedicated Chrome runtime

Use a dedicated headless Chrome process to keep the original emulator running
without normal browser-tab background throttling. This uses the same launch flags
as the successful local headless benchmark. It does not change DOSBox speed,
gameplay rules, or model decisions, and it does not start a campaign by itself.

After installing the Python dependencies and fetching the local runtime assets:

```sh
python3 -m civ2.launcher start --name campaign-c --port 3930
python3 -m civ2.launcher status campaign-c
```

Omit `--port` to choose an available port from 3930–3999. Ports 3920–3924 are
reserved so existing development games cannot be replaced accidentally. An
explicit port must be unused. Chrome is discovered at its standard macOS path or
on Linux's `PATH`; `--chrome /absolute/path/to/chrome` selects another executable.
Use the same virtual-environment Python that has the project's dependencies.

Startup waits for the server and the dashboard's runtime WebSocket connection.
The returned JSON includes the launch ID, port, process receipts, local directory
and **watch URL**. Open that `/web/watch.html` URL in your ordinary browser. It
shows the running original game and Jev panel without creating a second emulator.
Keep the server root URL in the dedicated Chrome process only.

Every launch creates an exclusive directory and fresh Chrome profile under
`.runtime/launchers/<id>/`. The profile, server/Chrome logs and process manifest
are ignored by Git. Existing names cannot be reused, even after stopping. The
launcher does not open or copy a normal browser profile and does not expose a
remote-debugging port. It removes `TYPESAFE_API_KEY` from the runtime children's
environment; the separate Python controller reads its own private credentials.

## Prepare and run a campaign

The connected runtime is initially unbooted. Select the same dedicated port for
setup and the controller:

```sh
python3 -m civ2.boot --port 3930 --profile campaign-c \
  --directory .runtime/campaign-c-setup

python3 -m civ2.run --port 3930 \
  --initial-save .runtime/campaign-c-setup/initial.sav \
  --directory runs/campaign-c --env-file /path/to/private/env
```

`new_game` uses the original setup screens and verifies the native save. Add
`--planning` to the controller command for the optional planning variant. Use a
different port, launch name, setup directory, run directory and boot profile for
each parallel campaign. The launcher does not start model requests or choose
strategic actions.

## Stop and retain evidence

Pause/end the controller and export the latest original native save before
stopping its runtime. Process shutdown cannot save an unsaved game for you.

```sh
python3 -m civ2.launcher stop campaign-c
```

Stop first verifies both processes against their recorded full command/start
fingerprint and private process group. The server command includes this launch's
ID; Chrome includes its exact isolated profile. A reused PID, altered command,
redirected profile or invalid manifest causes refusal before signaling either
process. Only verified owned groups receive termination, with bounded escalation
if they do not exit. Profiles, saves, logs and receipts remain available locally.
Missing processes are skipped; other Chrome windows and game servers are never
selected by executable name or a global `pkill`.

If a leader process has already disappeared, the launcher does not infer ownership
of a remaining process group. Inspect that launch's local logs instead of deleting
its manifest or trying to reuse its launch ID.

The launcher is tested for profile isolation, reserved/occupied ports, stale PID
refusal, manifest/path redirection and owned-process shutdown. The integration is
based on the observed benchmark; these tests do not claim a campaign victory or
measure performance on every host.
