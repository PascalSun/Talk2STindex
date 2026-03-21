"""MCP server configuration management."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from talk2stindex.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OAuthConfig:
    """OAuth/OIDC configuration."""

    discovery_url: str = "http://localhost:8000/o/.well-known/openid-configuration"
    public_base_url: str = "http://localhost:8000/o"
    internal_base_url: str | None = None
    client_id: str = "talk2stindex-mcp-client"
    client_secret: str = "test"
    use_introspection: bool = True
    verify_ssl: bool = False
    timeout: float = 60.0
    protect_mcp: bool = True


@dataclass
class ServerConfig:
    """MCP server configuration."""

    host: str = "0.0.0.0"
    port: int = 8016
    base_url: str = "http://localhost:8016"


@dataclass
class RestAuthConfig:
    verify_url: str | None = None
    token: str | None = None
    verify_ssl: bool = False
    timeout: float = 60.0
    cache_ttl_seconds: float = 30.0


@dataclass
class DevConfig:
    console_password: str | None = None
    console_secret: str | None = None


@dataclass
class AwsConfig:
    access_key_id: str | None = None
    secret_access_key: str | None = None
    session_token: str | None = None
    region: str | None = None
    endpoint_url: str | None = None


@dataclass
class LlmConfig:
    """Cloud LLM API keys used by stindex for entity extraction."""

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None


def _inject_llm_env(llm: LlmConfig) -> None:
    """Push LLM keys from config into os.environ (env vars already set take priority)."""
    mapping = {
        "ANTHROPIC_API_KEY": llm.anthropic_api_key,
        "OPENAI_API_KEY": llm.openai_api_key,
        "GOOGLE_API_KEY": llm.google_api_key,
    }
    for env_var, value in mapping.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value


@dataclass
class MCPConfig:
    """Main MCP configuration."""

    server: ServerConfig = field(default_factory=ServerConfig)
    oauth: OAuthConfig = field(default_factory=OAuthConfig)
    rest_auth: RestAuthConfig = field(default_factory=RestAuthConfig)
    dev: DevConfig = field(default_factory=DevConfig)
    aws: AwsConfig = field(default_factory=AwsConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)

    @classmethod
    def from_file(cls, config_path: str | Path) -> MCPConfig:
        """Load configuration from YAML file."""
        config_path = Path(config_path)

        if not config_path.exists():
            logger.warning(f"Config file not found: {config_path}, using defaults")
            return cls()

        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}

            server_data = data.get("server", {})
            server = ServerConfig(
                host=server_data.get("host", "0.0.0.0"),
                port=server_data.get("port", 8016),
                base_url=server_data.get("base_url", "http://localhost:8016"),
            )

            oauth_data = data.get("oauth", {})
            oauth = OAuthConfig(
                discovery_url=oauth_data.get(
                    "discovery_url",
                    "http://localhost:8000/o/.well-known/openid-configuration",
                ),
                public_base_url=oauth_data.get(
                    "public_base_url", "http://localhost:8000/o"
                ),
                internal_base_url=oauth_data.get("internal_base_url"),
                client_id=oauth_data.get("client_id", "talk2stindex-mcp-client"),
                client_secret=oauth_data.get("client_secret", "test"),
                use_introspection=oauth_data.get("use_introspection", True),
                verify_ssl=oauth_data.get("verify_ssl", False),
                timeout=oauth_data.get("timeout", 60.0),
                protect_mcp=oauth_data.get("protect_mcp", True),
            )

            rest_auth_data = data.get("rest_auth", {})
            rest_auth = RestAuthConfig(
                verify_url=rest_auth_data.get("verify_url"),
                token=rest_auth_data.get("token"),
                verify_ssl=rest_auth_data.get("verify_ssl", False),
                timeout=rest_auth_data.get("timeout", 60.0),
                cache_ttl_seconds=rest_auth_data.get("cache_ttl_seconds", 30.0),
            )

            dev_data = data.get("dev", {})
            dev = DevConfig(
                console_password=dev_data.get("console_password"),
                console_secret=dev_data.get("console_secret"),
            )

            aws_data = data.get("aws", {})
            aws = AwsConfig(
                access_key_id=aws_data.get("access_key_id"),
                secret_access_key=aws_data.get("secret_access_key"),
                session_token=aws_data.get("session_token"),
                region=aws_data.get("region"),
                endpoint_url=aws_data.get("endpoint_url"),
            )

            llm_data = data.get("llm", {})
            llm = LlmConfig(
                anthropic_api_key=llm_data.get("anthropic_api_key"),
                openai_api_key=llm_data.get("openai_api_key"),
                google_api_key=llm_data.get("google_api_key"),
            )
            _inject_llm_env(llm)

            logger.info(f"Loaded configuration from {config_path}")
            return cls(
                server=server,
                oauth=oauth,
                rest_auth=rest_auth,
                dev=dev,
                aws=aws,
                llm=llm,
            )

        except Exception as e:
            logger.error(f"Failed to load config from {config_path}: {e}")
            logger.info("Using default configuration")
            return cls()

    @classmethod
    def from_env(cls) -> MCPConfig:
        """Load configuration from environment variables."""
        server = ServerConfig(
            host=os.getenv("MCP_HOST", "0.0.0.0"),
            port=int(os.getenv("MCP_PORT", "8016")),
            base_url=os.getenv("MCP_BASE_URL", "http://localhost:8016"),
        )

        oauth = OAuthConfig(
            discovery_url=os.getenv(
                "OIDC_DISCOVERY_URL",
                "http://localhost:8000/o/.well-known/openid-configuration",
            ),
            public_base_url=os.getenv(
                "OIDC_PUBLIC_BASE_URL", "http://localhost:8000/o"
            ),
            internal_base_url=os.getenv("OIDC_INTERNAL_BASE_URL") or None,
            client_id=os.getenv("OIDC_CLIENT_ID", "talk2stindex-mcp-client"),
            client_secret=os.getenv("OIDC_CLIENT_SECRET", "test"),
            use_introspection=os.getenv("OIDC_USE_INTROSPECTION", "true").lower()
            in ("true", "1", "yes"),
            verify_ssl=os.getenv("OIDC_VERIFY_SSL", "false").lower()
            in ("true", "1", "yes"),
            timeout=float(os.getenv("OIDC_TIMEOUT", "60.0")),
            protect_mcp=os.getenv("OIDC_PROTECT_MCP", "true").lower()
            in ("true", "1", "yes"),
        )

        rest_auth = RestAuthConfig(
            verify_url=os.getenv("REST_AUTH_VERIFY_URL"),
            token=os.getenv("REST_AUTH_TOKEN"),
            verify_ssl=os.getenv("REST_AUTH_VERIFY_SSL", "false").lower()
            in ("true", "1", "yes"),
            timeout=float(os.getenv("REST_AUTH_TIMEOUT", "60.0")),
            cache_ttl_seconds=float(os.getenv("REST_AUTH_CACHE_TTL_SECONDS", "30.0")),
        )

        dev = DevConfig(
            console_password=os.getenv("TALK2STINDEX_CONSOLE_PASSWORD"),
            console_secret=os.getenv("TALK2STINDEX_CONSOLE_SECRET"),
        )

        aws = AwsConfig(
            access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            session_token=os.getenv("AWS_SESSION_TOKEN"),
            region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
            endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
        )

        llm = LlmConfig(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )

        return cls(
            server=server,
            oauth=oauth,
            rest_auth=rest_auth,
            dev=dev,
            aws=aws,
            llm=llm,
        )

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> MCPConfig:
        """Load configuration with priority: env vars > config file > defaults."""
        if config_path is None:
            config_path = Path.cwd() / "config.mcp.yml"

        config = cls.from_file(config_path)

        env_config = cls.from_env()

        env_overrides = {
            "MCP_HOST": ("server", "host"),
            "MCP_PORT": ("server", "port"),
            "MCP_BASE_URL": ("server", "base_url"),
            "OIDC_DISCOVERY_URL": ("oauth", "discovery_url"),
            "OIDC_PUBLIC_BASE_URL": ("oauth", "public_base_url"),
            "OIDC_INTERNAL_BASE_URL": ("oauth", "internal_base_url"),
            "OIDC_CLIENT_ID": ("oauth", "client_id"),
            "OIDC_CLIENT_SECRET": ("oauth", "client_secret"),
            "OIDC_USE_INTROSPECTION": ("oauth", "use_introspection"),
            "OIDC_VERIFY_SSL": ("oauth", "verify_ssl"),
            "OIDC_TIMEOUT": ("oauth", "timeout"),
            "OIDC_PROTECT_MCP": ("oauth", "protect_mcp"),
            "REST_AUTH_VERIFY_URL": ("rest_auth", "verify_url"),
            "REST_AUTH_TOKEN": ("rest_auth", "token"),
            "REST_AUTH_VERIFY_SSL": ("rest_auth", "verify_ssl"),
            "REST_AUTH_TIMEOUT": ("rest_auth", "timeout"),
            "REST_AUTH_CACHE_TTL_SECONDS": ("rest_auth", "cache_ttl_seconds"),
            "TALK2STINDEX_CONSOLE_PASSWORD": ("dev", "console_password"),
            "TALK2STINDEX_CONSOLE_SECRET": ("dev", "console_secret"),
            "AWS_ACCESS_KEY_ID": ("aws", "access_key_id"),
            "AWS_SECRET_ACCESS_KEY": ("aws", "secret_access_key"),
            "AWS_SESSION_TOKEN": ("aws", "session_token"),
            "AWS_REGION": ("aws", "region"),
            "AWS_DEFAULT_REGION": ("aws", "region"),
            "AWS_ENDPOINT_URL": ("aws", "endpoint_url"),
            "ANTHROPIC_API_KEY": ("llm", "anthropic_api_key"),
            "OPENAI_API_KEY": ("llm", "openai_api_key"),
            "GOOGLE_API_KEY": ("llm", "google_api_key"),
        }

        for env_var, (section, attr) in env_overrides.items():
            if os.getenv(env_var):
                section_obj = getattr(config, section)
                env_section_obj = getattr(env_config, section)
                setattr(section_obj, attr, getattr(env_section_obj, attr))

        # Ensure LLM keys are injected into os.environ
        _inject_llm_env(config.llm)

        return config

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "base_url": self.server.base_url,
            },
            "oauth": {
                "discovery_url": self.oauth.discovery_url,
                "public_base_url": self.oauth.public_base_url,
                "internal_base_url": self.oauth.internal_base_url,
                "client_id": self.oauth.client_id,
                "use_introspection": self.oauth.use_introspection,
                "verify_ssl": self.oauth.verify_ssl,
                "timeout": self.oauth.timeout,
                "protect_mcp": self.oauth.protect_mcp,
            },
            "rest_auth": {
                "verify_url": self.rest_auth.verify_url,
                "verify_ssl": self.rest_auth.verify_ssl,
                "timeout": self.rest_auth.timeout,
                "cache_ttl_seconds": self.rest_auth.cache_ttl_seconds,
            },
            "dev": {},
            "aws": {
                "access_key_id": None,
                "secret_access_key": None,
                "session_token": None,
                "region": self.aws.region,
                "endpoint_url": self.aws.endpoint_url,
            },
        }
