# MCP server

Urist as native tools for any MCP client, so a Freebuff agent on
Mikey's own machine gets the harness through Freebuff's
`.agents/mcp.json` instead of through raw HTTP calls. The HTTP API
stays the underlying transport: the MCP server is a thin translation
layer, not a second harness. It adds no game-driving logic and no
new snapshot format. Every tool maps onto an existing HTTP route.

Status: design written 2026-11-27, implementation in
`src/dfagent_harness/mcp/`. UNVERIFIED marks below name the live
proof each claim still needs.

## 1. The six tools, exactly

Six tools, no more, no fewer. The evidence for the cap is the
2026-11-25 research (GOAL.md step 8): tool-choice accuracy
degrades measurably past about 30 tools, so the breadth lives in
the catalog, which the agent reads on demand, and the tool surface
stays small. One tool per action would be dozens. Enums stay OUT
of every tool schema: legal values resolve through `catalog` at
decision time, so the schemas can never go stale.

| Tool | What it does | HTTP route | Call pattern |
|---|---|---|---|
| `observe` | The per-tick snapshot: diffs, attention, index. The only tool called every tick. | `GET /v1/snapshot` | Every tick |
| `act` | One catalog action by name plus parameters. Validates against the catalog first; errors name the legal values. | `GET /v1/catalog/<name>` then `POST /v1/actions/<name>` (or `POST /v1/tasks/<name>` for `task:` names) | When the agent decides to do something |
| `query` | Pull any state by route: units, buildings, stocks, jobs, slices, columns, overview, areas, survey, sites, attention. | `GET <route>` | When the snapshot only indexes the detail |
| `catalog` | Search or list the action catalog and its legal values; full schemas only for named actions. | `GET /v1/catalog`, `GET /v1/catalog/<name>` | When the agent does not know how to do something |
| `wiki_search` | Hybrid keyword plus semantic wiki lookup over the local DF wiki export; full page read by slug. | `GET /v1/wiki?q=&mode=&limit=`, `GET /v1/wiki/<slug>` | When the agent does not know how DF works |
| `journal` | Decision journal, failure records, and the diary: the memory-retrieval path. | `GET /v1/journal?limit=&kind=`, `GET /v1/diary` | When the agent needs what happened before |

`goals` is data returned by `observe` and `query`, not a tool.
Events fold into `observe` where possible; there is no separate
event tool. The daemon owns the clock and agent tools never
include pause or unpause: `observe` never pauses the game, and
`act` never touches the daemon loop.

## 2. Transport: stdio, NDJSON JSON-RPC

The server speaks the MCP protocol over stdio: newline-delimited
JSON-RPC 2.0 on stdin and stdout, one message per line. Nothing
but protocol messages goes to stdout; diagnostics go to stderr.

Why stdio and not HTTP: the client spawns the server as a local
command (Freebuff `.agents/mcp.json`), which is the standard MCP
shape for a same-machine tool, and it keeps the server decoupled
from the daemon process. The daemon stays the only process that
touches the game. The server talks to the daemon over HTTP and
holds no game state of its own.

Why no `mcp` package: the repo is stdlib plus protobuf only, and
no MCP library is installed in the venv. The protocol surface the
server needs is small (initialize, tools/list, tools/call, ping),
so it is implemented by hand in `protocol.py` with the stdlib
`json` module. If a future MCP feature needs the full SDK, that
is a dependency decision for Mikey, not a silent install.

Protocol versions accepted: `2025-06-18` and `2024-11-05`.
The server echoes the client's version when it is one of those;
otherwise it answers with `2025-06-18` and the client decides
whether to proceed. Server name is `urist`, version `0.1.0`.

## 3. Tool schemas

Schemas are JSON Schema objects, written out in `tools.py` next
to the dispatch code so they cannot drift from what the tools
accept. No schema carries an `enum`: legal values are described
in words and resolved through `catalog` (for actions) or stated
in the description (for wiki modes and journal kinds).

### observe

No parameters. Returns the assembled snapshot exactly as
`GET /v1/snapshot` returns it: sections, attention, the
suggestion, token cost. The snapshot is an index, not a dump
(about 4.7K tokens typical); full detail comes through `query`.

```json
{"type": "object", "properties": {}, "additionalProperties": false}
```

