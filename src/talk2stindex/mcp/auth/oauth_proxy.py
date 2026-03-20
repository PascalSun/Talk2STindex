"""OAuth 2.0 proxy handlers for MCP server."""

from __future__ import annotations

import base64
import html
import json
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from talk2stindex.logging import get_logger
from talk2stindex.mcp.config import MCPConfig

logger = get_logger(__name__)


def _proxy_base(config: MCPConfig) -> str:
    base = config.oauth.internal_base_url or config.oauth.public_base_url
    return base.rstrip("/o")


def _validate_redirect_uri(redirect_uri: str) -> bool:
    if not redirect_uri:
        return False

    try:
        parsed = urlparse(redirect_uri)
    except Exception:
        return False

    if parsed.scheme and len(parsed.scheme) > 0:
        if parsed.scheme.lower() in ["claude", "mcp", "http", "https"]:
            if parsed.scheme.lower() == "http":
                logger.warning(
                    f"HTTP redirect_uri used (consider HTTPS): {redirect_uri}"
                )
            return True

        dangerous_protocols = ["javascript", "data", "vbscript", "file", "about"]
        if parsed.scheme.lower() in dangerous_protocols:
            logger.warning(f"Blocked dangerous redirect_uri protocol: {parsed.scheme}")
            return False

    return False


def _rewrite_location(location: str, config: MCPConfig) -> str:
    idp_base = config.oauth.public_base_url.rstrip("/o")

    if location.startswith(idp_base + "/o/"):
        location = location.replace(idp_base + "/o/", "/oauth/", 1)
    elif location.startswith("/o/"):
        location = location.replace("/o/", "/oauth/", 1)

    if location.startswith(idp_base + "/accounts/"):
        location = location.replace(idp_base + "/accounts/", "/accounts/", 1)

    if location.startswith(idp_base + "/accounts/login"):
        location = location.replace(idp_base + "/accounts/login", "/login", 1)
    elif location.startswith("/accounts/login"):
        location = location.replace("/accounts/login", "/login", 1)

    if location.startswith(idp_base + "/login"):
        location = location.replace(idp_base + "/login", "/login", 1)

    return location


def _strip_and_rewrite_cookies(
    upstream_headers: httpx.Headers, use_https: bool
) -> list[str]:
    try:
        cookie_values = upstream_headers.get_list("set-cookie")
    except Exception:
        cookie_values = []

    rewritten_cookies: list[str] = []
    for cookie in cookie_values:
        parts = [p.strip() for p in cookie.split(";")]
        out: list[str] = []
        for p in parts:
            if p.lower().startswith("domain="):
                continue
            if (not use_https) and p.lower() == "secure":
                continue
            out.append(p)
        if not any(p.lower().startswith("samesite=") for p in out):
            out.append("SameSite=Lax")
        rewritten_cookies.append("; ".join(out))
    return rewritten_cookies


async def _forward_and_build_response(
    config: MCPConfig,
    request: Request,
    target_url: str,
    content_override: bytes | None = None,
) -> Response:
    async with httpx.AsyncClient(
        verify=config.oauth.verify_ssl, timeout=config.oauth.timeout
    ) as client:
        headers = dict(request.headers)
        headers.pop("host", None)

        if request.method == "GET":
            response = await client.get(target_url, headers=headers)
        elif request.method == "POST":
            body = content_override
            if body is None:
                body = await request.body()
            headers.pop("content-length", None)
            response = await client.post(target_url, headers=headers, content=body)
        else:
            return Response(f"Method {request.method} not supported", status_code=405)

    resp_headers = dict(response.headers)
    location = resp_headers.get("location") or resp_headers.get("Location")
    if location:
        resp_headers["location"] = _rewrite_location(location, config)

    resp_headers.pop("set-cookie", None)
    resp_headers.pop("Set-Cookie", None)

    proxied = Response(
        content=response.content,
        status_code=response.status_code,
        headers=resp_headers,
    )

    for cookie in _strip_and_rewrite_cookies(
        response.headers, use_https=config.server.base_url.startswith("https://")
    ):
        proxied.headers.append("set-cookie", cookie)

    return proxied


