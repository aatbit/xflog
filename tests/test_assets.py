import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from xflog.config import ASSETS


def test_gradio_javascript_entry_is_function_body_not_a_module():
    result = subprocess.run(
        [
            "node",
            "-e",
            "new Function('element', require('fs').readFileSync(process.argv[1], 'utf8'))",
            str(ASSETS / "app.js"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_brand_marks_are_self_contained_svg():
    for name in ("mark.svg", "wordmark.svg"):
        svg = ET.parse(ASSETS / name).getroot()
        assert svg.attrib["viewBox"]
        assert not svg.findall(".//{http://www.w3.org/2000/svg}text")
        assert not svg.findall(".//{http://www.w3.org/2000/svg}image")


def test_gradio_bundles_have_their_own_asset_namespace():
    source = (Path(__file__).parents[1] / "src/xflog/app.py").read_text()
    assert 'app.mount("/assets"' not in source
    assert 'app.mount("/static/xf"' in source


def test_font_really_has_variable_weights():
    import struct

    font = (ASSETS / "plex-sans-variable.ttf").read_bytes()
    count = struct.unpack_from(">H", font, 4)[0]
    tags = [font[12 + index * 16 : 16 + index * 16] for index in range(count)]
    assert b"fvar" in tags


def test_constellation_layout_and_motion_lifecycle():
    import json

    from xflog import audience_groups

    result = subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("constellation_check.mjs")),
            str(ASSETS),
            json.dumps(audience_groups.catalog(dict.fromkeys(audience_groups.MODULES, True))),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_selected_constellation_record_is_the_one_opened():
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("constellation_selection_check.mjs")), str(ASSETS)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_journal_groups_keep_records_order_and_collapsed_selection():
    import json

    from xflog import audience_groups

    result = subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("journal_check.mjs")),
            str(ASSETS),
            json.dumps(audience_groups.catalog(dict.fromkeys(audience_groups.MODULES, True))),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_browser_notification_permission_and_fallbacks():
    result = subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("notifications_check.mjs")),
            str(ASSETS / "notifications.js"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_shooting_star_intervals_and_fades():
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("shooting_star_check.mjs")), str(ASSETS)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_activity_readings_and_period_request_order():
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("activity_hud_check.mjs")), str(ASSETS)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_selected_signal_readout_uses_current_event_and_receipt_time():
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("selected_signal_check.mjs")), str(ASSETS)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