### act

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "description": "A catalog action name, for example build_workshop, queue_job, designate_dig, or a composed task as task:brew. Look it up with the catalog tool first; the catalog is the only source of legal names."
    },
    "parameters": {
      "type": "object",
      "description": "The action parameters, exactly as the catalog describes them for this action. Omit when the action takes none."
    }
  },
  "required": ["action"],
  "additionalProperties": false
}
```

The server validates the name against the catalog before
calling anything: `GET /v1/catalog/<name>`. An unknown name
fails with the error the catalog route returns, which names the
legal actions and tasks. A `task:<name>` name goes to
`POST /v1/tasks/<name>` with no parameters; anything else goes
to `POST /v1/actions/<name>` with the parameters as the body.
The action envelope comes back unchanged (`ok`, `action`,
`detail`, `evidence`, `took_ms`); a failed action carries its
`fix` field, the corrective action plus what it needs.

The guarded raw actions (`lua`, `command`) stay guarded: they
are refused unless the daemon was started with raw actions
allowed, exactly as the HTTP route refuses them. The MCP server
adds no bypass.

### query

```json
{
  "type": "object",
  "properties": {
    "route": {
      "type": "string",
      "description": "A read-only /v1/ route, for example /v1/units?kind=citizens, /v1/sites?kind=workshop, /v1/column?x=97&y=97. Use it when the snapshot only indexes the detail you need."
    }
  },
  "required": ["route"],
  "additionalProperties": false
}
```

Only read-only routes are accepted. The allowlist is the
read-only GET routes except the ones other tools own: `/v1/state`,
`/v1/status`, `/v1/units`, `/v1/unit/<id>`, `/v1/buildings`,
`/v1/stocks`, `/v1/jobs`, `/v1/items`, `/v1/reports`,
`/v1/map`, `/v1/wealth`, `/v1/slice`, `/v1/column`,
`/v1/overview`, `/v1/areas`, `/v1/area/<id|name>`, `/v1/path`,
`/v1/survey`, `/v1/sites`, `/v1/attention`, `/v1/cursor`,
`/v1/pause`. A route that belongs to another tool (`/v1/snapshot`,
`/v1/catalog`, `/v1/journal`, `/v1/diary`, `/v1/wiki`) is
refused with a message naming the right tool. Anything that is
not a GET, or not under `/v1/`, is refused. The SSE event stream
(`/v1/events`) is not a query route.

### catalog

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "description": "One action name to describe in full, for example queue_job. Omit to list the whole catalog."
    },
    "search": {
      "type": "string",
      "description": "Filter the catalog by a word in the name or description, for example brew. Ignored when action is given."
    }
  },
  "additionalProperties": false
}
```

With neither argument, returns the full catalog: every action
with its parameters, constraints, and example call, plus the
composed tasks and the query routes. With `action`, returns that
one action's description (or the catalog route's 404, which
names the legal values). With `search`, returns the matching
actions only, with a count.

### wiki_search

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "The question in plain words, for example how does brewing work."
    },
    "mode": {
      "type": "string",
      "description": "search is the fast keyword fallback, hybrid is the default and best for vague questions, semantic is vector-only, title matches page titles. Omit for hybrid."
    },
    "limit": {
      "type": "integer",
      "description": "Max results, default 5, clamped to 1-10."
    },
    "page": {
      "type": "string",
      "description": "A wiki page slug to read in full, for example brewing. When given, query is ignored and the whole page is returned."
    }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

`query` is required even when `page` is given, because the MCP
schema cannot express "required unless page": the server ignores
`query` when `page` is present but still requires the field to
be present, and says so in the error when it is missing. An
invalid mode is refused with the four legal modes named.

### journal

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "description": "Max decisions returned, default 100, clamped to 1-1000."
    },
    "kind": {
      "type": "string",
      "description": "Filter by decision domain: threat, needs, nobles, production, expansion. Omit for all domains."
    },
    "source": {
      "type": "string",
      "description": "decisions (the default) returns the decision journal with per-domain counts; diary returns the diary entries from diary.md. Omit for decisions."
    }
  },
  "additionalProperties": false
}
```

Failure records are decisions with `ok` false; the journal
result keeps the `ok` and `result` fields on every decision, so
a client finds failures by filtering on them. An invalid `kind`
is refused with the five legal domains named; an invalid `source`
is refused with the two legal sources named.

## 4. Auth

The server talks to the daemon with the same bearer token the
daemon itself uses: `~/.config/df-agent-harness/token` (0600),
or `DFH_AGENT_TOKEN` when set, or the file named by
`DFH_TOKEN_FILE`. The daemon URL is `http://127.0.0.1:8765`
unless `DFH_DAEMON_URL` is set. On startup the server reads
the token and checks `GET /v1/health`; if the token is missing
or the daemon does not answer, it exits with a clear stderr
message and a non-zero status instead of starting and failing
every call. That is a hard error, never a silent stall.

