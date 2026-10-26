import asyncio
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import gradio as gr
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import audience_groups
from .collector import DEFAULT_SELECTION, Collector
from .config import ASSETS, Config
from .demo import demo_history
from .demo import encounter_context as demo_encounter_context
from .errors import SetupError
from .storage import Store
from .transport import ProviderError, XClient


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    followers: StrictBool = True
    subscriptions: StrictBool = False
    notifications: StrictBool = False


class StartRequest(BaseModel):
    accepted_costs: StrictBool


class AudiencePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: dict[str, StrictBool]


def create_app(config: Config | None = None, *, transport=None, mount_ui=True):
    config = config or Config.from_env()
    store = Store(config.database)
    http = httpx.AsyncClient(
        timeout=20, transport=transport, trust_env=False, follow_redirects=False
    )
    client = XClient(config, http)
    collector = Collector(store, client)
    sessions = {}
    controls = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        await store.open()
        try:
            await collector.initialize()
            yield
        finally:
            await collector.shutdown()
            await http.aclose()
            await store.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.collector = store, collector
    app.state.client, app.state.sessions = client, sessions
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(config.origin).hostname])
    basic_auth = HTTPBasic(auto_error=False)

    @app.middleware("http")
    async def instance_security(request: Request, call_next):
        if request.headers.get("host") != urlsplit(config.origin).netloc:
            return JSONResponse({"detail": "Use the configured XFlog address."}, status_code=403)
        if request.url.path != "/healthz" and config.admin_password:
            try:
                credentials = await basic_auth(request)
            except HTTPException:
                credentials = None
            if not credentials or not (
                secrets.compare_digest(credentials.username.encode(), b"xflog")
                and secrets.compare_digest(
                    credentials.password.encode(), config.admin_password.encode()
                )
            ):
                return JSONResponse(
                    {"detail": "Instance authentication required."},
                    status_code=401,
                    headers={
                        "WWW-Authenticate": 'Basic realm="XFlog", charset="UTF-8"',
                        "Cache-Control": "no-store",
                    },
                )
        if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
            return JSONResponse(
                {"detail": "Open XFlog directly on its configured address."},
                status_code=403,
            )
        session = request.cookies.get("xflog_session")
        now = time.monotonic()
        fresh = False
        if request.url.path == "/" and request.method == "GET":
            for key in [key for key, value in sessions.items() if value["expires"] < now]:
                sessions.pop(key)
            if session not in sessions:
                if len(sessions) >= 100:
                    return JSONResponse(
                        {"detail": "Too many local browser sessions."}, status_code=429
                    )
                session = secrets.token_urlsafe(32)
                sessions[session] = {
                    "csrf": secrets.token_urlsafe(32),
                    "expires": now + 86400,
                }
                fresh = True
        protected = request.url.path.startswith("/api/")
        current = sessions.get(session)
        if protected and (not current or current["expires"] < now):
            return JSONResponse(
                {"detail": "Reload XFlog to begin a local session."}, status_code=401
            )
        if protected and request.method not in {"GET", "HEAD"}:
            if request.headers.get("origin") != config.origin or not secrets.compare_digest(
                request.headers.get("x-xflog-csrf", ""), current["csrf"]
            ):
                return JSONResponse(
                    {"detail": "Request could not be verified. Reload XFlog."},
                    status_code=403,
                )
        request.state.session = session
        response = await call_next(request)
        if fresh:
            response.set_cookie(
                "xflog_session",
                session,
                httponly=True,
                secure=config.secure,
                samesite="lax",
                max_age=86400,
            )
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
            }
        )
        return response

    @app.exception_handler(SetupError)
    @app.exception_handler(ProviderError)
    async def known_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def database_error(request, error):
        return JSONResponse(
            {"detail": "Local database unavailable. Check disk space and file access."},
            status_code=503,
        )

    @app.exception_handler(httpx.HTTPError)
    async def network_error(request, error):
        return JSONResponse(
            {"detail": "Could not reach X. Check your connection and retry."},
            status_code=502,
        )

    @app.get("/api/status")
    async def status(request: Request):
        account = await store.setting("account")
        selection = await store.setting("selection", DEFAULT_SELECTION)
        return {
            "account": account,
            "connected": collector.connected,
            "state": collector.state,
            "message": collector.message,
            "selection": selection,
            "missing_settings": config.missing_settings(selection),
            "setup_message": config.setup_message(selection),
            "environment_file": config.environment_file,
            "preference_warning": collector.preference_warning,
            "tracking": await store.setting("tracking", False),
            "counts": await store.summary(account["id"]) if account else {},
            "gaps": await store.gaps(account["id"]) if account else [],
            "cleanup_warning": await store.setting("cleanup_warning", ""),
            "csrf": sessions[request.state.session]["csrf"],
            "notification_sequence": collector.notifications,
            "audience_groups": audience_groups.catalog(await store.setting("audience_groups", {})),
        }

    @app.get("/api/events")
    async def history(kind: str = "all", subject: str = "followers", before: int = 0):
        if (
            kind not in {"all", "gained", "lost"}
            or subject not in {"followers", "subscriptions"}
            or before < 0
        ):
            raise HTTPException(422, "Invalid history filter.")
        account = await store.setting("account")
        if not account:
            return {"events": [], "next": None}
        result = await store.history(
            account["id"], {"kind": kind, "subject": subject, "before": before}
        )
        groups = await store.setting("audience_groups", {})
        result["events"] = await audience_groups.decorate_history(
            result["events"], groups, store.encounter_context
        )
        return result

    @app.get("/api/demo")
    async def demo(kind: str = "all", subject: str = "followers", before: int = 0):
        if (
            kind not in {"all", "gained", "lost"}
            or subject not in {"followers", "subscriptions"}
            or before < 0
        ):
            raise HTTPException(422, "Invalid demo filter.")
        result = demo_history({"kind": kind, "subject": subject, "before": before})
        groups = await store.setting("audience_groups", {})
        result["events"] = await audience_groups.decorate_history(
            result["events"], groups, demo_encounter_context
        )
        return result

    @app.post("/api/audience-groups")
    async def save_audience_groups(settings: AudiencePreferences):
        if settings.enabled.keys() - audience_groups.MODULES.keys():
            raise HTTPException(422, "Unknown audience group.")
        async with controls:
            previous = audience_groups.preferences(await store.setting("audience_groups", {}))
            enabled = {**previous, **settings.enabled}
            await store.save_setting("audience_groups", enabled)
        return {"audience_groups": audience_groups.catalog(enabled)}

    @app.post("/api/preferences")
    async def preferences(selection: Selection):
        return await collector.save_preferences(selection.model_dump())

    @app.post("/api/start")
    async def start(body: StartRequest):
        if not body.accepted_costs:
            raise HTTPException(422, "Review billing and explicitly accept before starting.")
        async with controls:
            await collector.start()
        return {"started": True}

    @app.post("/api/stop")
    async def stop():
        async with controls:
            await collector.stop()
        return {"stopped": True}

    app.mount("/static/xf", StaticFiles(directory=ASSETS), name="assets")

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    if mount_ui:
        with gr.Blocks(title="XFlog — X Follower Log", analytics_enabled=False) as ui:
            gr.HTML(
                (ASSETS / "shell.html").read_text(),
                apply_default_css=False,
                js_on_load=(ASSETS / "app.js").read_text(),
                elem_id="xflog-root",
            )
        app = gr.mount_gradio_app(
            app,
            ui,
            path="/",
            server_name=config.host,
            footer_links=[],
            css_paths=[
                ASSETS / name
                for name in (
                    "app.css",
                    "timeline.css",
                    "constellation.css",
                    "settings.css",
                    "responsive.css",
                )
            ],
            favicon_path=str(ASSETS / "mark.svg"),
            head='<link rel="stylesheet" href="/static/xf/fonts.css">',
            show_error=False,
            ssr_mode=False,
            enable_monitoring=False,
        )
    else:

        @app.get("/")
        async def root():
            return {"app": "XFlog"}

    return app
