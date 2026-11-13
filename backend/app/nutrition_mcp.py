"""Private, in-process MCP server bound to one authenticated chat request."""
import json

from mcp.server.fastmcp import FastMCP, Context
from mcp.shared.memory import create_connected_server_and_client_session
from starlette.responses import JSONResponse
from starlette.requests import Request
from datetime import datetime, timezone
from .auth import token_digest
from .db import connect


def http_server(summary_for_user, meals_for_user):
    server = FastMCP('nutrition', host='0.0.0.0', stateless_http=True, json_response=True,
                     streamable_http_path='/', max_request_body_size=65536)

    @server.tool()
    async def get_today_nutrition(ctx: Context) -> dict:
        """Get the authenticated user's recorded meals and nutrition today (Asia/Shanghai)."""
        user = ctx.request_context.request.scope['state']['mcp_user']
        return {'summary': await summary_for_user(user, 1), 'meals': await meals_for_user(user)}

    return server


class BearerAuth:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        request = Request(scope, receive=receive)
        authorization = request.headers.get('authorization', '')
        scheme, _, token = authorization.partition(' ')
        if scheme.lower() != 'bearer' or not token or len(token) > 128:
            response = JSONResponse({'detail': 'MCP bearer token required'}, status_code=401,
                                    headers={'WWW-Authenticate': 'Bearer'})
            await response(scope, receive, send)
            return
        async with connect() as db:
            row = await (await db.execute('SELECT user_id,expires_at FROM mcp_tokens WHERE token_hash=?',
                                          (token_digest(token),))).fetchone()
        if not row or datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc):
            response = JSONResponse({'detail': 'Invalid or expired MCP token'}, status_code=401,
                                    headers={'WWW-Authenticate': 'Bearer'})
            await response(scope, receive, send)
            return
        scope.setdefault('state', {})['mcp_user'] = str(row['user_id'])
        await self.app(scope, receive, send)


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
