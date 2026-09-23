"""Console entry point: run the server on stdio.

`MCPServer.run()` is synchronous and blocks for the life of the server; stdio is its default
transport (`docs/api-notes.md` section 1.3).
"""

from swiss_outdoor_mcp.server import mcp

__all__ = ["main"]


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
