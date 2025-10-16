# mcp/server.py
import inspect
import asyncio
from typing import Callable, Dict, Any
from fastapi import FastAPI, HTTPException
import uvicorn

# Tool registry (module-level)
_TOOL_REGISTRY: Dict[str, Callable] = {}


def tool(name: str = None):
    """Decorator to register a tool callable by name."""
    def _decorator(fn: Callable):
        key = name or fn.__name__
        _TOOL_REGISTRY[key] = fn
        return fn
    return _decorator


def list_tools():
    return {
        name: {
            "args": list(inspect.signature(fn).parameters.keys()),
            "doc": (fn.__doc__ or "")[:400]
        } for name, fn in _TOOL_REGISTRY.items()
    }


async def invoke_local(tool_name: str, payload: Dict[str, Any]):
    """Invoke a registered tool directly (local, no HTTP)."""
    if tool_name not in _TOOL_REGISTRY:
        raise KeyError("tool not found")
    fn = _TOOL_REGISTRY[tool_name]
    if inspect.iscoroutinefunction(fn):
        return await fn(**payload)
    else:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(**payload))


class LocalMCP:
    """Simple client wrapper that calls invoke_local directly."""
    def __init__(self):
        pass

    async def invoke(self, tool_name: str, args: Dict[str, Any]):
        return await invoke_local(tool_name, args)


# Optional HTTP FastAPI wrapper for MCP (not required for single-process mode)
app = FastAPI(title="MCP HTTP Server")


@app.get("/tools")
async def _list_tools():
    return list_tools()


@app.post("/invoke/{tool_name}")
async def _invoke_tool(tool_name: str, payload: Dict[str, Any]):
    if tool_name not in _TOOL_REGISTRY:
        raise HTTPException(status_code=404, detail="tool not found")
    fn = _TOOL_REGISTRY[tool_name]
    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(**payload)
        else:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: fn(**payload))
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def serve_http(host: str = "0.0.0.0", port: int = 8000):
    """Start the HTTP server for remote tool invocation."""
    uvicorn.run(app, host=host, port=port)