# mcp/__init__.py
from .server import LocalMCP, tool, list_tools, invoke_local
from .tools import * # registers tools


__all__ = ["LocalMCP", "tool", "list_tools", "invoke_local"]