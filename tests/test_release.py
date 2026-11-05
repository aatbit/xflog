import runpy
from pathlib import Path

import pytest

release_version = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / ".github/scripts/release_version.py")
)["release_version"]


@pytest.mark.parametrize("version", ["1.0.0", "1.2.34", "2.0.0"])
def test_release_tag_matches_package(version):
    assert release_version(f"v{version}", version) == version


@pytest.mark.parametrize(
    "tag", ["v1.0.1", "1.0.0", "v01.0.0", "v1.0.0rc1", "v1.0.0\n", "v1.0.0; echo unsafe"]
)
def test_mismatched_or_invalid_release_tag_is_rejected(tag):
    with pytest.raises(ValueError):
        release_version(tag, "1.0.0")
