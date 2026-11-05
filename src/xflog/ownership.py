"""Host-local ownership shared by CLI, ASGI and library runtimes."""

import hashlib
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator

from filelock import FileLock, Timeout

from .config import CoreConfig
from .errors import RuntimeBusyError


@contextmanager
def runtime_ownership(config: CoreConfig) -> Iterator[None]:
    directory = Path.home() / ".local/share/xflog/locks"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    database_key = str(config.database.resolve())
    digest = hashlib.sha256(database_key.encode()).hexdigest()[:24]
    names = [f"database-{digest}"]
    if config.app_bearer:
        # Retain the CLI's app key so old and new entry points exclude each other.
        names.append(hashlib.sha256(config.app_bearer.encode()).hexdigest()[:24])
    else:
        names.append(digest)
    with ExitStack() as locks:
        for name in names:
            try:
                locks.enter_context(FileLock(directory / f"{name}.lockfile", timeout=0))
            except Timeout:
                raise RuntimeBusyError(
                    "XFlog is already running for this developer app or database."
                ) from None
        yield
