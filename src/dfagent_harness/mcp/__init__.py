"""Urist MCP server: the harness as six native MCP tools.

The server speaks MCP over stdio (newline-delimited JSON-RPC 2.0)
and talks to the running daemon over HTTP. It holds no game state
of its own and adds no game-driving logic: every tool maps onto an
existing daemon route. See ``docs/MCP.md`` for the design.
"""

__version__ = "0.1.0"

TOOL_NAMES = (
    "observe",
    "act",
    "query",
    "catalog",
    "wiki_search",
    "journal",
)
