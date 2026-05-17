"""HTTP API wrapper for the shared TDX helpers.

This server mirrors ``mcp_server_sse_tdx.py`` but exposes plain HTTP endpoints
for the same three tools backed by ``bytedance.tdx_api.tdx_api``.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import FastAPI

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bytedance.tdx_api.tdx_api import fetch_td_eventlog, get_raw_tdx_quote, get_tee_status


TOOL_HANDLERS: Dict[str, Callable[[], Dict[str, Any]]] = {
    "fetchTDEventlog": fetch_td_eventlog,
    "getRawTDXQuote": get_raw_tdx_quote,
    "getTEEStatus": get_tee_status,
}

TOOL_DESCRIPTIONS = {
    "fetchTDEventlog": "Retrieve TD event log data using the shared TDX API bundle.",
    "getRawTDXQuote": "Retrieve raw TDX quote data using the shared TDX API bundle.",
    "getTEEStatus": "Check whether the current host is running as a TDX guest using the shared TDX API bundle.",
}

TOOL_ENDPOINTS = {
    "fetchTDEventlog": "/api/fetchTDEventlog",
    "getRawTDXQuote": "/api/getRawTDXQuote",
    "getTEEStatus": "/api/getTEEStatus",
}

app = FastAPI(
    title="TDX Tools HTTP API",
    description="HTTP API for the shared TDX helper tools",
)


def _invoke_tool(name: str) -> Dict[str, Any]:
    return TOOL_HANDLERS[name]()


@app.post("/api/fetchTDEventlog")
async def http_fetch_td_eventlog() -> Dict[str, Any]:
    return _invoke_tool("fetchTDEventlog")


@app.post("/api/getRawTDXQuote")
async def http_get_raw_tdx_quote() -> Dict[str, Any]:
    return _invoke_tool("getRawTDXQuote")


@app.post("/api/getTEEStatus")
async def http_get_tee_status() -> Dict[str, Any]:
    return _invoke_tool("getTEEStatus")


@app.get("/api/tools")
async def list_available_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": TOOL_DESCRIPTIONS[name],
            "endpoint": TOOL_ENDPOINTS[name],
            "method": "POST",
            "required_params": [],
            "example_request": {},
        }
        for name in TOOL_HANDLERS
    ]


@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "timestamp": datetime.datetime.now().isoformat()}


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "name": "TDX Tools HTTP API",
        "version": "1.0.0",
        "description": "HTTP API for the shared TDX helper tools",
        "endpoints": {
            "tools": "/api/tools",
            "health": "/health",
            **{name: endpoint for name, endpoint in TOOL_ENDPOINTS.items()},
        },
    }


if __name__ == "__main__":
    import uvicorn

    print("Starting TDX Tools HTTP API server...")
    print("Available endpoints:")
    print("  GET  /                 - API information")
    print("  GET  /health           - Health check")
    print("  GET  /api/tools        - List available tools")
    print("  POST /api/fetchTDEventlog - Retrieve TD Eventlog")
    print("  POST /api/getRawTDXQuote  - Get raw TDX Quote")
    print("  POST /api/getTEEStatus    - Check TEE status")
    print("\nServer starting on http://0.0.0.0:8800")
    uvicorn.run(app, host="0.0.0.0", port=8800)
