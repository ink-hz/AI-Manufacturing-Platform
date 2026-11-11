"""Shared host-authenticated administrative HTTP boundary; construction has no I/O."""
from collections.abc import Mapping
import inspect
import re
from uuid import UUID

from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Match

READ_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})


def private_admin_routes(*, authorize, error_type, system, validate_request, actor_state):
    """Return route classes that authorize before body parsing and service I/O.

    The host callback implements session authentication and CSRF using ``write``.
    Only its validated administrator identity crosses into the service layer.
    """
    def error(code, status):
        return JSONResponse({'code': code}, status_code=status)

    def actor(identity, write):
        if (not isinstance(identity, Mapping)
                or identity.get('configuration_admin') is not True
                or type(identity.get('read_only')) is not bool
                or (write and identity['read_only'])):
            raise error_type(system + '_FORBIDDEN', 403)
        user_id = identity.get('user_id')
        if isinstance(user_id, bool) or not isinstance(user_id, (str, int, UUID)) or not str(user_id).strip():
            raise error_type(system + '_FORBIDDEN', 403)
        return str(user_id)

    class PrivateRoute(APIRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def private(request):
                try:
                    write = request.method not in READ_METHODS
                    identity = authorize(request, write=write)
                    if inspect.isawaitable(identity):
                        identity = await identity
                    setattr(request.state, actor_state, actor(identity, write))
                    if not isinstance(self, DeniedRoute):
                        await validate_request(request)
                    response = await handler(request)
                except error_type as exc:
                    if (isinstance(exc.code, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', exc.code)
                            and type(exc.status) is int and 400 <= exc.status <= 599):
                        response = error(exc.code, exc.status)
                    else:
                        response = error(system + '_UNAVAILABLE', 503)
                except HTTPException as exc:
                    status = exc.status_code if exc.status_code in {401, 403} else 503
                    code = {401: '_UNAUTHENTICATED', 403: '_FORBIDDEN'}.get(status, '_UNAVAILABLE')
                    response = error(system + code, status)
                except Exception:
                    response = error(system + '_UNAVAILABLE', 503)
                response.headers['Cache-Control'] = 'private, no-store'
                return response

            return private

    class DeniedRoute(PrivateRoute):
        def matches(self, scope):
            match, child_scope = super().matches(scope)
            # Starlette must not answer 405 before our authorization wrapper.
            return (Match.FULL if match == Match.PARTIAL else match), child_scope

        async def handle(self, scope, receive, send):
            await self.app(scope, receive, send)

    return PrivateRoute, DeniedRoute
