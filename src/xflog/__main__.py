import hashlib
import logging
from pathlib import Path

import uvicorn
from filelock import FileLock, Timeout

from .app import create_app
from .config import Config


def main():
    config = Config.from_env()
    lock_key = config.app_bearer or str(config.database.resolve())
    digest = hashlib.sha256(lock_key.encode()).hexdigest()[:24]
    lock_dir = Path.home() / ".local/share/xflog/locks"
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # One process per developer app also prevents duplicate streams across database paths.
    lock = FileLock(lock_dir / f"{digest}.lockfile", timeout=0)
    try:
        with lock:
            logging.getLogger("httpx").setLevel(logging.CRITICAL)
            logging.getLogger("httpcore").setLevel(logging.CRITICAL)
            uvicorn.run(
                create_app(config),
                host=config.host,
                port=config.port,
                access_log=False,
                proxy_headers=False,
            )
    except Timeout:
        raise SystemExit("XFlog is already running for this developer app. Open its existing tab.")


if __name__ == "__main__":
    main()