The MCP client is trusted the way any local process is trusted:
it runs on the same machine and spawns the server. The server
binds nothing and listens on no port; the only network traffic
is its own HTTP calls to the daemon on loopback.

## 5. Error model

Two layers, kept apart:

- JSON-RPC errors, for protocol problems only: `-32700` parse
  error (a line that is not JSON), `-32600` invalid request (a
  JSON value that is not a request object, or a missing method),
  `-32601` method not found (anything that is not `initialize`,
  `ping`, `tools/list`, or `tools/call`), `-32602` invalid
  params (a `tools/call` for an unknown tool, or arguments that
  fail the schema). The server never crashes on a bad message:
  every line gets either a response or nothing (notifications
  get no response).
- Tool errors, for everything else: a normal `tools/call`
  result with `isError: true` and a text payload naming the
  problem and the fix. A daemon HTTP 400 becomes a tool error
  quoting the daemon's message; 404 the same; 503 (game down,
  poller missing, wiki unavailable) the same, with the daemon's
  error code included. A transport failure (connection refused,
  timeout) becomes a tool error naming the daemon URL and
  telling the client the daemon is down. A tool that returns
  `ok: false` from the daemon is NOT a tool error: the action
  ran and its envelope (with `fix`) is the result.

Argument validation is strict: a missing required argument, a
wrong type, or an unknown argument key fails with a message
naming the argument and the legal shape. This is the repo's
malformed-input rule applied to MCP arguments.

## 6. Running it

```sh
.venv/bin/python scripts/dfh-mcp
```

The script reads JSON-RPC messages on stdin and writes them on
stdout. Configure the client to spawn it, for example in
Freebuff's `.agents/mcp.json`:

```json
{
  "mcpServers": {
    "urist": {
      "command": "/home/mikey/workspace/df-agent-harness/.venv/bin/python",
      "args": ["/home/mikey/workspace/df-agent-harness/scripts/dfh-mcp"]
    }
  }
}
```

The paths are the machine's own checkout; adjust them to where
the harness lives. The daemon must already be running
(`dfh start`); the server refuses to start without it.

## 7. Model presentation

The MCP server pushes nothing into the snapshot. It exposes the
same snapshot through `observe`, so its presentation cost is
the snapshot's cost: about 4.7K tokens typical, target at most
30K, warning 60K, compaction 100K, never over 140K, same budgets
as the HTTP route. The tool list itself is six short
descriptions; the catalog is pulled on demand per action, never
dumped into the snapshot. There is no briefing trigger and no
opportunities section in the MCP layer: those live in the
snapshot the server returns unchanged. The server deliberately
does not push the full catalog, the wiki index, or the journal
into any response; each is one call away through its tool.

## 8. What it deliberately does not do

- No new game-driving logic: no tick loop, no planner, no
  decisions of its own. The daemon owns the clock; the agent
  owns decisions.
- No new snapshot format: `observe` returns the HTTP snapshot
  byte for byte in content.
- No pause or unpause tool, no daemon control, no goal
  management, no diary writing: those stay HTTP-only or
  daemon-owned. A client that needs them uses the daemon
  directly, not MCP.
- No events stream: the SSE stream is a long-lived HTTP
  connection and does not fit the request/response tool shape;
  events reach the client through `observe`.
- No caching of daemon responses: every call hits the daemon
  fresh, so a stale MCP answer cannot disagree with the game.
  The one exception is the catalog validation inside `act`,
  which reads the catalog live on every call.

## 9. UNVERIFIED marks

- The six tools return the daemon's real data through a real
  MCP client. UNVERIFIED: no live MCP client check has run
  yet. Bar: a real MCP client (not the unit-test fake) calls
  all six tools against the running daemon and the live fort,
  and each result matches the matching HTTP route.
  UNVERIFIED until that run is logged in the coordinator log.
- `observe` matches `GET /v1/snapshot` exactly. UNVERIFIED:
  needs the same live client check comparing the two.
- `act` validates an unknown action name against the catalog
  and names the legal values. UNVERIFIED: needs the live
  client check calling `act` with a bad name, and with a real
  game action executed through MCP (for example queueing a job)
  and verified in the game state.
- The server refuses to start without a reachable daemon.
  Proven offline by the subprocess test (exit 2, clear message
  naming the daemon URL). UNVERIFIED live: needs the same run
  with the real daemon stopped, showing the same exit and
  message.
- Freebuff `.agents/mcp.json` wiring works end to end.
  UNVERIFIED: needs a Freebuff agent on Mikey's machine
  actually using the server. That is Mikey's step, not a
  code step.
