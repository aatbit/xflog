import asyncio
from dataclasses import dataclass
from typing import Literal

from ..errors import SetupError
from ..tracking.collector import DEFAULT_SELECTION
from ..tracking.events import person_fields
from ..tracking.transport import ProviderError
from . import choices, numeric, parse_interaction, post_snapshot, selected
from .store import InteractionStore

THREAD_POST_FIELDS = "id,author_id,conversation_id,created_at,text"


@dataclass(frozen=True)
class ThreadOptions:
    """A saved interaction's thread request; X reads require accepted_costs=True."""

    sequence: int
    action: Literal["open", "cached", "more", "refresh"] = "open"
    checked_at: str | None = None
    offset: int = 0
    accepted_costs: bool = False

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or not 0 < self.sequence <= 9223372036854775807:
            raise ValueError("sequence must identify a saved interaction.")
        if not isinstance(self.action, str) or self.action not in {
            "open",
            "cached",
            "more",
            "refresh",
        }:
            raise ValueError("Invalid thread action.")
        if type(self.offset) is not int or not 0 <= self.offset <= 1000000:
            raise ValueError("offset must be between 0 and 1000000.")
        if self.checked_at is not None and not isinstance(self.checked_at, str):
            raise ValueError("checked_at must be a saved snapshot timestamp or None.")
        if type(self.accepted_costs) is not bool:
            raise ValueError("accepted_costs must be a boolean.")


class InteractionHistory:
    def __init__(self, store, identity):
        self.store = store
        self.identity = identity
        self.client = identity.client
        self.records = InteractionStore(store)
        self.lock = asyncio.Lock()

    def validate_selection(self, selection):
        if selected(selection) and not self.client.config.user_token.strip():
            raise SetupError(
                "Interaction tracking requires X_USER_ACCESS_TOKEN with users.read and tweet.read; likes also need like.read."
            )

    async def authorize(self, selection):
        self.validate_selection(selection)
        if selected(selection):
            await self.identity.verify_account()

    async def ingest(self, raw, selection):
        data = raw.get("data", raw) if isinstance(raw, dict) else None
        enabled_types = {kind.split(":", 1)[0] for kind in selected(selection)}
        if not isinstance(data, dict) or data.get("event_type") not in enabled_types:
            return False
        account = self.client.config.user_id
        event = parse_interaction(raw, account, choices(selection))
        if event and choices(selection).get(event["key"]):
            groups = await self.store.setting("audience_groups", {})
            users = (data.get("includes") or {}).get("users", [])
            if isinstance(users, dict):
                users = users.get("data", [])
            event["profiles"] = {}
            if isinstance(users, list):
                event["profiles"] = {
                    user["id"]: person_fields(user, groups)
                    for user in users
                    if isinstance(user, dict)
                    and numeric(user.get("id"))
                    and user["id"] in event["people"]
                }
            return await self.records.insert(account, event)
        return False

    async def person(self, event_id):
        account = await self.store.setting("account")
        if not account or account.get("id") != self.client.config.user_id:
            raise SetupError("The configured account is unavailable.")
        person = await self.store.event_actor(account["id"], event_id)
        if not numeric(person) or person == account["id"]:
            raise SetupError("Choose a recorded person from this account’s history.")
        return person

    async def history(self, event_id: str, before: int = 0) -> dict:
        person = await self.person(event_id)
        return await self.records.history(
            self.client.config.user_id, {"person": person, "before": before}
        )

    async def api(self, path, params):
        try:
            response = await self.client.user_request("GET", path, params=params)
        except ProviderError as error:
            if error.status == 401:
                self.identity.verified_account = False
            raise SetupError(
                "X could not load this thread. Check token permissions, search access and credits; saved posts are kept."
            )
        if len(response.content) > 6_000_000:
            raise SetupError("X returned an oversized thread page. Saved posts are kept.")
        try:
            body = response.json()
            if not isinstance(body, dict) or body.get("errors"):
                raise ValueError
            return body
        except ValueError:
            raise SetupError("X returned an incomplete result. Saved posts are kept.")

    async def authorize_load(self, request):
        selection = await self.store.setting("selection", DEFAULT_SELECTION)
        if not selected(selection):
            raise SetupError("Enable an interaction type in Profile before loading from X.")
        if not request.accepted_costs:
            raise SetupError("Confirm X read charges before loading a thread.")
        await self.authorize(selection)

    async def resolve_post(self, post_id):
        body = await self.api(f"/2/tweets/{post_id}", {"tweet.fields": THREAD_POST_FIELDS})
        try:
            post = post_snapshot(body.get("data"))
            if post["id"] != post_id or not numeric(post["conversation_id"]):
                raise ValueError
        except ValueError:
            raise SetupError("X did not supply this post’s conversation. Saved posts are kept.")
        await self.records.remember_posts(self.client.config.user_id, [post])
        return post["conversation_id"]

    async def fetch_page(self, conversation, token):
        params = {
            "query": f"conversation_id:{conversation}",
            "max_results": 100,
            "tweet.fields": THREAD_POST_FIELDS,
            "sort_order": "recency",
        }
        if token:
            params["next_token"] = token
        body = await self.api("/2/tweets/search/all", params)
        try:
            data = body.get("data", [])
            meta = body.get("meta")
            if not isinstance(data, list) or len(data) > 100 or not isinstance(meta, dict):
                raise ValueError
            if type(meta.get("result_count")) is not int or meta["result_count"] != len(data):
                raise ValueError
            posts = [post_snapshot(post) for post in data]
            if any(
                post["conversation_id"] != conversation or post["text"] is None for post in posts
            ):
                raise ValueError
            next_token = meta.get("next_token")
            if next_token is not None and (
                not isinstance(next_token, str)
                or not 1 <= len(next_token) <= 2000
                or next_token == token
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise SetupError("X returned an incomplete thread page. Saved posts are kept.")
        return {"conversation": conversation, "posts": posts, "next_token": next_token}

    async def thread(self, event_id: str, request: ThreadOptions) -> dict:
        async with self.lock:
            person = await self.person(event_id)
            account = self.client.config.user_id
            record = await self.records.interaction(
                account, {"person": person, "sequence": request.sequence}
            )
            if not record:
                raise SetupError("Choose an interaction from this person’s saved history.")
            conversation = record["conversation_id"]
            if not numeric(conversation):
                if request.action != "open":
                    raise SetupError("Load this thread first.")
                await self.authorize_load(request)
                conversation = await self.resolve_post(record["id"])
            cached = await self.records.snapshot(account, conversation)
            fetch = (request.action == "open" and cached is None) or request.action in {
                "refresh",
                "more",
            }
            if fetch and cached and request.checked_at != cached["checked_at"]:
                fetch = False
            if request.action == "cached" and cached is None:
                raise SetupError("Load this thread first.")
            if request.action == "more" and (not cached or not cached["next_token"]):
                fetch = False
            if fetch:
                await self.authorize_load(request)
                token = cached["next_token"] if request.action == "more" and cached else None
                page = await self.fetch_page(conversation, token)
                await self.records.save_thread(account, page)
                cached = await self.records.snapshot(account, conversation)
            if not cached:
                raise SetupError("Load this thread first.")
            result = await self.records.thread(
                account,
                {
                    "conversation": conversation,
                    "offset": request.offset if request.action == "cached" else 0,
                },
            )
            return {
                **result,
                "conversation_id": conversation,
                "checked_at": cached["checked_at"],
                "more_available": bool(cached["next_token"]),
                "fetched": fetch,
            }
