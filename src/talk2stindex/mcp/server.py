"""MCP server implementation with StreamableHTTP transport and OAuth 2.0 authentication."""

from __future__ import annotations

import hmac
import time
from functools import partial

import httpx
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from talk2stindex import __version__
from talk2stindex.logging import get_logger
from talk2stindex.mcp.auth import oauth_proxy
from talk2stindex.mcp.auth.oidc_client import OIDCResourceServer
from talk2stindex.mcp.config import MCPConfig

from .tools import register_tools

logger = get_logger(__name__)

SERVER_NAME = "Talk2STIndex MCP"
SERVER_INSTRUCTIONS = (
    "This MCP server provides spatiotemporal extraction capabilities. "
    "Use extract_text to extract spatial and temporal entities from plain text."
)


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to validate OAuth tokens for protected endpoints."""

    def __init__(
        self,
        app,
        oidc_resource_server: OIDCResourceServer,
        protected_paths: list[str],
        resource_metadata_url: str = "",
    ):
        super().__init__(app)
        self.oidc_resource_server = oidc_resource_server
        self.protected_paths = protected_paths
        self.resource_metadata_url = resource_metadata_url

    def _www_authenticate(self) -> str:
        header = 'Bearer realm="Talk2STIndex MCP"'
        if self.resource_metadata_url:
            header += f', resource_metadata="{self.resource_metadata_url}"'
        return header

    async def dispatch(self, request: Request, call_next):
        if not any(request.url.path.startswith(p) for p in self.protected_paths):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {
                    "error": "unauthorized",
                    "error_description": "Missing or invalid Authorization header",
                },
                status_code=401,
                headers={"WWW-Authenticate": self._www_authenticate()},
            )

        token = auth_header[7:]
        token_data = await self.oidc_resource_server.verify_token(token)

        if not token_data:
            return JSONResponse(
                {
                    "error": "unauthorized",
                    "error_description": "Invalid or expired token",
                },
                status_code=401,
                headers={"WWW-Authenticate": self._www_authenticate()},
            )

        request.state.token_data = token_data
        request.state.user_id = token_data.get("sub") or token_data.get("username")
        logger.debug(f"Authenticated request from user: {request.state.user_id}")

        return await call_next(request)


class RestAuthTokenVerifier:
    def __init__(
        self,
        verify_url: str | None,
        verify_ssl: bool,
        timeout: float,
        cache_ttl_seconds: float,
    ) -> None:
        self.verify_url = verify_url
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.cache_ttl_seconds = cache_ttl_seconds
        self._token_cache: dict[str, float] = {}

    async def verify(self, token: str) -> bool:
        if not self.verify_url:
            return False

        now = time.monotonic()
        cached_until = self._token_cache.get(token)
        if cached_until is not None and cached_until > now:
            return True

        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=self.timeout) as c:
            r = await c.post(
                self.verify_url, headers={"Authorization": f"Token {token}"}
            )
            if r.status_code == 405:
                r = await c.get(
                    self.verify_url, headers={"Authorization": f"Token {token}"}
                )
            if not (200 <= r.status_code < 300):
                r = await c.post(self.verify_url, json={"token": token})

        if 200 <= r.status_code < 300:
            self._token_cache[token] = now + self.cache_ttl_seconds
            return True

        return False


class RestAuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        token_verifier: RestAuthTokenVerifier,
        protected_paths: list[str],
        static_token: str | None = None,
    ):
        super().__init__(app)
        self.token_verifier = token_verifier
        self.protected_paths = protected_paths
        self.static_token = static_token

    async def dispatch(self, request: Request, call_next):
        if not any(request.url.path.startswith(p) for p in self.protected_paths):
            return await call_next(request)

        if not self.token_verifier.verify_url and not self.static_token:
            return JSONResponse(
                {
                    "error": "server_error",
                    "error_description": "REST auth is not configured",
                },
                status_code=500,
            )

        auth_header = request.headers.get("Authorization", "")
        token: str | None = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        elif auth_header.startswith("Token "):
            token = auth_header[6:]
        if not token:
            return JSONResponse(
                {
                    "error": "unauthorized",
                    "error_description": "Missing or invalid Authorization header",
                },
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="Talk2STIndex REST"'},
            )

        if self.static_token and hmac.compare_digest(token, self.static_token):
            request.state.user_id = None
            return await call_next(request)

        if not self.token_verifier.verify_url:
            return JSONResponse(
                {
                    "error": "unauthorized",
                    "error_description": "Invalid or expired token",
                },
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="Talk2STIndex REST"'},
            )

        ok = await self.token_verifier.verify(token)
        if not ok:
            return JSONResponse(
                {
                    "error": "unauthorized",
                    "error_description": "Invalid or expired token",
                },
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="Talk2STIndex REST"'},
            )

        request.state.user_id = None
        return await call_next(request)


# --- Route handlers ---


async def _handle_health(_request: Request) -> JSONResponse:
    return JSONResponse(
        {"status": "healthy", "service": SERVER_NAME, "version": __version__}
    )


class _AlreadySentResponse(Response):
    """Sentinel for endpoints that send the ASGI response directly.

    Starlette always calls ``await response(scope, receive, send)`` after the
    route handler returns.  When the inner handler has already written the full
    response through the raw ASGI *send* callback (as StreamableHTTP does),
    that second call sends a spurious ``http.response.start`` message into
    BaseHTTPMiddleware's internal stream, triggering an AssertionError.
    Making ``__call__`` a no-op prevents that second write.
    """

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[override]
        pass


async def _handle_mcp_endpoint(
    request: Request, *, session_manager: StreamableHTTPSessionManager
) -> Response:
    await session_manager.handle_request(request.scope, request.receive, request._send)
    return _AlreadySentResponse()


async def _handle_oauth_metadata(request: Request, config: MCPConfig) -> JSONResponse:
    return await oauth_proxy.handle_oauth_metadata(config, request)


async def _handle_openid_config(request: Request, config: MCPConfig) -> JSONResponse:
    return await oauth_proxy.handle_openid_configuration(config, request)


async def _handle_protected_resource(
    request: Request, config: MCPConfig
) -> JSONResponse:
    return await oauth_proxy.handle_protected_resource_metadata(config, request)


async def _handle_client_reg(request: Request, config: MCPConfig) -> JSONResponse:
    return await oauth_proxy.handle_client_registration(config, request)


async def _handle_callback(request: Request, config: MCPConfig) -> Response:
    return await oauth_proxy.handle_oauth_callback(config, request)


async def _handle_oauth_proxy(request: Request, config: MCPConfig) -> Response:
    return await oauth_proxy.proxy_oauth_request(config, request)


async def _handle_accounts_proxy(request: Request, config: MCPConfig) -> Response:
    return await oauth_proxy.proxy_accounts_request(config, request)


async def _handle_login_proxy(request: Request, config: MCPConfig) -> Response:
    return await oauth_proxy.proxy_login_request(config, request)


async def _handle_root_oauth_redirect(request: Request) -> Response:
    path = request.url.path
    query = request.url.query
    new_path = f"/oauth{path}"
    if query:
        new_path += f"?{query}"
    from starlette.responses import RedirectResponse

    return RedirectResponse(url=new_path)


async def _handle_privacy(request: Request) -> Response:
    return Response(
        content="<html><body><h1>Privacy Policy</h1><p>Talk2STIndex MCP Server</p></body></html>",
        media_type="text/html",
    )


async def _handle_terms(request: Request) -> Response:
    return Response(
        content="<html><body><h1>Terms of Service</h1><p>Talk2STIndex MCP Server</p></body></html>",
        media_type="text/html",
    )


async def _handle_static_proxy(request: Request, config: MCPConfig) -> Response:
    return await oauth_proxy.proxy_static_request(config, request)


# --- Server building ---


def create_mcp_server(config: MCPConfig | None = None) -> Server:
    server = Server(
        name=SERVER_NAME, version=__version__, instructions=SERVER_INSTRUCTIONS
    )

    register_tools(server, config=config)
    return server


def create_asgi_app(
    mcp_server: Server,
    oidc_resource_server: OIDCResourceServer,
    session_manager: StreamableHTTPSessionManager,
    config: MCPConfig,
) -> Starlette:
    """Create the ASGI application with MCP endpoints protected by OAuth."""

    rest_token_verifier = RestAuthTokenVerifier(
        verify_url=config.rest_auth.verify_url,
        verify_ssl=config.rest_auth.verify_ssl,
        timeout=config.rest_auth.timeout,
        cache_ttl_seconds=config.rest_auth.cache_ttl_seconds,
    )

    routes = [
        Route("/health", endpoint=_handle_health, methods=["GET"]),
        Route("/health/", endpoint=_handle_health, methods=["GET"]),
        Route("/privacy", endpoint=_handle_privacy, methods=["GET"]),
        Route("/privacy/", endpoint=_handle_privacy, methods=["GET"]),
        Route("/terms", endpoint=_handle_terms, methods=["GET"]),
        Route("/terms/", endpoint=_handle_terms, methods=["GET"]),
        Route(
            "/mcp",
            endpoint=partial(_handle_mcp_endpoint, session_manager=session_manager),
            methods=["GET", "POST", "DELETE"],
        ),
    ]

    if config.oauth.protect_mcp:
        routes.extend(
            [
                Route(
                    "/.well-known/oauth-authorization-server",
                    endpoint=partial(_handle_oauth_metadata, config=config),
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/.well-known/oauth-authorization-server/mcp",
                    endpoint=partial(_handle_oauth_metadata, config=config),
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/.well-known/oauth-authorization-server/oauth",
                    endpoint=partial(_handle_oauth_metadata, config=config),
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/.well-known/oauth-protected-resource",
                    endpoint=partial(_handle_protected_resource, config=config),
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/.well-known/oauth-protected-resource/mcp",
                    endpoint=partial(_handle_protected_resource, config=config),
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/.well-known/openid-configuration",
                    endpoint=partial(_handle_openid_config, config=config),
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/.well-known/openid-configuration/mcp",
                    endpoint=partial(_handle_openid_config, config=config),
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/.well-known/openid-configuration/oauth",
                    endpoint=partial(_handle_openid_config, config=config),
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/oauth/register",
                    endpoint=partial(_handle_client_reg, config=config),
                    methods=["GET", "POST", "OPTIONS"],
                ),
                Route(
                    "/oauth/callback",
                    endpoint=partial(_handle_callback, config=config),
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/oauth/{path:path}",
                    endpoint=partial(_handle_oauth_proxy, config=config),
                    methods=["GET", "POST", "OPTIONS"],
                ),
                Route(
                    "/accounts/{path:path}",
                    endpoint=partial(_handle_accounts_proxy, config=config),
                    methods=["GET", "POST", "OPTIONS"],
                ),
                Route(
                    "/login",
                    endpoint=partial(_handle_login_proxy, config=config),
                    methods=["GET", "POST", "OPTIONS"],
                ),
                Route(
                    "/login/",
                    endpoint=partial(_handle_login_proxy, config=config),
                    methods=["GET", "POST", "OPTIONS"],
                ),
                Route(
                    "/authorize",
                    endpoint=_handle_root_oauth_redirect,
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/authorize/",
                    endpoint=_handle_root_oauth_redirect,
                    methods=["GET", "OPTIONS"],
                ),
                Route(
                    "/token",
                    endpoint=_handle_root_oauth_redirect,
                    methods=["POST", "OPTIONS"],
                ),
                Route(
                    "/token/",
                    endpoint=_handle_root_oauth_redirect,
                    methods=["POST", "OPTIONS"],
                ),
                Route(
                    "/static/{path:path}",
                    endpoint=partial(_handle_static_proxy, config=config),
                    methods=["GET"],
                ),
            ]
        )

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        ),
    ]

    if rest_token_verifier.verify_url or config.rest_auth.token:
        middleware.append(
            Middleware(
                RestAuthMiddleware,
                token_verifier=rest_token_verifier,
                protected_paths=["/api"],
                static_token=config.rest_auth.token,
            )
        )
    if config.oauth.protect_mcp:
        middleware.append(
            Middleware(
                JWTAuthMiddleware,
                oidc_resource_server=oidc_resource_server,
                protected_paths=["/mcp"],
                resource_metadata_url=f"{config.server.base_url}/.well-known/oauth-protected-resource",
            )
        )

    app = Starlette(routes=routes, middleware=middleware)
    logger.info("ASGI application created with OAuth authentication")
    return app


def build_server(
    config: MCPConfig | None = None,
) -> tuple[Starlette, StreamableHTTPSessionManager, Server]:
    """Build and configure the complete MCP server with OAuth integration."""
    if config is None:
        config = MCPConfig.load()

    logger.info(f"Building MCP server at {config.server.base_url}")
    logger.info("Using StreamableHTTP transport (MCP protocol 2025-03-26)")
    logger.info(
        f"Token validation: {'Introspection' if config.oauth.use_introspection else 'JWT'}"
    )

    oidc_resource_server = OIDCResourceServer(
        oidc_discovery_url=config.oauth.discovery_url,
        client_id=config.oauth.client_id,
        client_secret=config.oauth.client_secret,
        use_introspection=config.oauth.use_introspection,
        verify_ssl=config.oauth.verify_ssl,
        timeout=config.oauth.timeout,
    )

    mcp_server = create_mcp_server(config=config)
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=False,
        stateless=True,
    )

    app = create_asgi_app(mcp_server, oidc_resource_server, session_manager, config)
    return app, session_manager, mcp_server
