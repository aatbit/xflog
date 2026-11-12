"""Exercise Constellation zoom and scene replacement against the real offline UI."""

import importlib.util
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest


@pytest.fixture(scope="module")
def offline_browser_app(tmp_path_factory):
    if importlib.util.find_spec("gradio") is None or importlib.util.find_spec("playwright") is None:
        pytest.skip("Browser UI and Playwright are optional")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip("Playwright Chromium is not installed")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        directory = tmp_path_factory.mktemp("scene-browser")
        env = {
            "PATH": os.defpath,
            "HOME": str(directory),
            "XFLOG_DATABASE": str(directory / "history.sqlite3"),
            "XFLOG_ORIGIN": origin,
            "XFLOG_HOST": "127.0.0.1",
            "XFLOG_PORT": str(port),
        }
        process = subprocess.Popen(
            [sys.executable, "-m", "xflog"],
            cwd=directory,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 25
            while True:
                try:
                    with urlopen(origin + "/healthz", timeout=1) as response:
                        if response.status == 200:
                            break
                except (OSError, URLError):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Temporary offline app failed to start") from None
                    time.sleep(0.05)
            browser = playwright.chromium.launch(headless=True)
            yield browser, origin
            browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


CONTROLLED_UI = r"""(() => {
  const nativeRaf = window.requestAnimationFrame.bind(window);
  const nativeCancel = window.cancelAnimationFrame.bind(window);
  const nativeFetch = window.fetch.bind(window);
  let controlled = false, next = -1;
  const frames = new Map(), held = {demo: [], hud: []};
  window.holdApi = {demo: false, hud: false};
  window.requestAnimationFrame = cb => {
    if (!controlled) return nativeRaf(cb);
    const id = next--; frames.set(id, cb); return id;
  };
  window.cancelAnimationFrame = id => id < 0 ? frames.delete(id) : nativeCancel(id);
  window.enableFrames = () => { controlled = true; };
  window.paintIds = () => [...frames].filter(([, cb]) => cb.name === 'paint').map(([id]) => id);
  window.paintCount = () => window.paintIds().length;
  window.stepFrames = (now = performance.now()) => {
    const callbacks = [...frames.values()]; frames.clear();
    callbacks.forEach(cb => cb(now));
  };
  window.fetch = (url, options) => {
    const path = String(url);
    const kind = path.startsWith('/api/demo?') ? 'demo' :
      path.startsWith('/api/activity-summary?') ? 'hud' : null;
    if (!kind || !window.holdApi[kind]) return nativeFetch(url, options);
    return new Promise((resolve, reject) => {
      held[kind].push({resolve, reject});
      options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once:true});
    });
  };
  window.heldCount = kind => held[kind].length;
  window.failHeld = kind => {
    const pending = held[kind].shift();
    if (!pending) throw Error('No held request');
    pending.resolve(new Response(JSON.stringify({detail:'Synthetic failure'}),
      {status:503, headers:{'content-type':'application/json'}}));
  };
})();"""


@pytest.fixture
def offline_page(offline_browser_app):
    browser, origin = offline_browser_app
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors, external = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(CONTROLLED_UI)

    def route(request):
        url = request.request.url
        if url.startswith(origin + "/") or url.startswith("data:"):
            request.continue_()
        else:
            external.append(url)
            request.abort()

    page.route("**/*", route)
    page.goto(origin + "/?demo=1", wait_until="networkidle")
    page.wait_for_selector(".constellation-star")
    page.wait_for_function(
        "document.querySelector('#history').getAttribute('aria-busy') === 'false'", polling=50
    )
    page.evaluate("""() => {
      window.enableFrames();
      const zoom = document.querySelector('#scene-zoom');
      zoom.value = '1'; zoom.dispatchEvent(new Event('input', {bubbles:true}));
    }""")
    page.wait_for_function("window.paintCount() > 0", polling=50)
    yield page
    page.close()
    assert not errors, errors
    assert not external, external


def test_loading_error_retry_and_layout_clear_the_parent_owned_scene(offline_page):
    page = offline_page
    result = page.evaluate("""() => {
      window.oldSky = document.querySelector('.constellation-sky');
      window.holdApi.demo = true;
      document.querySelector('[data-filter="lost"]').click();
      window.oldSky.style.transform = 'translateX(123456px)';
      const before = window.paintCount(); window.stepFrames();
      return {loading: !!document.querySelector('#history .loading-state'),
        detached: !window.oldSky.isConnected, before, after: window.paintCount(),
        transform: window.oldSky.style.transform,
        animating: document.querySelector('#xf').dataset.animating};
    }""")
    assert result == {
        "loading": True,
        "detached": True,
        "before": 0,
        "after": 0,
        "transform": "translateX(123456px)",
        "animating": "false",
    }
    page.wait_for_function("window.heldCount('demo') === 1", polling=50)
    page.evaluate("window.holdApi.demo = false; window.failHeld('demo')")
    page.wait_for_selector("#history [data-retry]")
    assert page.evaluate("window.paintCount()") == 0
    page.locator("#history [data-retry]").click()
    page.wait_for_selector(".constellation-star")
    page.wait_for_function(
        "document.querySelector('#history').getAttribute('aria-busy') === 'false'", polling=50
    )
    recovery = page.evaluate("""() => {
      const fresh = document.querySelector('.constellation-sky') !== window.oldSky;
      window.stepFrames();
      const stars = [...document.querySelectorAll('.constellation-star')];
      if (stars.length > 1) stars[1].click();
      window.stepFrames();
      return {fresh, pending:window.paintCount(), selected:stars.some(x => x.getAttribute('aria-pressed') === 'true')};
    }""")
    assert recovery["fresh"] and recovery["pending"] > 0 and recovery["selected"]
    page.evaluate("document.querySelector('[data-layout=vertical]').click()")
    assert page.evaluate("window.paintCount()") == 0
    assert page.locator(".constellation-sky").count() == 0
    page.evaluate("document.querySelector('[data-layout=horizontal]').click()")
    page.wait_for_selector(".constellation-star")
    assert page.evaluate("window.paintCount()") > 0
    unmount = page.evaluate("""() => {
      const sky = document.querySelector('.constellation-sky');
      document.querySelector('#xf').remove();
      sky.style.transform = 'translateX(777777px)';
      window.stepFrames();
      return {transform:sky.style.transform, pending:window.paintCount()};
    }""")
    assert unmount == {"transform": "translateX(777777px)", "pending": 0}


def test_error_fallback_clears_scene_when_initial_load_kept_existing_history(offline_page):
    page = offline_page
    page.evaluate("window.holdApi.demo = true; document.querySelector('#lens-trigger').click()")
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    page.wait_for_function("window.heldCount('demo') === 1 && window.paintCount() > 0", polling=50)
    page.evaluate("""() => {
      window.oldSky = document.querySelector('.constellation-sky');
      window.holdApi.hud = true;
      document.querySelector('[data-subject="subscriptions"]').click();
    }""")
    page.wait_for_function("window.heldCount('hud') === 1", polling=50)
    page.evaluate("window.failHeld('demo')")
    page.wait_for_selector("#history [data-retry]")
    result = page.evaluate("""() => {
      window.oldSky.style.transform = 'translateX(456789px)';
      const before = window.paintCount(); window.stepFrames();
      return {detached:!window.oldSky.isConnected, before, after:window.paintCount(),
        transform:window.oldSky.style.transform, animating:document.querySelector('#xf').dataset.animating};
    }""")
    assert result == {
        "detached": True,
        "before": 0,
        "after": 0,
        "transform": "translateX(456789px)",
        "animating": "false",
    }
    page.evaluate("window.holdApi.hud = false; window.holdApi.demo = false; window.failHeld('hud')")
    page.wait_for_function(
        "document.querySelector('#history').getAttribute('aria-busy') === 'false'", polling=50
    )


def test_detached_actor_click_cannot_act_on_a_reconstructed_scene(offline_page):
    offline_page.evaluate(
        "window.oldButton = document.querySelector('.constellation-star[aria-pressed=true]')"
    )
    offline_page.set_viewport_size({"width": 1100, "height": 810})
    offline_page.wait_for_function("!window.oldButton.isConnected", polling=50)
    result = offline_page.evaluate("""() => {
      const oldButton = window.oldButton;
      const id = oldButton.dataset.event;
      const current = [...document.querySelectorAll('.constellation-star')]
        .find(button => button.dataset.event === id);
      const history = document.querySelector('#history');
      const before = history.scrollLeft;
      oldButton.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      const stale = {detached: !oldButton.isConnected, sameId: current.dataset.event === id,
        selected: current.getAttribute('aria-pressed'), dialog: document.querySelector('#detail-dialog').open,
        scroll: history.scrollLeft === before};
      current.dispatchEvent(new MouseEvent('click', {bubbles:true}));
      return {stale, liveDialog:document.querySelector('#detail-dialog').open};
    }""")
    assert result == {
        "stale": {
            "detached": True,
            "sameId": True,
            "selected": "true",
            "dialog": False,
            "scroll": True,
        },
        "liveDialog": True,
    }


def test_ambient_frames_reuse_label_layout_and_navigation(offline_page):
    page = offline_page

    def preview_demo(route):
        response = route.fetch()
        payload = response.json()
        for index, event in enumerate(payload["events"]):
            event.update(
                kind="interaction.replies",
                post_id=str(10000 + index),
                post_text=f"Synthetic preview {index}" + " long text " * (16 if index else 0),
            )
        route.fulfill(response=response, json=payload)

    page.route("**/api/demo?*", preview_demo)
    page.evaluate("document.querySelector('[data-filter=lost]').click()")
    page.wait_for_function(
        """() => document.querySelector('.is-selected .star-post')
        && document.querySelector('#history').getAttribute('aria-busy') === 'false'""",
        polling=50,
    )
    result = page.evaluate("""() => {
      const history = document.querySelector('#history');
      const scrubber = document.querySelector('#memory-scrubber');
      const nav = ['#zoom-value', '#scene-zoom', '#zoom-in', '#zoom-out', '#memory-next',
        '#memory-previous', '#scene-people-count', '#constellation-key'];
      const label = () => history.querySelector('.is-selected .star-label');
      const preview = () => label().querySelector('.star-post');
      const spark = history.querySelector('.sequence-spark');
      const observer = new MutationObserver(() => {});
      for (const selector of nav)
        observer.observe(document.querySelector(selector), {attributes: true, childList: true, subtree: true});
      observer.observe(scrubber, {attributes: true});
      const labels = new MutationObserver(() => {});
      for (const node of history.querySelectorAll('.star-label'))
        labels.observe(node, {attributes: true, childList: true, subtree: true});
      const reads = {boxes: 0, previews: 0};
      const box = Element.prototype.getBoundingClientRect;
      const height = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
      Element.prototype.getBoundingClientRect = function() {
        if (this.matches('.star-label')) reads.boxes++;
        return box.call(this);
      };
      Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {...height, get() {
        if (this.matches('.star-post')) reads.previews++;
        return height.get.call(this);
      }});
      let now = 1000;
      const advance = () => stepFrames(now += 16);
      const count = () => ({...reads, navigation: observer.takeRecords().length,
        labels: labels.takeRecords().length});
      try {
        advance();
        count();
        reads.boxes = reads.previews = 0;
        const initialSpark = spark.getAttribute('cx');
        for (let index = 0; index < 6; index++) advance();
        const idle = {...count(), moving: initialSpark !== spark.getAttribute('cx')};

        const previousLeft = history.scrollLeft;
        history.scrollLeft += previousLeft > 40 ? -40 : 40;
        history.dispatchEvent(new Event('scroll'));
        advance();
        const expected = Math.round((1 - history.scrollLeft / (history.scrollWidth - history.clientWidth)) * 1000);
        const scroll = history.scrollLeft !== previousLeft && labels.takeRecords().length > 0
          && Number(scrubber.value) === expected;

        const originalPreview = preview().textContent, originalHeight = preview().offsetHeight;
        reads.boxes = reads.previews = 0;
        const stars = [...history.querySelectorAll('.constellation-star')];
        const next = stars[0].getAttribute('aria-pressed') === 'true' ? stars[1] : stars[0];
        next.click();
        for (let index = 0; index < 64; index++) advance();
        const selection = preview().textContent !== originalPreview
          && label().getAttribute('aria-hidden') === 'false'
          && preview().tabIndex === 0 && preview().style.top !== ''
          && reads.boxes > 0 && reads.previews > 0 && preview().offsetHeight !== originalHeight;
        return {idle, scroll, selection};
      } finally {
        observer.disconnect();
        labels.disconnect();
        Element.prototype.getBoundingClientRect = box;
        Object.defineProperty(HTMLElement.prototype, 'offsetHeight', height);
      }
    }""")
    assert result == {
        "idle": {"boxes": 0, "previews": 0, "navigation": 0, "labels": 0, "moving": True},
        "scroll": True,
        "selection": True,
    }


def test_reduced_motion_remeasures_labels_after_fonts_and_resize(offline_page):
    page = offline_page
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_function("matchMedia('(prefers-reduced-motion: reduce)').matches", polling=50)
    page.evaluate("""() => {
      const nativeBox = Element.prototype.getBoundingClientRect;
      window.sceneLabelReads = 0;
      Element.prototype.getBoundingClientRect = function() {
        if (this.matches('.star-label')) window.sceneLabelReads++;
        return nativeBox.call(this);
      };
      stepFrames();
      window.sceneLabelReads = 0;
      window.selectedLabel = document.querySelector('.is-selected .star-label');
      window.initialLabelHeight = window.selectedLabel.offsetHeight;
      const style = document.createElement('style');
      style.textContent = `@font-face {
        font-family: "XFlog test face";
        src: url(/static/xf/plex-sans-variable.ttf);
        size-adjust: 220%;
      }`;
      document.head.append(style);
      window.selectedLabel.style.fontFamily = '"XFlog test face", sans-serif';
      window.loadedTestFace = false;
      document.fonts.addEventListener('loadingdone', () => { window.loadedTestFace = true; }, {once:true});
      void document.fonts.load('20px "XFlog test face"');
    }""")
    page.wait_for_function("window.loadedTestFace && paintCount() > 0", polling=50)
    assert page.evaluate("""() => {
      stepFrames();
      return window.selectedLabel.isConnected && window.sceneLabelReads > 0 && paintCount() === 0
        && window.selectedLabel.offsetHeight !== window.initialLabelHeight;
    }""")

    page.set_viewport_size({"width": 1000, "height": 800})
    page.wait_for_function("!window.selectedLabel.isConnected && paintCount() > 0", polling=50)
    assert page.evaluate("""() => {
      window.sceneLabelReads = 0;
      stepFrames();
      return window.sceneLabelReads > 0 && paintCount() === 0
        && document.querySelector('.is-selected .star-label').getAttribute('aria-hidden') === 'false';
    }""")


@pytest.mark.parametrize("motion", ["no-preference", "reduce"])
def test_zoom_reuses_grouped_scene_and_rebinds_animation(offline_page, motion):
    page = offline_page
    page.emulate_media(reduced_motion=motion)

    def dense_demo(route):
        response = route.fetch()
        payload = response.json()
        events = payload["events"]
        templates = (
            events[0],
            next(event for event in events if event["kind"] != events[0]["kind"]),
        )
        anchor = datetime.fromisoformat(events[0]["received_at"])
        payload["events"] = [
            {
                **templates[index % 2],
                "sequence": 240 - index,
                "event_id": f"zoom-{index}",
                "received_at": (anchor - timedelta(seconds=index)).isoformat(),
            }
            for index in range(240)
        ]
        payload["next"] = None
        route.fulfill(response=response, json=payload)

    page.route("**/api/demo?*", dense_demo)
    page.locator("#lens-trigger").click()
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    page.wait_for_function(
        """() => document.querySelectorAll('.constellation-star').length === 240
        && document.querySelector('#history').getAttribute('aria-busy') === 'false'""",
        polling=50,
    )
    slider = page.locator("#scene-zoom")
    page.evaluate("""() => {
      const history = document.querySelector('#history');
      const selector = '.constellation-canvas, .constellation-sky, .constellation-person, '
        + '.constellation-star, .star-label, .star-identity';
      const nodes = [...history.querySelectorAll(selector)];
      const selected = history.querySelector('.constellation-star[aria-pressed=true]');
      const path = history.querySelector('.constellation-links path');
      let listenerCount = 0, historyWrites = 0;
      const nativeAdd = EventTarget.prototype.addEventListener;
      EventTarget.prototype.addEventListener = function(type, ...args) {
        if (this instanceof Element && this.matches(selector)) listenerCount++;
        return nativeAdd.call(this, type, ...args);
      };
      const observer = new MutationObserver(records => { historyWrites += records.length; });
      observer.observe(history, {childList:true});
      window.zoomProbe = {
        history, selected, path, initialPath: path.getAttribute('d'),
        unchanged: () => {
          const current = [...history.querySelectorAll(selector)];
          return history === document.querySelector('#history') && current.length === nodes.length
            && nodes.every((node, index) => node === current[index]);
        },
        work: () => ({historyWrites:historyWrites + observer.takeRecords().length,
          listeners:listenerCount}),
        finish: () => { observer.disconnect(); EventTarget.prototype.addEventListener = nativeAdd; },
      };
      window.setZoomInput = value => {
        const input = document.querySelector('#scene-zoom');
        input.value = String(value);
        input.dispatchEvent(new Event('input', {bubbles:true}));
      };
      selected.focus({preventScroll:true});
      zoomProbe.paintBefore = paintIds()[0];
      setZoomInput(1.25);
      zoomProbe.paintAfter = paintIds()[0];
    }""")
    assert page.evaluate("zoomProbe.unchanged() && document.activeElement === zoomProbe.selected")
    if motion == "no-preference":
        assert page.evaluate(
            "zoomProbe.paintBefore < 0 && zoomProbe.paintBefore === zoomProbe.paintAfter"
        )

    slider.press("ArrowRight")
    assert float(slider.input_value()) == 1.3
    bounds = slider.bounding_box()
    assert bounds is not None
    x, y = bounds["x"], bounds["y"] + bounds["height"] / 2
    page.mouse.move(x + bounds["width"] * 0.65, y)
    page.mouse.down()
    page.mouse.move(x + bounds["width"] * 0.90, y, steps=12)
    page.mouse.up()
    assert float(slider.input_value()) > 1.5
    page.locator("#zoom-out").click()
    assert page.evaluate(
        "zoomProbe.unchanged() && zoomProbe.path.getAttribute('d') !== zoomProbe.initialPath"
    )

    before_wheel = float(slider.input_value())
    history_bounds = page.locator("#history").bounding_box()
    assert history_bounds is not None
    x = history_bounds["x"] + history_bounds["width"] / 2
    y = history_bounds["y"] + history_bounds["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down(button="middle")
    # Playwright's wheel helper omits the pressed-button mask.
    session = page.context.new_cdp_session(page)
    session.send(
        "Input.dispatchMouseEvent",
        {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": 100, "buttons": 4},
    )
    session.detach()
    page.mouse.up(button="middle")
    page.wait_for_function(
        "previous => Number(document.querySelector('#scene-zoom').value) < previous",
        arg=before_wheel,
        polling=50,
    )
    assert before_wheel - float(slider.input_value()) == pytest.approx(0.225, abs=0.026)
    page.evaluate("setZoomInput(1); stepFrames(); setZoomInput(0.25); stepFrames()")
    assert page.locator(".constellation-group:visible").count() == 2
    assert page.evaluate("""() => zoomProbe.unchanged() && zoomProbe.selected.tabIndex === -1
      && zoomProbe.selected.getAttribute('aria-hidden') === 'true'
      && zoomProbe.history.scrollLeft >= 0
      && zoomProbe.history.scrollLeft <= zoomProbe.history.scrollWidth - zoomProbe.history.clientWidth""")
    assert page.locator(".constellation-links path:visible").count() == 0
    assert page.evaluate("""() => {
      const link = zoomProbe.path.parentNode;
      const observer = new MutationObserver(() => {});
      observer.observe(link, {attributes:true, subtree:true});
      stepFrames();
      const writes = observer.takeRecords().length;
      observer.disconnect();
      return writes === 0;
    }""")

    assert page.evaluate("""() => {
      const {history} = zoomProbe;
      const labels = [...history.querySelectorAll('.star-label')];
      const hidden = () => labels.every(label => getComputedStyle(label).visibility === 'hidden'
        && label.getAttribute('aria-hidden') === 'true'
        && [...label.querySelectorAll('button, a')].every(control => control.tabIndex === -1));
      const observer = new MutationObserver(() => {});
      for (const label of labels) observer.observe(label, {attributes: true, subtree: true});
      const width = () => Math.max(history.clientWidth, history.querySelector('.constellation-canvas').offsetWidth);
      try {
        for (const zoom of [0, 0.1, 0.25]) {
          setZoomInput(zoom);
          stepFrames();
          if (!hidden() || history.scrollWidth !== width()) return false;
        }
        return zoomProbe.unchanged() && observer.takeRecords().length === 0;
      } finally {
        observer.disconnect();
      }
    }""")

    page.evaluate("setZoomInput(0.30); stepFrames()")
    assert page.locator(".constellation-group:visible").count() == 0
    assert page.evaluate("""() => {
      const {history, selected, path} = zoomProbe;
      const expected = Math.max(0, Math.min(parseFloat(selected.style.left) - history.clientWidth / 2,
        history.scrollWidth - history.clientWidth));
      const spark = path.parentNode.querySelector('.sequence-spark');
      const trail = path.parentNode.querySelector('.sequence-trail');
      const [ax, ay, bx, by] = path.getAttribute('d').slice(1).split(/[,L]/).map(Number);
      const cx = Number(spark.getAttribute('cx')), cy = Number(spark.getAttribute('cy'));
      const progress = (cx - ax) / (bx - ax);
      const label = selected.parentElement.querySelector('.star-label');
      return zoomProbe.unchanged() && path.isConnected && selected.tabIndex === 0
        && getComputedStyle(label).visibility === 'visible'
        && label.getAttribute('aria-hidden') === 'false' && label.querySelector('button').tabIndex === 0
        && selected.getAttribute('aria-hidden') === 'false'
        && selected.getAttribute('aria-pressed') === 'true'
        && Math.abs(history.scrollLeft - expected) < 2
        && spark.hasAttribute('cx') && spark.getAttribute('cx') === trail.getAttribute('x2')
        && spark.getAttribute('cy') === trail.getAttribute('y2')
        && progress >= 0 && progress <= 1 && Math.abs(cy - (ay + (by - ay) * progress)) < 0.1;
    }""")
    assert page.evaluate("zoomProbe.work()") == {"historyWrites": 0, "listeners": 0}
    assert page.evaluate("() => { stepFrames(); return paintCount(); }") == (
        0 if motion == "reduce" else 1
    )

    page.evaluate("setZoomInput(0.2)")
    page.locator(".constellation-group:visible").first.click()
    assert float(slider.input_value()) == 1
    assert page.evaluate("zoomProbe.unchanged()")
    assert page.evaluate("""() => {
      const {history} = zoomProbe;
      const other = history.querySelector('.constellation-star[aria-pressed=false]');
      other.click();
      setZoomInput(1.5);
      const expected = Math.max(0, Math.min(parseFloat(other.style.left) - history.clientWidth / 2,
        history.scrollWidth - history.clientWidth));
      return zoomProbe.unchanged() && other.getAttribute('aria-pressed') === 'true'
        && Math.abs(history.scrollLeft - expected) < 2;
    }""")
    page.evaluate("zoomProbe.finish()")
    page.set_viewport_size({"width": 1050, "height": 800})
    page.wait_for_function("!zoomProbe.unchanged()", polling=50)
