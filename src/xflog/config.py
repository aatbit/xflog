import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

API_ROOT = "https://api.x.com"
ASSETS = Path(__file__).parent / "assets"


@dataclass(frozen=True)
class Config:
    database: Path
    app_bearer: str = field(default="", repr=False)
    user_id: str = ""
    user_token: str = field(default="", repr=False)
    origin: str = "http://127.0.0.1:7860"
    host: str = "127.0.0.1"
    port: int = 7860
    admin_password: str = field(default="", repr=False)

    def __post_init__(self):
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
        if self.user_id and not re.fullmatch(r"[0-9]{1,19}", self.user_id):
            raise ValueError("X_USER_ID must be the numeric target account ID.")
        if self.admin_password and (
            len(self.admin_password) < 16 or not self.admin_password.isascii()
        ):
            raise ValueError("XFLOG_ADMIN_PASSWORD must contain at least 16 ASCII characters.")
        if (
            self.secure or self.host not in {"127.0.0.1", "localhost", "::1"}
        ) and not self.admin_password:
            raise ValueError("Hosted binding requires XFLOG_ADMIN_PASSWORD.")

    @property
    def secure(self) -> bool:
        return urlsplit(self.origin).scheme == "https"

    @classmethod
    def from_env(cls):
        return cls(
            database=Path(
                os.getenv("XFLOG_DATABASE", "~/.local/share/xflog/history.sqlite3")
            ).expanduser(),
            app_bearer=os.getenv("X_APP_BEARER_TOKEN", ""),
            user_id=os.getenv("X_USER_ID", ""),
            user_token=os.getenv("X_USER_ACCESS_TOKEN", ""),
            origin=os.getenv("XFLOG_ORIGIN", "http://127.0.0.1:7860"),
            host=os.getenv("XFLOG_HOST", "127.0.0.1"),
            port=int(os.getenv("XFLOG_PORT", "7860")),
            admin_password=os.getenv("XFLOG_ADMIN_PASSWORD", ""),
        )
