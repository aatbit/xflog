import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .interactions import selected

API_ROOT = "https://api.x.com"
ASSETS = Path(__file__).parent / "assets"


@dataclass(frozen=True)
class CoreConfig:
    """Single-account storage and X credentials, independent of any web server."""

    database: Path
    app_bearer: str = field(default="", repr=False)
    user_id: str = ""
    user_token: str = field(default="", repr=False)
    environment_file: str = ""
    user_refresh_token: str = field(default="", repr=False)
    client_id: str = field(default="", repr=False)
    client_secret: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.user_id and not re.fullmatch(r"[0-9]{1,19}", self.user_id):
            raise ValueError("X_USER_ID must be the numeric target account ID.")
        if self.user_refresh_token and not (self.client_id and self.user_token):
            raise ValueError("X_USER_REFRESH_TOKEN needs X_CLIENT_ID and X_USER_ACCESS_TOKEN.")

    def missing_settings(self, selection: dict) -> list[str]:
        required = {"X_APP_BEARER_TOKEN": self.app_bearer}
        if not self.user_token.strip():
            required["X_USER_ID"] = self.user_id
        if selection.get("subscriptions") or selected(selection):
            required["X_USER_ACCESS_TOKEN"] = self.user_token
        return [name for name, value in required.items() if not value.strip()]

    def setup_message(self, selection: dict) -> str:
        missing = self.missing_settings(selection)
        return (
            f"Missing server settings: {', '.join(missing)}. "
            f"Set them in {self.environment_file or 'the server environment'} and restart XFlog."
            if missing
            else ""
        )

    @classmethod
    def from_env(cls) -> "CoreConfig":
        return cls(
            database=Path(
                os.getenv("XFLOG_DATABASE", "~/.local/share/xflog/history.sqlite3")
            ).expanduser(),
            app_bearer=os.getenv("X_APP_BEARER_TOKEN", ""),
            user_id=os.getenv("X_USER_ID", ""),
            user_token=os.getenv("X_USER_ACCESS_TOKEN", ""),
            environment_file=os.getenv("XFLOG_ENV_FILE", ""),
            user_refresh_token=os.getenv("X_USER_REFRESH_TOKEN", ""),
            client_id=os.getenv("X_CLIENT_ID", ""),
            client_secret=os.getenv("X_CLIENT_SECRET", ""),
        )


@dataclass(frozen=True)
class Config(CoreConfig):
    """Self-hosted browser settings; core callers only need CoreConfig."""

    origin: str = "http://127.0.0.1:7860"
    host: str = "127.0.0.1"
    port: int = 7860
    admin_password: str = field(default="", repr=False)
    loopback_published: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        parsed = urlsplit(self.origin)
        origin_port = parsed.port
        if (
            not parsed.hostname
            or parsed.scheme not in {"http", "https"}
            or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"})
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or any(character.isspace() for character in self.origin)
        ):
            raise ValueError(
                "XFLOG_ORIGIN must be an HTTPS origin (or HTTP loopback), without a path."
            )
        if parsed.scheme == "http" and not origin_port:
            raise ValueError("XFLOG_ORIGIN must include the local server port.")
        if self.host not in {"127.0.0.1", "localhost", "0.0.0.0", "::1", "::"}:
            raise ValueError("XFLOG_HOST must be a loopback or wildcard bind address.")
        if not 1 <= self.port <= 65535:
            raise ValueError("XFLOG_PORT must be between 1 and 65535.")
        if self.admin_password and (
            len(self.admin_password) < 16 or not self.admin_password.isascii()
        ):
            raise ValueError("XFLOG_ADMIN_PASSWORD must contain at least 16 ASCII characters.")
        if not isinstance(self.loopback_published, bool):
            raise ValueError("loopback_published must be a boolean deployment setting.")
        local_origin = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        local_binding = self.host in {"127.0.0.1", "localhost", "::1"} or self.loopback_published
        if not self.admin_password and not (local_origin and local_binding):
            raise ValueError("Remote access requires XFLOG_ADMIN_PASSWORD.")

    @property
    def secure(self) -> bool:
        return urlsplit(self.origin).scheme == "https"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            **vars(CoreConfig.from_env()),
            origin=os.getenv("XFLOG_ORIGIN", "http://127.0.0.1:7860"),
            host=os.getenv("XFLOG_HOST", "127.0.0.1"),
            port=int(os.getenv("XFLOG_PORT", "7860")),
            admin_password=os.getenv("XFLOG_ADMIN_PASSWORD", ""),
            loopback_published=os.getenv("XFLOG_LOOPBACK_PUBLISHED", "").lower() in {"1", "true"},
        )
