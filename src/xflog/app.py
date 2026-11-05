import asyncio
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import audience_groups
from .config import ASSETS, Config
from .errors import SetupError
from .history.demo import demo_activity, demo_history
from .history.demo import encounter_context as demo_encounter_context
from .history.filters import valid_filters
from .history.summary import PERIODS, SUBJECT_TYPES, activity_window, readings
from .history.timeline import Timeline, decode_cursor
from .interactions import TYPES, catalog
from .interactions.history import ThreadOptions
from .profile_names import ProfileNames
from .runtime import Runtime
from .tracking.collector import DEFAULT_SELECTION
from .tracking.transport import ProviderError
from .web.models import (
    AudiencePreferences,
    FollowChange,
    FollowTarget,
    Selection,
    StartRequest,
    ThreadRequest,
)
from .web.ui import mount_ui as mount_browser_ui


def create_app(config: Config | None = None, *, transport=None, mount_ui=True):
    config = config or Config.from_env()
    runtime = Runtime(config, transport=transport)
    store, collector = runtime.store, runtime.collector
    timeline = Timeline(store)
    profile_names = ProfileNames(store, runtime.client)
    follow_actions, interactions = runtime.follow_actions, runtime.interactions
    sessions = {}
    controls = asyncio.Lock()

    app = FastAPI(lifespan=runtime.lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.collector = store, collector
    app.state.client, app.state.sessions = runtime.client, sessions
    app.state.runtime = runtime
    app.state.follow_actions = follow_actions
    app.state.interactions = interactions
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
            "missing_settings": runtime.config.missing_settings(selection),
            "setup_message": runtime.identity_error or runtime.config.setup_message(selection),
            "environment_file": config.environment_file,
            "preference_warning": collector.preference_warning,
            "profile_warning": await store.setting("profile_warning", "")
            if selection.get("profile_names")
            else "",
            "tracking": await store.setting("tracking", False),
            "counts": await store.summary(account["id"]) if account else {},
            "gaps": await store.gaps(account["id"]) if account else [],
            "cleanup_warning": await store.setting("cleanup_warning", ""),
            "csrf": sessions[request.state.session]["csrf"],
            "notification_sequence": collector.notifications,
            "timeline_revision": await timeline.revision(account["id"]) if account else "0:0",
            "audience_groups": audience_groups.catalog(await store.setting("audience_groups", {})),
            "follow_actions": await follow_actions.status(),
            "interaction_types": catalog(),
        }

    @app.get("/api/activity-summary")
    async def activity_summary(period: str = "24h", subject: str = "followers", demo: bool = False):
        if period not in PERIODS or subject not in SUBJECT_TYPES:
            raise HTTPException(422, "Invalid activity period or audience.")
        if demo:
            return demo_activity(period, subject)
        window = activity_window(period)
        account = await store.setting("account")
        counts = await store.activity_counts(account["id"], window, subject) if account else {}
        return {**readings(counts, window, subject), "synthetic": False}

    @app.get("/api/timeline")
    async def timeline_history(kind: str = "all", subject: str = "followers", before: str = "0"):
        try:
            decode_cursor(before)
        except ValueError:
            raise HTTPException(422, "Invalid timeline cursor.") from None
        if not valid_filters(kind, subject, 0):
            raise HTTPException(422, "Invalid timeline filter.")
        account = await store.setting("account")
        if not account:
            return {"events": [], "next": None}
        result = await timeline.history(
            account["id"], {"kind": kind, "subject": subject, "before": before}
        )
        if await profile_names.ensure(result["events"]):
            result = await timeline.history(
                account["id"], {"kind": kind, "subject": subject, "before": before}
            )
        groups = await store.setting("audience_groups", {})
        result["events"] = await audience_groups.decorate_history(
            result["events"], groups, timeline.encounter_context
        )
        return result

    @app.get("/api/events")
    async def history(kind: str = "all", subject: str = "followers", before: int = 0):
        if not valid_filters(kind, subject, before):
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
        if not valid_filters(kind, subject, before):
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
        async with interactions.lock:
            previous = await store.setting("selection", DEFAULT_SELECTION)
            follow_setting = (
                selection.follow_actions if "follow_actions" in selection.model_fields_set else None
            )
            if follow_setting is not None:
                follow_actions.validate_setting(follow_setting)
            values = selection.model_dump(exclude={"follow_actions", "interactions"})
            if selection.interactions is not None:
                if selection.interactions.keys() - TYPES.keys():
                    raise HTTPException(422, "Unknown interaction type.")
                values["interactions"] = selection.interactions
            else:
                if "interactions" in previous:
                    values["interactions"] = previous["interactions"]
            interactions.validate_selection(values)
            result = await collector.save_preferences(values)
            if result["saved"] and selection.profile_names and not previous.get("profile_names"):
                await profile_names.retry_unresolved()
            if result["saved"] and follow_setting is not None:
                await follow_actions.configure(follow_setting)
            return result

    @app.post("/api/follow-actions/relationship")
    async def follow_relationship(target: FollowTarget):
        if target.demo:
            raise SetupError("Follow actions are unavailable in the offline demo.")
        return await follow_actions.relationship(target.event_id)

    @app.post("/api/follow-actions")
    async def change_follow(target: FollowChange):
        if target.demo:
            raise SetupError("Follow actions are unavailable in the offline demo.")
        return await follow_actions.change(target.event_id, target.following)

    @app.get("/api/interactions")
    async def person_interactions(event_id: str, before: int = 0, demo: bool = False):
        if not 0 <= before <= 9223372036854775807 or not 1 <= len(event_id) <= 200:
            raise HTTPException(422, "Invalid interaction query.")
        if demo:
            return {"interactions": [], "next": None}
        return await interactions.history(event_id, before)

    @app.post("/api/interactions/thread")
    async def thread_snapshot(body: ThreadRequest):
        if body.demo:
            raise SetupError("Thread loading is unavailable in the offline demo.")
        options = ThreadOptions(**body.model_dump(exclude={"event_id", "demo"}))
        return await interactions.thread(body.event_id, options)

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
        app = mount_browser_ui(app, config)
    else:

        @app.get("/")
        async def root():
            return {"app": "XFlog"}

    return app
