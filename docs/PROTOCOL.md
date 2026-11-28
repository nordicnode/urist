# DF Agent Harness — Protocol Design

**Status:** design (phase 0). Nothing here is verified against a live game yet;
see [§8 Open questions](#8-open-questions--to-verify-in-phase-1).

**Scope:** Dwarf Fortress **0.47.05** + DFHack **0.47.05-r5**, fortress mode.
This harness is a separate, from-scratch implementation. Mikey's `dfkit`
(`github.com/nordicnode/dfkit`) was read only to understand the transport
approach; no code is copied from it and it is not modified.

---

## 1. What `dfagent` is (dfkit's transport)

`dfkit` (repo `nordicnode/dfkit`, branch `master`, created 2026-11-25) is two
layers:

| Layer | Files | Role |
|---|---|---|
| **`dfagent` — transport** | `dfhack_client.py` (275 lines), `dfagent.py` (987 lines), generated `*_pb2.py` stubs, `proto/`, `lua/agent/*.lua` | Talks DFHack RPC; CLI that prints JSON on stdout |
| **`dfkit` — framework** | `dfkit/model.py`, `actions.py`, `tasks.py`, `goals.py`, `daemon.py`, `events.py`, `ui.py`, `cli.py` | World model + SQLite history, verified actions, composed tasks, goals/planner, daemon policy loop, semantic menu driver |

**`dfagent` is a separable transport.** `dfhack_client.py` imports nothing from
`dfkit`: it is a standalone, minimal DFHack RPC client (Python stdlib +
`protobuf` runtime only). `dfagent.py` is a one-shot CLI over it — each
invocation connects, runs one command, prints JSON, exits. `dfkit` drives the
game through it, plus one-shot Lua helper scripts executed via RPC
`RunCommand("lua", …)`.

What `dfagent` exposes to an agent (CLI commands, JSON on stdout):

- Observe: `observe` (one JSON snapshot), `status`, `units` / `unit ID`, `map`,
  `blocks`, `scan`, `buildings`, `jobs`, `reports`, `screen`, `where`, `cursor`
- Act: `dig`, `undesignate`, `build`, `stockpile`, `order`, `key` (inject keys),
  `cmd` (any DFHack console command), `lua` (evaluate Lua), `pause`
- Stream: `events [--follow]` — JSON-lines, **poll-based**: it polls
  `agent/status` + `GetReports` and diffs (new citizens, new threats, new
  reports, mode/pause/year changes)
- Manage: `start [--ascii]` / `stop` (launch DF, wait for the RPC port; `die` +
  restore graphics profile), `version`, `commands`, `recipes`, `supervise`
  (policy loop: threats, food/drink, migrants, idlers, autosave)

`dfkit`'s daemon (`daemon.py:tick`) is one policy pass: refresh the model →
drain events → pause on invasion/hostile → else advance one goal or run fixed
policy rules (drink < 20 → brew, food < 15 → cook, many idlers → autolabor).
Every decision is journaled in SQLite. Verified end-to-end by Mikey on a real
fort (world "Lina Yula", fort "Ostathîton"): world gen via `key` + `screen`,
embark, a `dig` designation read back from the map, pause/unpause advancing
the clock, `quicksave` writing `world.sav`.

### 1.1 How dfkit gets *push* events (the part that matters for §5)

The RPC layer has no server push. dfkit gets events in-game instead:

- `lua/agent/watch.lua` registers `plugins.eventful` handlers
  (`JOB_COMPLETED`, `UNIT_DEATH`, `REPORT`, `INVASION`, `NEW_UNIT_ACTIVE`)
  that append one JSON object per line to `df_linux/dfkit-events.jsonl`.
- `dfkit/events.py:drain` reads the file from a stored byte offset (kept in
  the model DB), so no event is handled twice or lost across restarts.
- `dfkit/events.py:summarize` collapses a batch into what policy needs:
  deaths, hostiles/invasion, job completions, report text containing
  "cancels".

We reuse this *pattern* (eventful → JSONL → drain), with our own Lua and our
own drain, not dfkit's code.

### 1.2 dfkit gotchas to re-verify, not assume

Recorded in dfkit's README / FRAMEWORK.md from live play; each must be
re-confirmed against our own build in phase 1:

- Screen buffer is **column-major** in 0.47.05 (`index = x * height + y`).
- `BlockRequest` takes **block** coordinates (`tile // 16`); `max_z` is
  **exclusive**; tiles inside a block are column-major too.
- DF strings are CP437 bytes; decode UTF-8 if valid, else CP437.
- `SetPauseState` sets the flag, but DF re-asserts pause just after a save
  loads — verify, fall back to injecting the space key.
- Threats need `isOpposedToLife` **or** `flags1.active_invader` to catch
  sieges and spawned units.
- Never free a job struct (0.47.05 crashes if a freed job is still
  referenced); `undesignate` clears designations and lets the game cancel.
- Stockpile category flags alone leave per-subtype vectors empty; build one
  stockpile per category by hand once, then copy settings with a template.
- Manager orders: the shipped `workorder` script checks a stale
  `assignments_by_type` cache; dfkit writes `df.manager_order` records
  directly. Direct workshop jobs (`q` menu, `a`) are the reliable path.
- Furniture `build` creates a site consuming a matching item — a carpenter
  must make the item first.

---

## 2. Transport to DFHack: the remote protocol

### 2.1 Authoritative sources

- **Protocol spec (published docs, verified):**
  https://docs.dfhack.org/en/50.10-r1/docs/dev/Remote.html
  — *Note:* this is the 50.10-r1 build. The 0.47.05-r5 docs build no longer
  exists (`/en/0.47.05-r5/docs/dev/Remote.html` returns 404, and
  `docs/dev/Remote.rst` is absent at tag `0.47.05-r5`). The protocol below is
  corroborated against the 0.47.05-r5 sources, which agree with the doc.
- **0.47.05-r5 sources** (repo `DFHack/dfhack`, tag `0.47.05-r5`):
  - `library/include/RemoteClient.h` — constants, header structs, protocol
    description comment; `DEFAULT_PORT = 5000` (line 236)
  - `library/RemoteServer.cpp` — server config + bind behaviour
  - `library/proto/CoreProtocol.proto` — core messages and RPC declarations
  - `plugins/proto/RemoteFortressReader.proto` — RFR method list (lines 10–45)
  - `plugins/eventful.cpp`, `plugins/lua/eventful.lua` — in-game event hooks
  - `library/dfhack-run.cpp`, `package/linux/dfhack-run` — shipped CLI client

### 2.2 Server configuration

- DFHack starts a TCP server on game launch. Failure to bind is logged to
  `stderr.log`.
- Config file `dfhack-config/remote-server.json`:
  `{"allow_remote": false, "port": 5000}` (defaults; the server rewrites/
  normalizes the file on start).
- `DFHACK_PORT` environment variable takes precedence over the config file
  (per the published docs; dfkit relies on this with port **5001**, because
  5000 is taken on Mikey's machine). *Verify the env override live in phase 1*
  — see §8.
- `allow_remote: false` (default) binds **`127.0.0.1` only**
  (`RemoteServer.cpp:447`: `const char* addr = allow_remote ? NULL : "127.0.0.1"`).
  `allow_remote: true` binds all interfaces and is insecure (arbitrary code
  execution). Additionally, individual RPC functions are gated for non-local
  clients by the `SF_ALLOW_REMOTE` flag (`RemoteServer.cpp:327`).
- **No authentication, no encryption.** Localhost is the trust boundary.

### 2.3 Wire protocol (all numbers little-endian; max payload 64 MiB)

**Handshake** — client sends, server replies:

| Direction | Bytes |
|---|---|
| Client → Server | `char[8] "DFHack?\n"` + `int32 version = 1` (12 bytes) |
| Server → Client | `char[8] "DFHack!\n"` + `int32 version = 1` (12 bytes) |

Both versions must be 1. Anything else: abort the connection.

**Request** — `header(id, size)` + protobuf payload:

| Field | Type | Notes |
|---|---|---|
| `id` | `int16` | method id (see §2.4); ≥ 0 |
| `size` | `int32` | length of the protobuf payload in bytes |

(The C struct `RPCMessageHeader` is `int16 id; int32 size;` — 6 bytes on the
wire as written by the reference client: `struct.pack("<hhi", id, 0, size)`
is an 8-byte header with a 2-byte pad. Match the reference framing exactly;
do not "simplify" to 6 bytes without testing against the live server.)

**Reply** — one request produces zero or more TEXT messages, then exactly one
terminal message:

| Reply id | Meaning | `size` field |
|---|---|---|
| `-1` `RPC_REPLY_RESULT` | success | payload length; body is the method's output protobuf message |
| `-2` `RPC_REPLY_FAIL` | failure | **holds the error code directly** (a `command_result` `CR_*` value), not a length; no body |
| `-3` `RPC_REPLY_TEXT` | console text | payload length; body is `dfproto.CoreTextNotification` (repeated `CoreTextFragment{text, color}`) |

**Quit** — client sends header `(id = -4 `RPC_REQUEST_QUIT`, size = 0)` and
closes the socket immediately. The server closes the connection after a FAIL.

**Conversation flow:** handshake → repeat { request → 0..n TEXT → RESULT or
FAIL } → quit. The client initiates every call; the server never speaks first
and never pushes unsolicited messages. **There is no change/notification
channel in the RPC layer** — "Currently there are no change-based or
change-driven notifications, so remote fortress clients must perform the
expensive operation of polling" (Dwarf Fortress Wiki, DFHack Remote API
section). Push comes from the in-game `eventful` hooks (§5), not from RPC.

### 2.4 Method binding

Two methods have hardcoded ids; everything else is bound by name:

| ID | Method | Input | Output |
|---|---|---|---|
| 0 | `BindMethod` | `dfproto.CoreBindRequest{method, input_msg, output_msg, plugin?}` | `dfproto.CoreBindReply{assigned_id}` |
| 1 | `RunCommand` | `dfproto.CoreRunCommandRequest{command, arguments[]}` | `dfproto.EmptyMessage` |

To call a plugin method: send `BindMethod` with the method name, the fully
qualified input/output protobuf message names, and the plugin name (default
plugin is `RemoteFortressReader` when omitted in dfkit's client; pass it
explicitly in ours). Cache the returned `assigned_id` per (plugin, method)
for the life of the connection — ids are assigned by the server per
connection and must not be assumed stable across reconnects.

Core RPCs declared in `CoreProtocol.proto`:

- `BindMethod`, `RunCommand` (above)
- `CoreSuspend` / `CoreResume`: `EmptyMessage → IntMessage`
- `RunLua`: `CoreRunLuaRequest{module, function, arguments[]} →
  StringListMessage` — **calls a named function in a named Lua module only;
  it cannot evaluate arbitrary code.** Arbitrary Lua goes through
  `RunCommand("lua", <code>)` (see §2.6).

### 2.5 RemoteFortressReader methods (0.47.05-r5)

From `// RPC` comments in `plugins/proto/RemoteFortressReader.proto`
(lines 10–45). Input → output as declared there; `EmptyMessage` is
`dfproto.EmptyMessage`.

| Method | Input → Output |
|---|---|
| `GetVersionInfo` | `EmptyMessage → VersionInfo` (DF/DFHack/RFR versions) |
| `GetPauseState` / `SetPauseState` | `EmptyMessage → SingleBool` / `SingleBool → EmptyMessage` |
| `GetMapInfo` | `EmptyMessage → MapInfo` |
| `GetUnitList` | `EmptyMessage → UnitList` |
| `GetUnitListInside` | `BlockRequest → UnitList` |
| `GetViewInfo` | `EmptyMessage → ViewInfo` |
| `GetBlockList` | `BlockRequest → BlockList` |
| `GetTiletypeList` | `EmptyMessage → TiletypeList` |
| `GetPlantList` | `BlockRequest → PlantList` |
| `GetItemList` | `EmptyMessage → MaterialList` |
| `GetBuildingDefList` | `EmptyMessage → BuildingList` |
| `GetReports` | `EmptyMessage → Status` (announcements/combat reports) |
| `GetCreatureRaws` / `GetPartialCreatureRaws` | `EmptyMessage → CreatureRawList` / `ListRequest → CreatureRawList` |
| `GetPlantRaws` / `GetPartialPlantRaws` | `EmptyMessage → PlantRawList` / `ListRequest → PlantRawList` |
| `GetMaterialList` / `GetGrowthList` | `EmptyMessage → MaterialList` |
| `GetWorldMap` / `GetWorldMapNew` | `EmptyMessage → WorldMap` |
| `GetRegionMaps` / `GetRegionMapsNew` | `EmptyMessage → RegionMaps` |
| `GetWorldMapCenter` | `EmptyMessage → WorldMap` |
| `GetLanguage` | `EmptyMessage → Language` |
| `GetGameValidity` | `EmptyMessage → SingleBool` |
| `CopyScreen` | `EmptyMessage → ScreenCapture` |
| `PassKeyboardEvent` | `KeyboardEvent → EmptyMessage` |
| `SendDigCommand` | `DigCommand → EmptyMessage` |
| `MoveCommand` / `JumpCommand` | `MoveCommandParams → EmptyMessage` |
| `MenuQuery` | `EmptyMessage → MenuContents` |
| `MovementSelectCommand` | `IntMessage → EmptyMessage` |
| `MiscMoveCommand` | `MiscMoveParams → EmptyMessage` |
| `CheckHashes` / `ResetMapHashes` | `EmptyMessage → EmptyMessage` |

There is **no core `GetVersion`** RPC in 0.47.05-r5; version info comes from
RFR `GetVersionInfo`. (Newer DFHack has core version RPCs; do not use them —
they may not exist at this tag.)

Other plugin proto sets exist at this tag (`AdventureControl`,
`DwarfControl`, `ItemdefInstrument`, `isoworldremote`, `rename`,
`ui_sidebar_mode`, `stockpiles`) but are out of scope for phase 1; RFR +
core is enough for observation and basic action, with Lua covering the rest.

### 2.6 The Lua bridge

Lua is how we reach everything RFR does not expose (jobs, buildings,
stockpiles, labors, orders, unit health/mood, event hooks). Two routes:

1. **`RunCommand("lua", <code>)`** — evaluates arbitrary Lua in the DFHack
   interpreter. Output is whatever the code `print()`s, delivered as
   `RPC_REPLY_TEXT` (`CoreTextNotification`) messages before the RESULT.
   This is the primary route. Convention: helper scripts `print()` exactly
   one JSON object; the client joins TEXT fragments and parses the JSON.
   (This is how dfkit's `agent/*.lua` helpers work; ours are written from
   scratch.)
2. **`RunLua` RPC** — named module function only; useful if a helper needs
   structured string-list returns, but not a general escape hatch. Phase 1
   will use route 1 only.

Helper scripts live in the harness repo under `lua/agent/` and must be
visible to DFHack at runtime: either copy/symlink them into
`df_linux/hack/scripts/agent/` or point DFHack's script path at the harness
folder. **Verify the exact mechanism in phase 1** (dfkit's README says
"point DFHack's script path at this folder or copy them into
`df_linux/hack/scripts/agent/`" — confirm which works on a clean install).
Scripts must be defensive: wrap bodies in `pcall`, always print valid JSON
(even on error: `{"ok": false, "error": "..."}`), never crash the game.

Keyboard injection (`PassKeyboardEvent`) uses SDL 1.2 key events
(`type` 2 = key down, 3 = key up; `sym` = SDL keysym; `state` 1/0;
`unicode` = sym for printable ASCII else 0; `scancode` 0; `mod` 0), sent as
down/up pairs with a small delay. This is the fallback for menus with no API
(military, trade, hospital) — see §8.

### 2.7 Writing our own Python client from scratch

**DFHack ships no Python client.** `dfhack-run` is a C++ binary
(`package/linux/dfhack-run`) that uses the RPC interface to invoke commands
externally. The docs list third-party clients; the Python one,
`McArcady/dfhack-client-python` (adapted from Blendwarf, 2021, 3 commits,
8 stars, 0 releases), is effectively unmaintained. Do not depend on it.

What our client needs (all verified above):

1. `socket` + `struct` (stdlib) for the TCP framing in §2.3.
2. The **0.47.05-r5 `.proto` files**, vendored into our repo under `proto/`:
   `library/proto/CoreProtocol.proto`, `library/proto/Basic.proto`,
   `plugins/proto/RemoteFortressReader.proto`,
   `plugins/proto/ItemdefInstrument.proto` (only if needed),
   `plugins/proto/ui_sidebar_mode.proto` (only if needed).
   Source: `DFHack/dfhack` tag `0.47.05-r5`, paths above. **Do not copy
   dfkit's vendored protos** — fetch them from the DFHack repo so provenance
   is clean (they are the same upstream files, but ours come from upstream).
3. Generated stubs: `protoc -Iproto --python_out=. proto/*.proto`
   (regenerate if the DFHack version ever changes; pin to 0.47.05-r5).
   Only runtime dependency: `protobuf` (`protobuf>=5.0`).
4. A method table mapping method name → (plugin, input message, output
   message), a `bind` cache, and a `call` that collects TEXT fragments and
   returns `(parsed_output_message, text)`.
5. CP437 string decoding (UTF-8 if valid, else CP437) for names.
6. One connection, serialized calls (see §8 — concurrent connections are
   unverified; assume the server is effectively single-client).
7. Reconnect with backoff; on reconnect, re-handshake and re-bind (ids are
   per-connection). Treat a dropped connection as "game not running" until
   the port answers again.

---

## 3. Decision: the agent-facing protocol

### 3.1 Recommendation

**A local HTTP server, JSON over HTTP/1.1, plus Server-Sent Events for
push. One daemon process owns the DFHack connection and serves all agents.**

```
  ┌─────────────┐   DFHack RPC (protobuf/TCP 127.0.0.1:5001)   ┌──────────────┐
  │  DF 0.47.05 │ ◄──────────────────────────────────────────► │  dfh daemon  │
  │  + DFHack   │   eventful Lua → JSONL file (drained)        │  (Python)    │
  └─────────────┘                                              └──────┬───────┘
                                                                     │ HTTP JSON
                                                                     │ 127.0.0.1:8765
                                        ┌────────────────────────────┼────────────────────────────┐
                                        ▼                            ▼                            ▼
                                  any LLM agent              `dfh` CLI (thin              human dashboard
                                  (incl. Freebuff             client over HTTP)             / tests (curl)
                                  agent on Mikey's
                                  own machine)
```

- **Daemon (`dfh daemon` / `dfh start`):** single Python process (stdlib
  only). Owns the one DFHack RPC connection, runs the event watcher, keeps a
  SQLite journal/state store, serves HTTP. Started/stopped via the `dfh` CLI
  (§3.4).
- **HTTP API:** `http://127.0.0.1:8765/v1/...` (§4). JSON request/response
  bodies. `GET /v1/events` is an SSE stream (§5); every other read is a plain
  GET; every mutation is a POST returning a verified result (§6).
- **CLI (`dfh`):** a thin client over the same HTTP API (`dfh state`,
  `dfh task brew`, `dfh events --follow`, …) for humans and shell scripts.
  It dogfoods the API — no second protocol.

### 3.2 Why HTTP + SSE (and not the alternatives)

| Requirement | HTTP + SSE | stdio JSON-lines | WebSocket |
|---|---|---|---|
| Any AI can drive it (incl. a Freebuff agent on Mikey's machine) | **Yes** — HTTP+JSON is the one thing every agent runtime can already call; no custom transport, no process management | No — the agent must spawn and babysit a child process, frame stdin/stdout, handle restarts | Yes, but needs a WS client; more moving parts |
| Testable with curl | **Yes** — every endpoint, plus `curl -N` for the event stream | No | No (needs a WS client) |
| Multiple consumers at once (agent + human + tests) | **Yes** | No — one process, one stdin/stdout | Yes |
| Push (events, not poll-only) | **Yes** — SSE is a standard, reconnectable push channel (`Last-Event-ID` replay) | Yes, but only to the one attached process | Yes |
| Firewall / network setup | None — localhost only | None | None |
| Dependencies | Python stdlib (`http.server`) — zero new deps | Zero | Needs a WS library or hand-rolled framing |

**Decision:** HTTP + SSE. stdio JSON-lines was the main alternative; it loses
on multi-consumer access and on agent ergonomics (a Freebuff agent would have
to manage a subprocess lifecycle instead of just calling URLs). It stays on
the table as a possible *secondary* mode later (e.g. `dfh --stdio` for an
embedded single-agent setup) but is not the primary protocol. WebSocket adds
machinery for no benefit here: our push is server→client only, and
request/response fits plain HTTP.

### 3.3 Authentication model (local use)

- **Bind `127.0.0.1` only, always.** The daemon never listens on `0.0.0.0`.
  Remote access is out of scope; anyone who needs it can SSH-tunnel.
  (DFHack's own RPC layer has no auth at all — the HTTP layer is the trust
  boundary, and it must never be exposed past localhost.)
- **Optional bearer token** (defense in depth against other local processes /
  browser tabs hitting the daemon):
  - On first run the daemon generates a random token and stores it at
    `~/.config/df-agent-harness/token` (mode `0600`).
  - If the token file exists, every request must carry
    `Authorization: Bearer <token>`; missing/wrong token → `401`.
  - If `DFH_AGENT_TOKEN` is set, it overrides the file (useful for tests /
    single-user setups that want a known token).
  - If neither is set and the user explicitly passes `--no-auth`, the daemon
    runs token-free (localhost-only still applies). Default is token-on.
  - The token is a local secret, not a security boundary against the machine
    owner: anyone with read access to the user's home can read it. Document
    that honestly; do not oversell it.
- **No TLS** on localhost (no benefit; adds cert management). Revisit only
  if remote binding is ever requested.
- The daemon must refuse to start if the configured port is already in use
  by something else, and must log the effective bind address + auth mode on
  startup.

### 3.4 Daemon lifecycle (start / stop)

- `dfh start [--port N] [--df-port N] [--ascii]`
  - Launches DF if the RPC port does not answer (sets `DFHACK_PORT`,
    waits up to 90 s for the port, same pattern dfkit uses).
  - Starts the harness daemon (or attaches to an already-running one and
    reports `{"started": false, "reason": "already running"}`).
  - Writes a PID file + port file under
    `~/.config/df-agent-harness/` (or `$XDG_RUNTIME_DIR` if set).
  - `--ascii` swaps `data/init/init.txt` for a plain-curses profile for
    readable `screen` output (dfkit's `init-agent.txt` pattern; our own
    profile file, written from scratch), restoring the original on stop.
- `dfh stop` — stops the daemon (drain + flush journal first), then tells DF
  to quit via RPC `RunCommand("die")`; restores the graphics profile if one
  was swapped. Never `kill -9` DF while a save is in flight.
- `dfh status` — daemon state + DF reachability + game version, as JSON.
- `dfh daemon` — run the daemon in the foreground (for `systemd --user`,
  tmux, or debugging). A user systemd unit is a later convenience, not
  phase 1.
- Ports: DFHack RPC default **5001** (`DFHACK_PORT`; dfkit precedent — 5000
  is commonly taken), agent HTTP default **127.0.0.1:8765**. Both
  overridable by flag/env. Verify 8765 is free on Mikey's machine in phase 1.
- The daemon is the **only** process that opens the DFHack RPC connection.
  The CLI and any agent talk to the daemon over HTTP; they never touch the
  RPC port directly. This is what makes the single-connection assumption
  safe.

---

## 4. Agent-facing API (v1)

Base: `http://127.0.0.1:8765/v1`. All bodies JSON. All responses JSON.
`Content-Type: application/json` throughout. Times are Unix epoch seconds
(`at`) plus in-game time (`tick`, `year`) where relevant.

### 4.1 Conventions

- **Envelope (reads):** the resource object directly (no wrapper), plus
  `"meta": {"tick": …, "year": …, "paused": …}` where the value is a
  live snapshot.
- **Envelope (actions):** always `{"ok": bool, "action": "<name>",
  "detail": "<human sentence>", "evidence": {...}|null, "took_ms": …}`.
  `ok: false` with HTTP 200 means the action ran but verification failed
  (precondition missing, effect not observed) — see §6.
- **IDs:** `seq` (monotonic event sequence, SSE `id:` field) for events;
  game ids (`unit_id`, `building_id`, `job_id`) are DF's own integers.
- **Coordinates:** `[x, y, z]` arrays, tile coordinates unless a field says
  `block`. Boxes are `{"x0":…,"y0":…,"z0":…,"x1":…,"y1":…,"z1":…}` inclusive
  in tile space (the daemon converts to RFR block coords + exclusive `max_z`).
- **Pagination:** list endpoints accept `?limit=` (default 100, max 1000)
  and `?cursor=` (opaque, from `meta.next_cursor`).

### 4.2 Read-only state queries

| Method | Endpoint | Returns |
|---|---|---|
| GET | `/v1/health` | `{"ok": true, "daemon": "…", "df_reachable": bool, "version": {…}, "busy": bool}` — no auth required (liveness only). `busy` is true while another RPC call holds the lock (health never blocks on it); `df_reachable` is then the poller's last-known state, or false when there is none. |
| GET | `/v1/state` | Full snapshot: versions, mode/viewscreen, pause, date, population, food/drink/wood, threats, jobs, buildings summary, recent reports. The "one call to orient" endpoint. |
| GET | `/v1/status` | Compact status (same fields as the Lua `status` probe: viewscreen, game_mode, paused, year, year_tick, population, dwarves, idlers, animals, threats, food, drink, wood, jobs, wounded, dead, citizens[], threat_list[]) |
| GET | `/v1/units?limit=&citizens_only=` | Unit list (id, name, race, profession, pos, job, health flags, mood/stress where available) |
| GET | `/v1/units?kind=citizens&fresh=1` | Same list, but from a fresh FULL units collect instead of the poller's lite cache. The lite records omit needs, the wounds list, relations, labors, skills, sex, age, and goals — not enough for a per-dwarf sample. The M1 driver fetches this at run start and run end for the diary feed. A fresh collect is a paused read, so it is safe while the game is paused; it costs ~1 s. |
| GET | `/v1/unit/{id}` | One unit, full detail |
| GET | `/v1/map` | Map size, world/save names, embark info |
| GET | `/v1/blocks?x0=&…&z1=` | Raw block tiles for a region (tile shapes, water/magma, designations) |
| GET | `/v1/scan?shape=wall&x0=&…` | Tiles of a given shape in a box |
| GET | `/v1/buildings` | Workshops/furnaces/beds/farms, manager flag, manager orders |
| GET | `/v1/jobs?limit=` | Queued jobs (type, pos, worker, wait timer) |
| GET | `/v1/items?name=` | Item/material counts (supports the `status` food/drink accounting) |
| GET | `/v1/reports?limit=` | Announcements + combat reports (text, pos, announcement flag, repeat count) |
| GET | `/v1/screen` | Current screen as text rows (only meaningful with the ASCII profile) |
| GET | `/v1/cursor` | Current map cursor `[x, y, z]` |
| GET | `/v1/journal?limit=&kind=` | Daemon journal (decisions, actions, events) — the audit trail |
| GET | `/v1/goals` | Goal list + satisfaction state |
| GET | `/v1/tasks` | Task registry (name, description, preconditions, dry-run plan) |

**`GET /v1/state` response schema (v1):**

```json
{
  "version": {"df": "0.47.05", "dfhack": "0.47.05-r5", "rfr": "…"},
  "mode": "fortress",
  "viewscreen": "dwarfmode",
  "paused": true,
  "year": 125, "year_tick": 123456,
  "population": 7, "dwarves": 7, "idlers": 2, "animals": 3,
  "threats": 0, "threat_list": [],
  "food": 42, "drink": 18, "wood": 30,
  "jobs": 5, "wounded": 0, "dead": 0,
  "citizens": [{"id": 1, "name": "…", "pos": [x, y, z], "idle": true, "job": null}],
  "buildings": {"summary": {"carpenter": 1, "still": 0}, "manager": false},
  "reports_tail": [{"text": "…", "pos": [x, y, z], "announcement": true}],
  "meta": {"tick": 123456, "generated_at": 1764020000, "took_ms": 120}
}
```

**`GET /v1/unit/{id}`** returns the RFR `UnitList` entry for the unit plus
Lua-enriched fields (`mood`, `stress`, `hunger/thirst`, `wounds`,
`current_job`, `labors`) as they become available in phase 1. Fields that
are not yet implemented are omitted, never invented.

### 4.3 Verified actions

Every action is **precondition-checked, executed, then verified by re-reading
game state**. A success means "verified in the game", never "command sent".
Each returns the §4.1 action envelope; `evidence` carries the before/after
read-back (ids, counts, positions).

| Method | Endpoint | Body | Verifies |
|---|---|---|---|
| POST | `/v1/actions/pause` | `{"paused": true|false}` | `GetPauseState` equals the request (with the space-key fallback if the flag does not stick — see §1.2) |
| POST | `/v1/actions/dig` | `{"tiles": [[x,y,z],…], "mode": "dig"\|"channel"\|"ramp"\|…}` or `{"box": {...}, "mode": …}` | designation count in the box via a count probe |
| POST | `/v1/actions/undesignate` | `{"box": {...}}` | designations cleared in the box |
| POST | `/v1/actions/build` | `{"kind": "carpenter"\|"still"\|… , "pos": [x,y,z], "width":…, "height":…}` | building count rose and the new building id exists |
| POST | `/v1/actions/deconstruct` | `{"building_id": N}` | building gone (uses `dfhack.buildings.deconstruct` result) |
| POST | `/v1/actions/stockpile` | `{"box": {...}, "types": ["food","wood",…], "template_id": N?}` | new stockpile id + type flags |
| POST | `/v1/actions/order` | `{"job_type": "…", "count": N?, "reaction": "…"?}` | manager order record exists |
| POST | `/v1/actions/queue-job` | `{"building_id": N, "job": "…", "reaction": "…"?}` | workshop job id appears in the job list (job must also be inserted into `building.jobs` — `linkIntoWorld` alone never dispatches) |
| POST | `/v1/actions/labor` | `{"name": "MINING", "on": true, "unit_ids": […]?}` | number of dwarves whose labor changed |
| POST | `/v1/actions/discard-job` | `{"job_id": N}` | releases the items the stale job held (never frees the job struct) |
| POST | `/v1/actions/key` | `{"keys": ["down","enter",…]}` | best-effort only (no read-back possible); returns the resulting viewscreen so the caller can verify the menu changed |
| POST | `/v1/actions/cursor` | `{"pos": [x,y,z]}` | cursor read-back |
| POST | `/v1/actions/lua` | `{"code": "…"}` | **Guarded** (§4.5): returns `{ok, text}` — the raw Lua escape hatch, for development and for actions with no typed endpoint yet |
| POST | `/v1/actions/command` | `{"command": "quicksave", "args": […]}` | **Guarded** (§4.5): runs a DFHack console command, returns `{ok, text}` |

**Composed tasks** (multi-step, with honest blocking reasons and dry runs):

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/v1/tasks/{name}/plan` | Dry-run plan only (steps + preconditions), no execution |
| POST | `/v1/tasks/{name}` | `{"dry_run": false, "wait": 60}` — run, verify the end effect (e.g. brew → a **new drink stack** exists; total drink is unreliable because dwarves drink concurrently) |
| POST | `/v1/tasks/{name}/cancel` | Cancel a running task (phase 2+) |

Initial task registry (phase 2, grows from the verified action layer):
`brew`, `cook`, `gather`, `build-still`, `build-carpenter`, `build-kitchen`,
`food-stockpile`, `autolabor`, `ensure-drink`, `ensure-food`.

**Goals** (persistent conditions with a task attached; daemon pursues them):

| Method | Endpoint | Notes |
|---|---|---|
| POST | `/v1/goals` | `{"name": "…", "expression": "drink >= 40", "task": "brew", "priority": 6}` |
| GET | `/v1/goals/{id}` | Goal + current variable values + satisfied? |
| POST | `/v1/goals/{id}/done` | Mark done (manual) |
| DELETE | `/v1/goals/{id}` | Remove |

Goal expressions evaluate over live variables (`drink`, `food`, `population`,
`idlers`, `threats`, `brewable_plants`, `empty_barrels`, `plants`,
`stockpiles`, any inventory count in lower case). Planner: highest priority
unsatisfied goal first, 3-minute backoff after a failed attempt so one
impossible goal cannot starve the rest (dfkit's rule, adopted).

### 4.4 Control

| Method | Endpoint | Notes |
|---|---|---|
| POST | `/v1/control/pause` | Same as `/v1/actions/pause` (alias for the daemon loop) |
| POST | `/v1/control/quicksave` | `RunCommand("quicksave")`; returns save confirmation |
| GET | `/v1/control/daemon` | Daemon state: tick count, last tick duration, journal size, event seq, uptime |
| POST | `/v1/control/daemon/pause` | Pause the autonomous loop (game keeps running; agent still gets events + reads) |
| POST | `/v1/control/daemon/resume` | Resume the autonomous loop |

### 4.5 The guarded endpoints (`/lua`, `/command`)

`POST /v1/actions/lua` and `/v1/actions/command` are arbitrary code
execution inside the game — the same power as DFHack's console. They exist
because no typed API covers everything (and never will), but:

- They are **disabled by default** in autonomous mode; enable with
  `dfh start --allow-raw` or config `allow_raw_actions: true`. The daemon
  logs every raw call with the caller's token id (if any) and the code.
- The daemon loop itself never uses them; tasks/actions use typed paths.
- An agent should prefer a typed endpoint; if none exists, it should say so
  in its reasoning and use `/lua` as a named, logged step — not silently.
- Phase 1 may run with them on (observation needs Lua probes); phase 2+
  tightens as typed endpoints land.

---

## 5. Events (push channel)

### 5.1 How events are produced

Two sources, merged by the daemon into one ordered stream:

1. **In-game push (primary):** a Lua watcher script (ours, written from
   scratch) registers `plugins.eventful` handlers and appends one JSON object
   per line to a file under the DF directory (e.g.
   `df_linux/dfh-events.jsonl`). Handlers (from the eventful API available
   at 0.47.05-r5): `JOB_COMPLETED`, `UNIT_DEATH`, `REPORT`, `INVASION`,
   `NEW_UNIT_ACTIVE`, plus whatever else eventful exposes at this tag
   (verify in phase 1 — see §8). The daemon drains the file by byte offset
   (stored in SQLite), so events survive daemon restarts and are never
   double-delivered.
2. **Poll-diff (fallback + coverage):** the daemon polls compact status
   (every N seconds, default 2 s when unpaused, 10 s when paused) and
   `GetReports`, diffing against the previous poll: new/threatening units,
   citizens appearing/vanishing, mode/pause/year changes, new reports.
   This covers everything eventful misses (e.g. dwarf distress derived
   from unit state) and keeps working if the watcher script fails to load.

Both paths feed the same event log (SQLite `events` table + in-memory ring).
Every event gets a monotonic `seq` assigned by the daemon — the ordering
guarantee is the daemon's, not the game's.

### 5.2 Delivery: SSE

```
GET /v1/events
Accept: text/event-stream
```

- Long-lived stream. Each event is one SSE message:
  `id: <seq>` + `data: {json}` + blank line. A `:heartbeat` comment every
  30 s keeps the connection alive through proxies.
- `GET /v1/events?since=<seq>` replays missed events from the SQLite log,
  then continues live. `Last-Event-ID` header is honored the same way.
- `GET /v1/events?limit=N` (without SSE) returns the N most recent events
  as a JSON array — the poll fallback for clients that cannot hold an SSE
  connection.
- The daemon **pauses the game** on `invasion` / `hostile_spawn` (critical)
  before any task runs — same policy dfkit's daemon uses — and emits the
  event first so the agent sees why the game paused.

### 5.3 Event envelope

```json
{
  "seq": 1042,
  "id": "evt-1042",
  "type": "threat",
  "severity": "critical",
  "tick": 123456,
  "year": 125,
  "at": 1764020123,
  "source": "eventful",
  "data": {"unit_id": 88, "name": "Goblin thief", "pos": [98, 102, 174]}
}
```

- `severity`: `info` | `notice` | `warning` | `critical`.
- `source`: `eventful` | `poll` | `daemon` | `task`.
- `tick`/`year` are in-game time at detection; `at` is wall-clock.
- Unknown future event types must be ignored by consumers (forward
  compatibility); the daemon never renames a type, only adds new ones.

### 5.4 Event catalog (v1 — initial list)

| Type | Severity | Source | Data | Meaning |
|---|---|---|---|---|
| `daemon_started` / `daemon_stopped` | info | daemon | `{version, pid}` | Daemon lifecycle |
| `state` | info | poll | full compact status | Initial snapshot on (re)connect |
| `mode` | info | poll | `{viewscreen, game_mode}` | Menu/mode changed |
| `pause` | notice | poll | `{paused}` | Pause state changed |
| `year` | info | poll | `{year}` | In-game year rolled over |
| `citizen_new` | info | poll | `{unit_id, name, pos}` | Migrant / birth / new citizen |
| `citizen_gone` | notice | poll | `{unit_id, name, pos}` | Citizen left the active list (death, departure — check `unit_death`) |
| `threat` | critical | poll | `{unit_id, name, pos}` | Hostile unit newly visible |
| `invasion` | critical | eventful | `{race}` | Invasion event fired (game pauses) |
| `hostile_spawn` | critical | eventful | `{unit_id, name}` | Hostile unit became active (game pauses) |
| `unit_death` | warning | eventful | `{unit_id, name, citizen}` | Any unit died; `citizen` flags dwarves |
| `dwarf_distress` | warning | poll | `{unit_id, name, kind, detail}` | `kind`: `starving` \| `thirsty` \| `exhausted` \| `unhappy` \| `wounded` \| `tantrum_risk` — derived from unit state; thresholds defined in phase 3, not guessed here |
| `report` | notice | eventful/poll | `{text, pos, announcement, repeat}` | Announcement / combat report text |
| `job_cancelled` | warning | poll | `{text}` | A report containing "cancels" — the early warning for blocked production |
| `job_completed` | info | eventful | `{job_type, reaction}` | A job finished |
| `task_completed` / `task_failed` | notice / warning | daemon | `{task, detail, evidence}` | A composed task finished or failed verification |
| `goal_satisfied` | notice | daemon | `{goal_id, name}` | A goal's expression became true |
| `save` | info | daemon | `{}` | Quicksave completed |
| `daemon_error` | critical | daemon | `{error, context}` | RPC lost, Lua probe failed, journal write failed — the daemon is degraded |

`dwarf_distress` kinds and thresholds are **deliberately unspecified** until
phase 3 measures real unit state (stress, hunger, thirst, wounds) on a live
fort. Do not invent thresholds in phase 1.

---

## 6. Error model

HTTP status + JSON body, always:

```json
{"error": {"code": "GAME_NOT_RUNNING", "message": "DFHack RPC is not reachable on 127.0.0.1:5001", "detail": {"port": 5001}}}
```

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `BAD_REQUEST` | Malformed JSON, unknown field, bad coordinates, unknown action/task/goal name |
| 401 | `UNAUTHORIZED` | Missing/wrong bearer token (when auth is on) |
| 404 | `NOT_FOUND` | Unknown endpoint, unknown unit/building/job/goal id |
| 409 | `PRECONDITION_FAILED` | Action preconditions not met (no workshop, no plants, no empty barrel…). Returned as an action envelope with `ok: false` when the call is an action POST; as an error body otherwise |
| 422 | `VERIFICATION_FAILED` | Action executed but the effect was not observed on re-read (action envelope, `ok: false`, `evidence` shows before/after) |
| 502 | `RPC_ERROR` | DFHack RPC call failed (`CR_*` code in `detail`, plus any TEXT output) |
| 503 | `GAME_NOT_RUNNING` | RPC port not answering / DF not loaded / wrong game mode for the call |
| 504 | `TIMEOUT` | RPC or Lua probe exceeded its deadline (default 20 s) |
| 500 | `INTERNAL` | Daemon bug — journal it, include a `request_id` |

Rules:

- **Transport failure ≠ action failure.** A 502/503/504 means "we don't know
  what the game did" — the caller must re-read state before retrying, never
  blindly retry a mutation. A 200 with `ok: false` means "we know it didn't
  work" — safe to plan around.
- Every error response carries a `request_id` (logged server-side with the
  full context).
- Lua probe failures return `502 RPC_ERROR` with the Lua error text in
  `detail.lua_error`; the daemon never lets a Lua error crash the HTTP server.
- Rate limits: none in v1 (localhost, single agent). If a second agent
  hammers the daemon, the daemon serializes RPC calls; slow calls are the
  backpressure. Revisit only if abuse is observed.

---

## 8. Open questions — to verify in phase 1

### Resolved in phase 1 (2026-11-25, live, DFHack **0.47.05-r8**)

The installed server is r8, not r5 (SETUP.md is correct; the r5
references elsewhere in this doc are the tag the protocol was read
from — the wire protocol is unchanged). Verified on the fort Athelunol
(region1), see `docs/OBSERVE.md` for the full list:

1. **Framing byte-exactness — CONFIRMED.** The 8-byte header
   (`<hhi`) and 12-byte handshake are accepted by the real r8 server;
   `GetVersionInfo` returns DF 0.47.05 / DFHack 0.47.05-r8 / RFR 0.21.0.
2. **`DFHACK_PORT` precedence — NOT TESTED.** The game runs on the
   default port 5000; no reason to move it was found. Still open.
3. **Concurrent RPC connections — NOT TESTED.** The harness still
   assumes one connection (the observe CLI opens one connection per
   invocation and closes it; no second concurrent client was tried).
4. **Script path for Lua helpers — RESOLVED DIFFERENTLY.** Helpers are
   not installed into the DF tree at all: the Python side reads the
   `.lua` files from the repo and sends them as `RunCommand("lua",
   <code>)` arguments. No copy/symlink/script-path setup needed.
5. **`RunLua` vs `lua` command — CONFIRMED for `lua`.** `RunCommand
   ("lua", code)` returns printed output via TEXT notifications
   exactly as designed. `RunLua` was not used and remains untested.
   **New finding:** TEXT fragments whose bytes are not valid UTF-8
   (CP437 dwarf names) arrive from the protobuf runtime as `bytes`,
   not `str` — the client now decodes each fragment with
   `decode_df_string` (UTF-8 if valid, else CP437). Regression test in
   `tests/test_client.py`.
6. **Eventful coverage — NOT TESTED.** Deferred to phase 3.
7. **RFR read-back quirks — PARTIALLY CONFIRMED.** `GetMapInfo`
   returns 12×12 blocks (192×192 tiles), 58 z-levels; `GetViewInfo`
   returns view/cursor (cursor is -30000 when unset); `GetVersionInfo`
   field contents verified (see 1). `CopyScreen` column-major layout
   and `BlockRequest` exclusive `max_z` were **not** exercised —
   observation uses Lua, not RFR map reads, in phase 1.
8. **Pause behaviour — CONFIRMED.** `SetPauseState(true)` pauses and
   sticks (re-read via `GetPauseState`); the space-key fallback was
   not needed. Note the game starts **unpaused** after embark — the
   harness must pause it explicitly.
9. **Port 8765 — NOT TESTED.** No HTTP daemon exists yet (phase 4).
10. **Headless DF + RPC under Xvfb — CONFIRMED.** RPC comes up on
    127.0.0.1:5000 the same way headless; `dfhack-run` agrees with our
    client about the port.
11. **`dwarf_distress` thresholds — NOT DEFINED.** Raw
    `counters2` hunger/thirst/sleepiness timers are reported; what
    values mean hungry/thirsty/exhausted is still unknown.
12. **Save/load and the daemon — PARTIALLY OBSERVED.** `quicksave`
    writes `data/save/region1/world.sav` (and `data/save/current/
    world.sav`); **while a quicksave is writing, the RPC server stops
    answering for ~30-40 s** (calls time out; the collector records
    section errors and survives). Reconnect behaviour across
    save/load is still untested.

### Original open questions

1. **RPC framing byte-exactness.** The reference client sends an 8-byte
   header (`<hhi`: id, pad, size) while `RPCMessageHeader` is declared as
   6 bytes (`int16 id; int32 size`). Confirm the 8-byte framing against the
   live 0.47.05-r5 server before writing our client — a wrong header size
   fails every call.
2. **`DFHACK_PORT` precedence.** The 50.x docs say the env var beats
   `remote-server.json`; dfkit relies on it (port 5001). Confirm on the
   0.47.05-r5 server that setting `DFHACK_PORT=5001` actually moves the port.
3. **Concurrent RPC connections.** Unverified whether the server accepts more
   than one client at a time. Design assumes one connection; verify by
   opening a second connection while the first is alive.
4. **Script path for Lua helpers.** Confirm whether DFHack 0.47.05-r5 picks
   up `hack/scripts/agent/*.lua` from a copied folder, a symlink, or a
   configured script path — and which one survives a clean install.
5. **`RunLua` vs `lua` command.** Confirm `RunCommand("lua", code)` returns
   printed JSON via TEXT notifications exactly as dfkit relies on, and that
   `RunLua` is module-function-only (per its proto) and not a code-eval path.
6. **Eventful coverage at 0.47.05-r5.** Confirm which `eventful.eventType`
   values exist and fire in fortress mode (`JOB_COMPLETED`, `UNIT_DEATH`,
   `REPORT`, `INVASION`, `NEW_UNIT_ACTIVE` per dfkit; check for
   job-cancel / mood / siege-specific events). dfkit observed `job_completed`
   but not a live invasion/report capture — we must trigger and observe one.
7. **RFR read-back quirks.** Re-confirm on a live fort: `CopyScreen`
   column-major layout, `BlockRequest` block coords + exclusive `max_z`,
   `GetUnitList` cost on a large fort, `GetVersionInfo` field contents.
8. **Pause behaviour.** Confirm `SetPauseState` + the post-load re-assert
   and the space-key fallback on our build.
9. **Port 8765.** Confirm nothing on Mikey's machine already listens there;
   pick another default if so.
10. **Headless DF + RPC under Xvfb.** The environment worker owns this; the
    protocol side needs only: does the RPC port come up the same way headless,
    and does `dfhack-run` agree with our client about the port?
11. **`dwarf_distress` thresholds.** Do not define until phase 3 measures
    real stress/hunger/thirst/wound values.
12. **Save/load and the daemon.** What happens to the RPC connection across
    `quicksave`, world load, and embark? Define reconnect behaviour from
    observation, not assumption.

---

## Appendix A. Sources

- DFHack remote interface (published docs, 50.10-r1):
  https://docs.dfhack.org/en/50.10-r1/docs/dev/Remote.html
- DFHack repo, tag `0.47.05-r5` (`github.com/DFHack/dfhack`):
  `library/include/RemoteClient.h`, `library/RemoteServer.cpp`,
  `library/proto/CoreProtocol.proto`, `library/proto/Basic.proto`,
  `plugins/proto/RemoteFortressReader.proto`,
  `plugins/eventful.cpp`, `plugins/lua/eventful.lua`,
  `library/dfhack-run.cpp`
- dfkit (read-only reference, no code copied):
  https://github.com/nordicnode/dfkit — `README.md`, `docs/FRAMEWORK.md`,
  `docs/PLAYBOOK.md`, `dfhack_client.py`, `dfagent.py`, `dfkit/daemon.py`,
  `dfkit/events.py`, `lua/agent/watch.lua`, `lua/agent/status.lua`
- Third-party Python client (evaluated, rejected as unmaintained):
  https://github.com/McArcady/dfhack-client-python (2021, 3 commits, 8 stars)
- Dwarf Fortress Wiki, "DFHack — Remote API" section (no-change-notification
  note): https://dwarffortresswiki.org/index.php?title=Utility:DFHack

## Appendix B. Glossary

- **RFR** — RemoteFortressReader, the DFHack plugin exposing map/units/screen
  over RPC.
- **BindMethod** — core RPC (id 0) that resolves a method name to a numeric id.
- **RunCommand** — core RPC (id 1) that runs a DFHack console command
  (including `lua <code>`).
- **eventful** — DFHack plugin exposing in-game event hooks to Lua.
- **SSE** — Server-Sent Events, one-way text/event-stream push over HTTP.
- **Verified action** — an action whose effect was re-read from game state
  after execution; success means "observed in the game".

## Model presentation

This section is required by the 2026-11-27 presentation constraint
(GOAL.md, coordinator log 2026-11-27 ~17:47 PT): every new system
must state how its information reaches the model, what it costs,
and what it deliberately does not push. The snapshot stays an
index: counts, exceptions, and diffs only, about 4,700 tokens
typical, never a replacement for full state. Budgets hold (target
30K, warning 60K, compaction 100K, hard cap 140K on a 200K
window), enforced by the assembler's token accountant with its
cut order. No system bolts its own dump onto the snapshot.

### Snapshot: the protocol is the wire, not a section

The protocol (§3 Decision, §4 Agent-facing API) is handed to the
model once at session start, not pushed per tick. The per-tick
snapshot is the protocol's payload: the state, the suggestion,
and the failure feedback, in the shape §4 specifies. There is no
per-tick protocol section, because the protocol does not change
tick to tick. The protocol version is carried with the snapshot
so the model can tell when the shape changes.

**Token cost.** At 7 dwarves and at 50 dwarves alike, the
protocol costs 0 tokens in the snapshot: there is no protocol
section to render. The one-time cost of handing the protocol to
the model at session start is the protocol text itself, measured
once, not per tick; that size is UNVERIFIED against the
accountant. It does not grow with population, because the
protocol does not grow with the fort.

### Query route: GET /v1/catalog (live) and the v1 API (§4)

The agent-facing API (§4) is the query surface: GET /v1/catalog
for what the model can do, GET /v1/snapshot for the state, the
per-system detail routes for choosing, POST /v1/actions/ for
acting, and the SSE push channel (§5 Events) for being pinged
the moment something happens. The error model (§6) types every
failure: a failure names what failed and why in plain words.

### Briefing: the protocol carries briefings, it is not one

Briefings arrive over the same wire, fired by events, each a few
hundred tokens at most, fired once when the event starts. The
protocol's job is to deliver the briefing text faithfully, with
its trigger and its cost stated in the system doc that owns the
event. The protocol never invents briefing text and never
rewords it.

### Opportunities: none from this layer

The protocol does not suggest. The opportunities section carries
at most 3 entries per tick from the system docs, each facts plus
a query route. The protocol delivers them; it does not choose
them.

### What the system deliberately does NOT push, and why

- **The transport internals.** The DFHack remote protocol (§2)
  is transport, not model input. The model sees the v1 API. The
  bytes on the wire are harness implementation.
- **The full API per tick.** The API is handed once at session
  start and queried through the catalog. Pushing it every tick
  would be a dump of a document that does not change.
- **Unverified capabilities.** An action or route the harness
  cannot verify live is not in the catalog. The protocol
  presents only what the harness can actually do. (Note the
  drift LABOR.md §3.4 records: PROTOCOL.md lists `autolabor`
  in the task list, but no autolabor-like system exists in
  Urist. That claim must be removed from the task list; the
  presentation never promises a capability the harness does
  not have.)
- **Raw error text.** Errors are typed (§6). Raw DFHack error
  text is logged, never pushed.
