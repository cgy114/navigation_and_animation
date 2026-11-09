"""Read-only MCP transport smoke test. Does not open or write to a COM port."""

import asyncio
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / ".vendor"
for relative in ("", "win32", "win32/lib", "pywin32_system32"):
    sys.path.insert(0, str(VENDOR / relative))
if sys.platform == "win32":
    import os
    _dll_directory = os.add_dll_directory(str(VENDOR / "pywin32_system32"))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(live_port=None):
    params = StdioServerParameters(
        command=str(ROOT / ".venv" / "Scripts" / "python.exe"),
        args=[str(ROOT / "mcp_server.py")],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            expected = {"list_serial_ports", "connect_serial", "read_serial", "capture_serial", "send_serial", "disconnect_serial", "flash_hex"}
            assert set(names) == expected, names
            ports = await session.call_tool("list_serial_ports", {})
            if ports.isError:
                raise RuntimeError(str(ports.content))
            print(json.dumps({"tools": names, "ports_result": [item.text for item in ports.content if item.type == "text"]}, ensure_ascii=False))
            if live_port:
                captured = await session.call_tool("capture_serial", {"port_name": live_port, "baud_rate": 115200, "duration_ms": 1000, "max_bytes": 256})
                print(json.dumps({"live_capture_error": captured.isError, "capture_result": [item.text for item in captured.content if item.type == "text"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-port", help="Optionally capture one second from this real COM port")
    args = parser.parse_args()
    asyncio.run(main(args.live_port))
