import os
import re
import tomllib
from pathlib import Path


def release_version(tag: str, version: str) -> str:
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise ValueError("Release tags must be stable versions such as v1.0.0.")
    if tag[1:] != version:
        raise ValueError("The release tag must match the version in pyproject.toml.")
    return version


if __name__ == "__main__":
    project = tomllib.loads(Path("pyproject.toml").read_text())
    print(release_version(os.environ["RELEASE_TAG"], project["project"]["version"]))