async def handle_oauth_metadata(
    config: MCPConfig, request: Request | None = None
) -> JSONResponse:
    base_url = config.server.base_url
    metadata = {
        "issuer": f"{base_url}/oauth",
        "authorization_endpoint": f"{base_url}/oauth/authorize/",
        "token_endpoint": f"{base_url}/oauth/token/",
        "registration_endpoint": f"{base_url}/oauth/register",
        "revocation_endpoint": f"{base_url}/oauth/revoke_token/",
        "introspection_endpoint": f"{base_url}/oauth/introspect/",
        "userinfo_endpoint": f"{base_url}/oauth/userinfo/",
        "jwks_uri": f"{base_url}/oauth/.well-known/jwks.json",
        "response_types_supported": [
            "code",
            "token",
            "id_token",
            "code token",
            "code id_token",
            "token id_token",
            "code token id_token",
        ],
        "scopes_supported": ["openid", "profile", "email", "read", "write"],
        "grant_types_supported": [
            "authorization_code",
            "implicit",
            "client_credentials",
            "refresh_token",
        ],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "code_challenge_methods_supported": ["S256", "plain"],
        "service_documentation": "https://django-oauth-toolkit.readthedocs.io/",
        "op_policy_uri": f"{base_url}/privacy",
        "op_tos_uri": f"{base_url}/terms",
    }

    if request and (
        request.url.path.endswith("/mcp") or request.url.path.endswith("/oauth")
    ):
        metadata["mcp"] = {
            "client_id": config.oauth.client_id,
            "redirect_uri": f"{base_url}/oauth/callback",
        }

    return JSONResponse(metadata)


async def handle_openid_configuration(
    config: MCPConfig, request: Request | None = None
) -> JSONResponse:
    base_url = config.server.base_url
    metadata = {
        "issuer": f"{base_url}/oauth",
        "authorization_endpoint": f"{base_url}/oauth/authorize/",
        "token_endpoint": f"{base_url}/oauth/token/",
        "userinfo_endpoint": f"{base_url}/oauth/userinfo/",
        "jwks_uri": f"{base_url}/oauth/.well-known/jwks.json",
        "registration_endpoint": f"{base_url}/oauth/register",
        "revocation_endpoint": f"{base_url}/oauth/revoke_token/",
        "introspection_endpoint": f"{base_url}/oauth/introspect/",
        "response_types_supported": [
            "code",
            "token",
            "id_token",
            "code token",
            "code id_token",
            "token id_token",
            "code token id_token",
        ],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "profile", "email", "read", "write"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "grant_types_supported": [
            "authorization_code",
            "implicit",
            "client_credentials",
            "refresh_token",
        ],
        "code_challenge_methods_supported": ["S256", "plain"],
        "op_policy_uri": f"{base_url}/privacy",
        "op_tos_uri": f"{base_url}/terms",
    }

    if request and (
        request.url.path.endswith("/mcp") or request.url.path.endswith("/oauth")
    ):
        metadata["mcp"] = {
            "client_id": config.oauth.client_id,
            "redirect_uri": f"{base_url}/oauth/callback",
        }

    return JSONResponse(metadata)


async def handle_protected_resource_metadata(
    config: MCPConfig, _request: Request
) -> JSONResponse:
    resource_base = config.server.base_url
    return JSONResponse(
        {
            "resource": resource_base,
            "authorization_servers": [f"{resource_base}/oauth"],
            "bearer_methods_supported": ["header"],
            "resource_signing_alg_values_supported": ["RS256"],
        }
    )


