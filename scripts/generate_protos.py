#!/usr/bin/env python3
"""Regenerate the protobuf Python stubs for the vendored DFHack .proto files.

Usage (from the repo root):

    .venv/bin/python scripts/generate_protos.py

What it does:

1. Runs ``protoc`` (via grpcio-tools, installed in the project venv) over the
   vendored .proto files in ``src/dfhack_rpc/proto/``.
2. Rewrites the two flat cross-file imports protoc emits
   (``import Basic_pb2 as Basic__pb2`` etc.) into package-relative imports
   (``from . import Basic_pb2 as Basic__pb2``). protoc's Python generator in
   the grpcio-tools 1.85 build does not support the ``M`` module-mapping
   option, so this rewrite is the documented workaround; it is a one-line
   regex over generated files only, never over the vendored .proto sources.
3. Verifies the generated modules import and round-trip a message.

The .proto files themselves are byte-identical to upstream
(DFHack/dfhack tag 0.47.05-r5); only the generated *_pb2.py files are
modified. Regenerate whenever the DFHack version is bumped.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = ROOT / "src" / "dfhack_rpc" / "proto"

# protoc emits `import <Name>_pb2 as <Name>__pb2` for cross-file imports
# because the .proto files import each other by bare filename. Rewrite to
# package-relative imports so the stubs work as dfhack_rpc.proto.*.
_IMPORT_RE = re.compile(r"^import (\w+_pb2) as (\w+__pb2)$", re.MULTILINE)


def main() -> int:
    protos = sorted(PROTO_DIR.glob("*.proto"))
    if not protos:
        print("no .proto files found in", PROTO_DIR, file=sys.stderr)
        return 1

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        "-I",
        str(PROTO_DIR),
        "--python_out",
        str(PROTO_DIR),
        *[str(p) for p in protos],
    ]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    rewritten = 0
    for pb2 in sorted(PROTO_DIR.glob("*_pb2.py")):
        text = pb2.read_text()
        new_text, n = _IMPORT_RE.subn(
            r"from . import \1 as \2", text
        )
        if n:
            pb2.write_text(new_text)
            rewritten += n
            print(f"rewrote {n} import(s) in {pb2.name}")

    # Verify the generated modules import and round-trip.
    sys.path.insert(0, str(ROOT / "src"))
    from dfhack_rpc.proto import CoreProtocol_pb2, RemoteFortressReader_pb2

    req = CoreProtocol_pb2.CoreBindRequest(
        method="GetVersionInfo",
        input_msg="dfproto.EmptyMessage",
        output_msg="RemoteFortressReader.VersionInfo",
        plugin="RemoteFortressReader",
    )
    assert CoreProtocol_pb2.CoreBindRequest.FromString(
        req.SerializeToString()
    ) == req
    assert RemoteFortressReader_pb2.VersionInfo(
        dfhack_version="0.47.05-r5"
    ).dfhack_version == "0.47.05-r5"
    print(f"generated {len(protos)} stub(s) OK ({rewritten} import rewrite(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
