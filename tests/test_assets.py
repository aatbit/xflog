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


def test_memory_strand_geometry_matches_native_scroll_and_alternates():
    import json

    script = f"""
    import {{ strandGeometry }} from {json.dumps((ASSETS / "strand.js").as_uri())};
    import assert from 'node:assert/strict';
    for (const viewport of [375, 768, 1440]) {{
      for (const count of [0, 1, 2, 25, 50]) {{
        const geometry = strandGeometry(count, viewport, 480);
        assert.equal(geometry.points.length, count);
        assert.ok(Math.abs(geometry.width - viewport - Math.max(0,count-1)*geometry.spacing) < 0.001);
        geometry.points.forEach((point,index) => {{
          assert.equal(point.x, viewport/2 + (count-1-index)*geometry.spacing);
          assert.equal(point.above, (count-1-index)%2===0);
          assert.ok(point.y > 0 && point.y < 480);
          assert.equal((point.y<240), point.above);
        }});
        assert.ok(!geometry.front.includes('NaN'));
        assert.ok(!geometry.back.includes('NaN'));
      }}
    }}
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_strand_fit_zoom_and_motion_are_bounded():
    import json

    script = f"""
    import {{ strandGeometry, flowStep, wheelDistance }} from {json.dumps((ASSETS / "strand.js").as_uri())};
    import assert from 'node:assert/strict';
    for (const viewport of [375, 768, 1440]) {{
      for (const count of [0, 1, 2, 25, 50]) {{
        const fit = strandGeometry(count, viewport, 480, 0);
        assert.equal(fit.width, viewport);
        assert.equal(fit.canPan, false);
        assert.ok(fit.points.every(p => p.x >= 0 && p.x <= viewport));
        let previous = fit.spacing;
        for (const zoom of [0.05, 0.25, 1, 2]) {{
          const geometry = strandGeometry(count, viewport, 480, zoom);
          assert.ok(geometry.spacing >= previous);
          assert.ok(geometry.points.every(p => p.x >= 0 && p.x <= geometry.width));
          assert.ok(!geometry.front.includes('NaN'));
          previous = geometry.spacing;
        }}
      }}
    }}
    let position = 0;
    for (let frame = 0; frame < 120; frame++) {{
      const next = flowStep(position, 1000, 16);
      assert.ok(next > position && next <= 1000);
      position = next;
    }}
    assert.ok(1000 - position < 1);
    assert.equal(flowStep(42, 42, 16), 42);
    assert.ok(flowStep(100, 0, 16) > 0);
    assert.ok(Math.abs(flowStep(flowStep(0, 100, 8), 100, 8) - flowStep(0, 100, 16)) < 0.001);
    assert.equal(wheelDistance({{deltaX:0,deltaY:2,deltaMode:1}}, 1000), 48.6);
    assert.equal(wheelDistance({{deltaX:-20,deltaY:2,deltaMode:0}}, 1000), -27);
    assert.equal(wheelDistance({{deltaX:0,deltaY:1,deltaMode:2}}, 1000), 700);
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_living_helix_keeps_chronology_stable_through_a_full_turn():
    import json

    script = f"""
    import {{ strandGeometry, reverseIndex, wheelDistance }} from {json.dumps((ASSETS / "strand.js").as_uri())};
    import {{ projectHelixPoint }} from {json.dumps((ASSETS / "strand-life.js").as_uri())};
    import assert from 'node:assert/strict';
    for (const width of [375, 768, 1440]) {{
      for (const count of [1, 2, 25, 50]) {{
        for (const zoom of [0, 0.25, 1, 2]) {{
          const geometry = strandGeometry(count, width, 560, zoom);
          geometry.points.forEach((base, index) => {{
            assert.equal(reverseIndex(reverseIndex(index, count), count), index);
            for (let phase = 0; phase <= Math.PI*2; phase += Math.PI/12) {{
              const point = projectHelixPoint(base.x, geometry, phase);
              assert.ok(Number.isFinite(point.x));
              assert.ok(Number.isFinite(point.y));
              assert.ok(point.y > 0 && point.y < 560);
              assert.equal(point.scale, 1);
            }}
            const start = projectHelixPoint(base.x, geometry, 0);
            const end = projectHelixPoint(base.x, geometry, Math.PI*2);
            assert.ok(Math.abs(start.x-end.x) < 0.001);
            assert.ok(Math.abs(start.y-end.y) < 0.001);
            assert.ok(Math.abs(start.scale-end.scale) < 0.001);
          }});
          if (count > 1) assert.ok(geometry.points[0].x > geometry.points[count-1].x);
        }}
      }}
    }}
    const geometry = strandGeometry(25, 1440, 560);
    const start = projectHelixPoint(geometry.padding, geometry, 0);
    const halfTurn = projectHelixPoint(geometry.padding, geometry, Math.PI);
    const quarterTurn = projectHelixPoint(geometry.padding, geometry, Math.PI/2);
    assert.ok(Math.abs(start.y + halfTurn.y - 2*geometry.center) < 0.001);
    assert.ok(Math.abs(quarterTurn.y - geometry.center) < 0.001);
    assert.ok(Math.abs(quarterTurn.depth) > geometry.amplitude * 0.99);
    assert.equal(start.scale, quarterTurn.scale);
    // Positive wheel input travels right, toward the lower (newer) event index.
    assert.ok(wheelDistance({{deltaX:0,deltaY:100,deltaMode:0}},1440) > 0);
    assert.ok(reverseIndex(11,25) < reverseIndex(10,25));
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_strand_renders_every_display_frame_and_resumes_after_profile():
    result = subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("strand_life_check.mjs")),
            str(ASSETS / "strand-life.js"),
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
