# mcp/__init__.py
from .server import LocalMCP, tool, list_tools, invoke_local
from .tools import *  # Basic tools (6 tools)
from .tools_enhanced import *  # Enhanced tools (15 additional tools)

__all__ = ["LocalMCP", "tool", "list_tools", "invoke_local"]