import argparse
import asyncio
import logging

import httpx

from .config import Config, CoreConfig
from .errors import SetupError
from .tracking.transport import ProviderError, XClient, provider_http


async def lookup_user_id(handle: str | None) -> str:
    config = CoreConfig.from_env()
    async with provider_http() as http:
        return await XClient(config, http).lookup_user_id(handle)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="XFlog: run the UI or look up an X account ID.")
    commands = parser.add_subparsers(dest="command")
    lookup = commands.add_parser(
        "user-id", help="Look up an account ID (one X read; X charges may apply)."
    )
    target = lookup.add_mutually_exclusive_group(required=True)
    target.add_argument("handle", nargs="?", help="@handle, using X_APP_BEARER_TOKEN")
    target.add_argument("--me", action="store_true", help="Use X_USER_ACCESS_TOKEN (OAuth 2.0)")
    args = parser.parse_args(argv)
    if args.command == "user-id":
        try:
            print(asyncio.run(lookup_user_id(args.handle)))
        except (SetupError, ValueError) as error:
            raise SystemExit(str(error)) from None
        except ProviderError as error:
            raise SystemExit(
                f"X user lookup failed (HTTP {error.status}). "
                "Check the account, token permissions, API access and credits."
            ) from None
        except httpx.HTTPError:
            raise SystemExit("Could not reach X. Check your connection and try again.") from None
        return
    serve()


def serve() -> None:
    try:
        import uvicorn

        from .app import create_app
    except ModuleNotFoundError as error:
        if error.name not in {"uvicorn", "fastapi", "gradio"}:
            raise
        raise SystemExit(
            'The browser UI is optional. Install it with: pip install "xflog[ui]" '
            "(or use uv pip install with the same argument)."
        ) from None
    config = Config.from_env()
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