async def handle_client_registration(
    config: MCPConfig, request: Request
) -> JSONResponse:
    if request.method == "GET":
        response_data = {
            "registration_endpoint": f"{config.server.base_url}/oauth/register",
            "registration_endpoint_auth_methods_supported": ["client_secret_post"],
            "supported_client_metadata": [
                "client_name",
                "redirect_uris",
                "grant_types",
                "response_types",
                "token_endpoint_auth_method",
                "scope",
            ],
        }
        return JSONResponse(
            response_data,
            status_code=200,
            headers={"Content-Type": "application/json"},
        )

    if request.method != "POST":
        return JSONResponse(
            {
                "error": "invalid_request",
                "error_description": "Client registration requires POST method",
            },
            status_code=405,
        )

    try:
        body = await request.body()
        if not body:
            client_data = {}
        else:
            client_data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        return JSONResponse(
            {
                "error": "invalid_client_metadata",
                "error_description": f"Invalid JSON in request body: {str(e)}",
            },
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Error parsing client registration request: {e}")
        return JSONResponse(
            {
                "error": "invalid_request",
                "error_description": f"Failed to parse request: {str(e)}",
            },
            status_code=400,
        )

    client_name = client_data.get("client_name") or "Talk2STIndex MCP Client"
    redirect_uris = client_data.get("redirect_uris") or [
        f"{config.server.base_url}/oauth/callback"
    ]
    grant_types = client_data.get("grant_types") or [
        "authorization_code",
        "refresh_token",
    ]
    response_types = client_data.get("response_types") or ["code"]
    token_endpoint_auth_method = (
        client_data.get("token_endpoint_auth_method") or "client_secret_post"
    )

    for uri in redirect_uris:
        if not _validate_redirect_uri(uri):
            return JSONResponse(
                {
                    "error": "invalid_redirect_uri",
                    "error_description": f"Invalid redirect_uri: {uri}",
                },
                status_code=400,
            )

    client_id = config.oauth.client_id
    client_secret = config.oauth.client_secret
    client_id_issued_at = int(time.time())

    registration_response = {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_id_issued_at": client_id_issued_at,
        "client_secret_expires_at": 0,
        "client_name": client_name,
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "grant_types": grant_types,
        "response_types": response_types,
        "redirect_uris": redirect_uris,
    }

    if "scope" in client_data:
        registration_response["scope"] = client_data["scope"]
    if "client_uri" in client_data:
        registration_response["client_uri"] = client_data["client_uri"]
    if "logo_uri" in client_data:
        registration_response["logo_uri"] = client_data["logo_uri"]
    if "contacts" in client_data:
        registration_response["contacts"] = client_data["contacts"]

    logger.info(
        f"Client registration (static credentials): client_id={client_id}, "
        f"client_name={client_name}, redirect_uris={redirect_uris}"
    )

    return JSONResponse(
        registration_response,
        status_code=201,
        headers={"Content-Type": "application/json"},
    )


async def handle_oauth_callback(config: MCPConfig, request: Request) -> Response:
    params = dict(request.query_params)
    code = params.get("code")
    state = params.get("state")
    error = params.get("error")
    error_description = params.get("error_description")

    original_redirect_uri = None
    clean_state = state
    if state and "|" in state:
        try:
            parts = state.rsplit("|", 1)
            if len(parts) == 2:
                clean_state = parts[0]
                encoded_redirect = parts[1]
                padding = 4 - len(encoded_redirect) % 4
                if padding != 4:
                    encoded_redirect += "=" * padding
                original_redirect_uri = base64.urlsafe_b64decode(
                    encoded_redirect.encode("utf-8")
                ).decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to decode redirect_uri from state: {e}")

    if original_redirect_uri:
        if not _validate_redirect_uri(original_redirect_uri):
            return JSONResponse(
                {
                    "error": "invalid_request",
                    "error_description": "Invalid redirect_uri in state parameter",
                },
                status_code=400,
            )

        if error:
            redirect_params = {"error": error}
            if error_description:
                redirect_params["error_description"] = error_description
            if clean_state:
                redirect_params["state"] = clean_state
            redirect_url = f"{original_redirect_uri}?{urlencode(redirect_params)}"
            return RedirectResponse(url=redirect_url, status_code=302)
        else:
            redirect_params = {"code": code}
            if clean_state:
                redirect_params["state"] = clean_state
            redirect_url = f"{original_redirect_uri}?{urlencode(redirect_params)}"
            return RedirectResponse(url=redirect_url, status_code=302)

    if error:
        html_content = f"""<!DOCTYPE html>
<html><head><title>OAuth Error</title></head>
<body><h1>Authorization Error</h1>
<p>Error: {html.escape(error)}</p>
<p>Description: {html.escape(error_description or 'No description')}</p>
</body></html>"""
    else:
        code_display = html.escape(code or "None")
        html_content = f"""<!DOCTYPE html>
<html><head><title>Authorization Successful</title></head>
<body><h1>Authorization Successful</h1>
<p>Authorization code: {code_display}</p>
<p>This window can be closed.</p>
<script>
if (window.opener) {{
    window.opener.postMessage({{
        type: 'oauth_callback',
        code: {json.dumps(code or "")},
        state: {json.dumps(state or "")}
    }}, '*');
    setTimeout(() => window.close(), 1500);
}}
</script>
</body></html>"""

    return Response(content=html_content, media_type="text/html")


async def proxy_oauth_request(config: MCPConfig, request: Request) -> Response:
    path = request.url.path.replace("/oauth", "/o", 1)
    query_string = request.url.query

    if "/authorize" in path and request.method == "GET":
        params = dict(request.query_params)
        original_redirect_uri = params.get("redirect_uri")

        if original_redirect_uri and not _validate_redirect_uri(original_redirect_uri):
            return JSONResponse(
                {
                    "error": "invalid_request",
                    "error_description": "Invalid redirect_uri parameter",
                },
                status_code=400,
            )

        if "state" in params and original_redirect_uri:
            state_value = params["state"]
            encoded_redirect = (
                base64.urlsafe_b64encode(original_redirect_uri.encode("utf-8"))
                .decode("utf-8")
                .rstrip("=")
            )
            params["state"] = f"{state_value}|{encoded_redirect}"

        if "redirect_uri" in params:
            params["redirect_uri"] = f"{config.server.base_url}/oauth/callback"
        if "scope" not in params or not params.get("scope"):
            params["scope"] = "read"
        query_string = urlencode(params)

    request_body: bytes | None = None
    if "/token" in path and request.method == "POST":
        request_body = await request.body()
        body_params = parse_qs(request_body.decode("utf-8"))
        if "redirect_uri" in body_params:
            body_params["redirect_uri"] = [f"{config.server.base_url}/oauth/callback"]
            request_body = urlencode({k: v[0] for k, v in body_params.items()}).encode(
                "utf-8"
            )

    target_url = f"{_proxy_base(config)}{path}"
    if query_string:
        target_url = f"{target_url}?{query_string}"

    try:
        return await _forward_and_build_response(
            config, request, target_url, content_override=request_body
        )
    except Exception as e:
        logger.error(f"OAuth proxy error: {e}")
        return Response(f"Proxy error: {str(e)}", status_code=502)


async def proxy_accounts_request(config: MCPConfig, request: Request) -> Response:
    path = request.url.path
    if path.startswith("/accounts/login"):
        path = "/login" + path[len("/accounts/login") :]
    query_string = request.url.query

    target_url = f"{_proxy_base(config)}{path}"
    if query_string:
        target_url = f"{target_url}?{query_string}"

    try:
        return await _forward_and_build_response(config, request, target_url)
    except Exception as e:
        logger.error(f"Accounts proxy error: {e}")
        return Response(f"Proxy error: {str(e)}", status_code=502)


async def proxy_login_request(config: MCPConfig, request: Request) -> Response:
    path = request.url.path
    query_string = request.url.query

    target_url = f"{_proxy_base(config)}{path}"
    if query_string:
        target_url = f"{target_url}?{query_string}"

    try:
        return await _forward_and_build_response(config, request, target_url)
    except Exception as e:
        logger.error(f"Login proxy error: {e}")
        return Response(f"Proxy error: {str(e)}", status_code=502)


async def proxy_static_request(config: MCPConfig, request: Request) -> Response:
    path = request.url.path
    query_string = request.url.query

    target_url = f"{_proxy_base(config)}{path}"
    if query_string:
        target_url = f"{target_url}?{query_string}"

    try:
        async with httpx.AsyncClient(
            verify=config.oauth.verify_ssl, timeout=config.oauth.timeout
        ) as client:
            headers = dict(request.headers)
            headers.pop("host", None)
            response = await client.get(target_url, headers=headers)

            resp_headers = dict(response.headers)
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=resp_headers,
            )
    except Exception as e:
        logger.error(f"Static proxy error: {e}")
        return Response(f"Proxy error: {str(e)}", status_code=502)
