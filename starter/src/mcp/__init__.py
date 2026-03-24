"""
src/mcp/__init__.py
===================
MCP package for The Ledger.
"""
from src.mcp.server import MCPLedgerServer, handle_tool_call, handle_resource_call

__all__ = ["MCPLedgerServer", "handle_tool_call", "handle_resource_call"]
