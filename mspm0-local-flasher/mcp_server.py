"""Codex MCP stdio server for a locally attached MSPM0G3507."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

# Dependencies are installed in this project's .vendor directory, not globally.
ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / ".vendor"
for relative in ("", "win32", "win32/lib", "pywin32_system32"):
    sys.path.insert(0, str(VENDOR / relative))
if os.name == "nt":
    _dll_directory = os.add_dll_directory(str(VENDOR / "pywin32_system32"))

from mcp.server.fastmcp import FastMCP
from mcp_backend import SerialService


mcp = FastMCP("mspm0g3507-serial")
service = SerialService()


@mcp.tool()
async def list_serial_ports() -> list[dict]:
    """List local COM ports with device descriptions; use to find CH340/USB serial before connecting."""
    return await asyncio.to_thread(service.list_ports)


@mcp.tool()
async def connect_serial(port_name: str, baud_rate: int = 115200) -> dict:
    """Connect the UART monitor to a local COM port using 8N1. Close any browser monitor using the same port first."""
    return await asyncio.to_thread(service.connect, port_name, baud_rate)


@mcp.tool()
async def read_serial(max_bytes: int = 4096, wait_ms: int = 1000, encoding: str = "utf-8") -> dict:
    """Read buffered UART bytes since the previous call. Returns decoded text AND raw HEX; call repeatedly to monitor output."""
    return await asyncio.to_thread(service.read, max_bytes, wait_ms, encoding)


@mcp.tool()
async def capture_serial(port_name: str, baud_rate: int = 115200,
                         duration_ms: int = 3000, max_bytes: int = 4096,
                         encoding: str = "utf-8") -> dict:
    """One-call UART capture: open a COM port, collect incoming bytes, return text and raw HEX, then release it."""
    return await asyncio.to_thread(service.capture, port_name, baud_rate, duration_ms, max_bytes, encoding)


@mcp.tool()
async def send_serial(data: str, format: str = "text", line_ending: str = "none") -> dict:
    """Send UTF-8 text or HEX bytes to the connected UART. For text, line_ending is none, lf, cr, or crlf."""
    return await asyncio.to_thread(service.send, data, format, line_ending)


@mcp.tool()
async def disconnect_serial() -> dict:
    """Release the currently connected UART monitor COM port."""
    return await asyncio.to_thread(service.disconnect)


@mcp.tool()
async def flash_hex(hex_path: str, port_name: str = "", bsl_baud_rate: int = 115200,
                    password_hex: str = "FF" * 32, start_application: bool = True,
                    monitor_after: bool = False, monitor_baud_rate: int = 115200) -> dict:
    """Flash Intel HEX to MSPM0G3507 MAIN Flash via ROM UART BSL. Chip must already be in BSL mode; this erases MAIN Flash, writes aligned blocks, and checks each BSL result. The default password is for factory settings only. An open browser monitor must be disconnected first. Set monitor_after to reconnect UART after starting the application."""
    return await asyncio.to_thread(service.flash, hex_path, port_name, bsl_baud_rate,
                                   password_hex, start_application, monitor_after, monitor_baud_rate)


if __name__ == "__main__":
    mcp.run(transport="stdio")
