"""Synchronous bridge from Flask to the chess MCP server.

Runs a dedicated thread with its own asyncio loop that owns a stdio
ClientSession to chess_mcp_server.py; call() marshals tool calls onto
that loop from any Flask worker thread.
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_SERVER = Path(__file__).resolve().parent / "chess_mcp_server.py"


class ChessMCP:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: ClientSession | None = None
        self._ready = threading.Event()
        self._startup_error: Exception | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=30):
            raise RuntimeError("Chess MCP server did not start in time")
        if self._startup_error:
            raise self._startup_error

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:  # startup failure surfaces to constructor
            self._startup_error = exc
            self._ready.set()

    async def _main(self) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(_SERVER)],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self._session = session
                self._ready.set()
                await asyncio.Event().wait()  # serve forever

    def call(self, tool: str, **args) -> dict:
        """Call an MCP tool and return its structured result as a dict."""
        assert self._session is not None and self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(tool, args), self._loop
        )
        result = fut.result(timeout=30)
        if result.is_error:
            text = result.content[0].text if result.content else "unknown error"
            raise ValueError(_strip_tool_error(text))
        if result.structured_content is not None:
            data = result.structured_content
            return data.get("result", data)
        return json.loads(result.content[0].text)


def _strip_tool_error(text: str) -> str:
    # FastMCP wraps exceptions like "Error executing tool make_move: <msg>"
    marker = ": "
    if text.startswith("Error executing tool") and marker in text:
        return text.split(marker, 1)[1]
    return text


_instance: ChessMCP | None = None
_lock = threading.Lock()


def get_bridge() -> ChessMCP:
    global _instance
    with _lock:
        if _instance is None:
            _instance = ChessMCP()
        return _instance
