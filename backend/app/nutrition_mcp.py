"""Private, in-process MCP server bound to one authenticated chat request."""
import json

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session


async def today_context(user, summary_for_user, meals_for_user):
    # Capture the verified identity in the server closure, never in tool arguments.
    server = FastMCP('nutrition-private')

    @server.tool()
    async def get_today_nutrition() -> dict:
        """Return today's recorded meals and nutrition for the signed-in user."""
        summary = await summary_for_user(user, 1)
        meals = await meals_for_user(user)
        return {'summary': summary, 'meals': meals}

    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool('get_today_nutrition', {})
        if result.isError:
            raise RuntimeError('nutrition MCP tool failed')
        if result.structuredContent is not None:
            return result.structuredContent
        return json.loads(result.content[0].text)
