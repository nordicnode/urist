<p align="center">
  <img src="assets/logo.png" alt="Urist logo: a pixel-art dwarf with a pickaxe" width="220">
</p>

<h1 align="center">Urist</h1>

<p align="center"><strong>An AI overseer that plays Dwarf Fortress on its own.</strong></p>

<p align="center">
  Urist watches the fort, understands what the dwarves need, and plays the game itself:
  digging, building, brewing, and keeping everyone alive, with no human at the keyboard.
</p>

---

## What it is

Urist is a harness that lets any AI play Dwarf Fortress fortress mode autonomously.
It sits between the game and the AI: it reads the full state of the fort, turns it
into a form an AI can understand, lets the AI act through a clean API, and pings
the AI the moment something happens — a death, a siege, a strange mood, a
cancelled job.

It is AI-agnostic. Any model can drive it through the same protocol; nothing
depends on one particular AI, its memory, or its tooling.

It is pinned to **Dwarf Fortress 0.47.05** with **DFHack 0.47.05-r8**. That version
is a deliberate choice, not a limitation.

## Status

In active development. The foundation is built and verified against a live game:

- **Observation layer** — full fort state as structured JSON and compact readable
  text: dwarves, stocks, buildings, jobs, reports, map, designations.
- **Action layer** — verified actions for digging, chopping, gathering, building,
  manager orders, and labors, each checked before and after it runs.
- **Event system** — a watcher inside the game fires on deaths, job completions,
  reports, invasions, and new arrivals, and streams them to the AI.
- **Planner and daemon** — in progress: a goal-driven planner and a daemon that
  owns the game loop, so the fort keeps playing tick after tick.

Urist does not yet play a fort end to end with no intervention. That is the goal
it is being built toward.

## How it works

Four layers, each verified live before the next is built:

| Layer | What it does |
| --- | --- |
| **Observe** | Reads the game through DFHack RPC and returns the fort as JSON and readable text. Raw values are interpreted into plain state, stable lists are compressed to diffs, and what needs attention comes first. |
| **Act** | A typed action catalog. Every action names its parameters, legal values, preconditions, and expected effects, and verifies the result in the game. |
| **Events** | A watcher inside the game emits events as they happen. The AI is pinged instead of polling blindly, and the game pauses first on a threat. |
| **Plan** | A daemon drives the loop: observe, decide, act, verify, repeat. Goals are ordered by survival first, and every decision is journaled. |

The AI never touches the game directly. It has no vision and no keystrokes:
everything goes through the harness API.

## Design principles

- **AI-agnostic.** Any model, any provider. The protocol is the interface.
- **Everything through the API.** No screenshots, no simulated keystrokes for
  game actions.
- **Live-verified, or it does not count.** Every step is tested against a running
  fort before the next one is built. Offline tests alone never prove a feature.
- **The AI starts knowing nothing about Dwarf Fortress.** The harness teaches it:
  composed tasks that encode the game's causal chains, failure diagnoses that say
  what went wrong and how to fix it, briefings when a new situation appears, and
  a wiki it can ask.
- **The AI must remember what happened and why.** Events carry their causes,
  decisions carry their outcomes, and failures are recorded so the same mistake
  is not repeated.
- **Built for small context windows.** The harness pushes only diffs and a small
  snapshot each tick; the AI pulls full detail on demand. Nothing assumes a
  large context window.

## Quickstart

Requirements: Linux, Python 3.12, Dwarf Fortress 0.47.05, DFHack 0.47.05-r8,
and Xvfb. Full setup, with exact download URLs and checksums, is in
[docs/SETUP.md](docs/SETUP.md).

```sh
git clone https://github.com/nordicnode/urist.git
cd urist
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Put a DF 0.47.05 install with DFHack r8 in `third_party/df_47_05/`
(see [docs/SETUP.md](docs/SETUP.md)), then:

```sh
# Observe the fort once
.venv/bin/python scripts/dfh-observe.py

# Start the daemon (HTTP API on 127.0.0.1:8765)
.venv/bin/python scripts/dfh.py start

# Check it
.venv/bin/python scripts/dfh.py status
```

## The agent protocol

The daemon serves HTTP on `127.0.0.1:8765`:

- `GET /v1/health`, `/v1/state`, `/v1/units`, `/v1/unit/{id}`,
  `/v1/buildings`, `/v1/jobs`, `/v1/items`, `/v1/reports`, `/v1/map`
- `GET /v1/events` — server-sent events, plus JSON
- `POST /v1/actions/{dig,chop,gather,build,deconstruct,stockpile,order,queue-job,labor,pause,...}`
- `GET /v1/journal`, `/v1/goals`, `/v1/tasks`

The per-tick snapshot is an index into the full state: it always names what
exists, with ids, and the AI pulls full detail for anything it needs.

## Project layout

```
src/dfagent_harness/   the harness: observe, actions, events, planner, daemon, server
src/dfhack_rpc/        minimal DFHack RPC client (stdlib + protobuf)
src/dfagent_harness/lua/  Lua helpers run inside the game via DFHack
scripts/               CLIs: dfh-observe, dfh-act, dfh-events, dfh (daemon)
docs/                  OBSERVE.md, ACTIONS.md, EVENTS.md, SETUP.md
tests/                 unit tests plus live tests against a running fort
```

## Roadmap

1. Planner and daemon live on a real fort, keeping it alive through a full
   in-game day.
2. A season bootstrapped from embark with no intervention.
3. The full knowledge layer: a catalog built from the game's own enums, wiki
   lookup wired into the loop, a library of skills that worked, and memory
   that answers why things happened.
4. A fort that plays itself for in-game years: threats, trade, strange moods,
   military, farming, and everything else fortress mode holds.

## License

MIT. See [LICENSE](LICENSE).

## Links

- [Dwarf Fortress](https://www.bay12games.com/dwarves/) — the game, by Bay 12 Games
- [DFHack](https://github.com/DFHack/dfhack) — the modding API this harness drives
- [Dwarf Fortress Wiki](https://dwarffortresswiki.org/) — the game's documentation
