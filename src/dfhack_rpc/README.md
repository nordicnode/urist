# dfhack_rpc — DFHack RPC client (DF 0.47.05 / DFHack 0.47.05-r5)

From-scratch Python client for the DFHack remote protocol. Stdlib +
`protobuf` runtime only. See `docs/PROTOCOL.md` §2 for the spec this
implements.

## Layout

```
src/dfhack_rpc/
  __init__.py      public exports
  client.py        DFHackClient: handshake, framing, bind/call, RunCommand, run_lua
  errors.py        TransportError vs RemoteError (transport failure != DFHack FAIL)
  methods.py       RemoteFortressReader method table (bind type names + message classes)
  proto/           vendored DFHack .proto files (tag 0.47.05-r5) + generated *_pb2.py
  proto/README.md  provenance + regeneration instructions
```

## Framing (PROTOCOL.md §8 open question #1 — resolved)

Verified against the 0.47.05-r5 server sources
(`library/RemoteServer.cpp`, `library/RemoteClient.cpp`,
`library/include/RemoteClient.h`):

* Handshake is 12 bytes: `b"DFHack?\n"` + int32 LE 1; reply `b"DFHack!\n"`
  + int32 LE 1.
* Every message header is **8 bytes**: `struct.pack("<hhi", id, 0, size)`.
  The C struct is `int16_t id; int32_t size;` — C++ alignment pads it to
  8 bytes, and both server and reference client read/write
  `sizeof(header)`. Do not "simplify" to 6 bytes.
* FAIL replies carry the `command_result` code in the header's size field
  with no body; TEXT replies carry `CoreTextNotification`.
* Still to confirm against the **live game** in phase 1: the mock-server
  tests prove our framing is self-consistent with the spec + server
  source, not that the real server accepts it.

## Usage

```python
from dfhack_rpc import DFHackClient

with DFHackClient("127.0.0.1", 5000) as client:
    print(client.get_version())          # RFR GetVersionInfo
    print(client.run_lua('print("hi")')) # RunCommand("lua", ...)
    data = client.run_lua_json('print("{\\"ok\\": true}")')
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v   # from the repo root
```

All tests run offline against a mock DFHack server (`tests/mock_dfhack_server.py`);
no DF install is needed.

## Regenerating the protobuf stubs

```bash
.venv/bin/python scripts/generate_protos.py
```

## Smoke test against a live game

```bash
.venv/bin/python scripts/rpc_smoke.py --host 127.0.0.1 --port 5000
```

Exits non-zero with a clear message if nothing is listening (5 s
connect timeout, no hanging).

## Open questions (live-game verification still needed)

* `BasicApi.proto` declares core RPCs `GetVersion` / `GetDFVersion`
  (`EmptyMessage -> StringMessage`); untested whether they are bound on
  the core service at r5. `get_version()` uses RFR `GetVersionInfo`
  instead, which is documented in PROTOCOL.md §2.5.
* Whether the server accepts more than one concurrent client connection
  (design assumes one).
* Whether `DFHACK_PORT` overrides `remote-server.json` at r5.
