"""Local MCP server exposing a read-only department directory."""
from mcp.server.fastmcp import FastMCP
from .departments import list_departments

mcp = FastMCP('department-directory')

@mcp.tool()
async def query_departments() -> list[dict]:
    """Return available general outpatient department codes and names."""
    return await list_departments()

if __name__ == '__main__':
    mcp.run(transport='stdio')
