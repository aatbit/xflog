"""Exercise timeline interactions and scene replacement against the real offline UI."""

import importlib.util
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urljoin, urlsplit
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
            yield browser, origin, directory / "history.sqlite3"
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
  window.journalFrameCount = () => [...frames.values()].filter(cb => cb.name === 'paintJournal').length;
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
    browser, origin, _ = offline_browser_app
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


def test_scope_change_discards_stale_failure_before_current_error(offline_page):
    page = offline_page
    page.evaluate("""() => {
      window.oldSky = document.querySelector('.constellation-sky');
      window.holdApi.demo = true;
      document.querySelector('#lens-trigger').click();
    }""")
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    page.wait_for_function("window.heldCount('demo') === 1", polling=50)
    page.evaluate("""() => {
      window.holdApi.hud = true;
      document.querySelector('[data-subject="subscriptions"]').click();
    }""")
    page.wait_for_function("window.heldCount('hud') === 1", polling=50)
    page.evaluate("window.failHeld('demo')")
    result = page.evaluate("""async () => {
      await new Promise(resolve => setTimeout(resolve, 0));
      window.oldSky.style.transform = 'translateX(456789px)';
      const before = window.paintCount(); window.stepFrames();
      return {detached:!window.oldSky.isConnected, before, after:window.paintCount(),
        transform:window.oldSky.style.transform, animating:document.querySelector('#xf').dataset.animating,
        loading: Boolean(document.querySelector('#history .loading-state'))};
    }""")
    assert result == {
        "detached": True,
        "before": 0,
        "after": 0,
        "transform": "translateX(456789px)",
        "animating": "false",
        "loading": True,
    }
    page.evaluate("window.holdApi.hud = false; window.failHeld('hud')")
    page.wait_for_function("window.heldCount('demo') === 1", polling=50)
    page.evaluate("window.failHeld('demo')")
    page.wait_for_selector("#history [data-retry]")
    assert page.evaluate("window.paintCount()") == 0


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
        const labelBox = label().getBoundingClientRect();
        const viewport = history.getBoundingClientRect();
        const scroll = history.scrollLeft !== previousLeft && Number(scrubber.value) === expected
          && label().getAttribute('aria-hidden') === 'false'
          && labelBox.left >= viewport.left && labelBox.right <= viewport.right;

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


@pytest.fixture
def viewport_page(offline_page):
    page = offline_page

    def long_demo(route):
        response = route.fetch()
        payload = response.json()
        template = payload["events"][0]
        anchor = datetime.fromisoformat(template["received_at"])
        payload["events"] = [
            {
                **template,
                "event_id": f"viewport-{index}",
                "name": f"Dummy actor {index}",
                "sequence": 120 - index,
                "received_at": (anchor - timedelta(seconds=index)).isoformat(),
                "kind": "interaction.replies",
                "post_id": str(10000 + index),
                "post_text": f"Synthetic reply {index}",
            }
            for index in range(120)
        ]
        payload["next"] = None
        route.fulfill(response=response, json=payload)

    page.route("**/api/demo?*", long_demo)
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("document.querySelector('[data-filter=lost]').click()")
    page.wait_for_function(
        """() => document.querySelectorAll('.constellation-star').length === 120
        && document.querySelector('#history').getAttribute('aria-busy') === 'false'""",
        polling=50,
    )
    page.evaluate("""() => {
      window.viewportTime = 1000;
      window.viewportStep = () => stepFrames(viewportTime += 16);
      const zoom = document.querySelector('#scene-zoom');
      zoom.value = '2';
      zoom.dispatchEvent(new Event('input', {bubbles: true}));
      viewportStep();
    }""")
    return page


def test_viewport_limits_label_and_spark_work_across_scroll_jumps(viewport_page):
    page = viewport_page
    # At 2× zoom a segment can cross this entire viewport and its overscan.
    page.set_viewport_size({"width": 230, "height": 844})
    page.wait_for_function(
        """() => {
          const history = document.querySelector('#history');
          return history.clientWidth < 234
            && history.querySelector('.constellation-sky').viewBox.baseVal.width === history.clientWidth;
        }""",
        polling=50,
    )
    result = page.evaluate("""async () => {
      const {seed} = await import('/static/xf/constellation-layout.js');
      const history = document.querySelector('#history');
      const canvas = history.querySelector('.constellation-canvas');
      const actors = [...history.querySelectorAll('[data-actor]')];
      const labels = [...history.querySelectorAll('.star-label')];
      const linkLayer = history.querySelector('.constellation-links');
      const links = [...linkLayer.querySelectorAll('[data-link-group]')].map((group, index) => {
        const [x1, y1, x2, y2] = group.querySelector('path').getAttribute('d').slice(1).split(/[,L]/).map(Number);
        return {index, x1, y1, x2, y2, spark: group.querySelector('.sequence-spark'),
          trail: group.querySelector('.sequence-trail')};
      });
      const jump = left => {
        history.scrollLeft = left;
        history.dispatchEvent(new Event('scroll'));
        viewportStep();
      };
      const cross = links[Math.floor(links.length / 2)];
      const center = (cross.x1 + cross.x2) / 2;
      const old = links[0];
      jump((old.x1 + old.x2 - history.clientWidth) / 2);
      const phase = link => (Number(link.spark.getAttribute('cx')) - link.x1) / (link.x2 - link.x1);
      const oldLeft = history.scrollLeft;
      const oldPhase = phase(old);
      const oldLabel = history.querySelector('.is-selected .star-label');
      const oldSparkPosition = old.spark.getAttribute('cx');
      const labelObserver = new MutationObserver(() => {});
      const sparkObserver = new MutationObserver(() => {});
      const childObserver = new MutationObserver(() => {});
      for (const label of labels)
        labelObserver.observe(label, {attributes: true, attributeFilter: ['style']});
      sparkObserver.observe(linkLayer, {subtree: true, attributes: true, attributeFilter: ['cx']});
      childObserver.observe(canvas, {subtree: true, childList: true});
      const nativeAdd = EventTarget.prototype.addEventListener;
      let listenerWrites = 0;
      EventTarget.prototype.addEventListener = function(type, ...args) {
        if (this instanceof Node && canvas.contains(this)) listenerWrites++;
        return nativeAdd.call(this, type, ...args);
      };
      try {
        jump(center - history.clientWidth / 2);
        const left = history.scrollLeft, right = left + history.clientWidth;
        const margin = 128;
        const expectedSparks = links.filter(link => Math.min(link.x1, link.x2) <= right + margin
          && Math.max(link.x1, link.x2) >= left - margin).map(link => link.spark);
        const sparkWrites = sparkObserver.takeRecords().map(record => record.target);
        const labelWrites = new Set(labelObserver.takeRecords().map(record => record.target));
        const selected = actors.find(actor => actor.getAttribute('aria-pressed') === 'true');
        const nearest = actors.reduce((best, actor) =>
          Math.abs(parseFloat(actor.style.left) - (left + history.clientWidth / 2))
          < Math.abs(parseFloat(best.style.left) - (left + history.clientWidth / 2)) ? actor : best);
        const selectedLabel = selected.parentElement.querySelector('.star-label');
        const eligibleWrites = actors.filter(actor => {
          const x = parseFloat(actor.style.left);
          return (x >= left - margin && x <= right + margin)
            || (x >= oldLeft - margin && x <= oldLeft + history.clientWidth + margin);
        }).map(actor => actor.parentElement.querySelector('.star-label'));
        const labelBudget = new Set([...eligibleWrites, oldLabel, selectedLabel]);
        const expectedPhase = ((oldPhase - seed(old.index) + seed(cross.index) + 0.0016) % 1 + 1) % 1;
        const crossWrites = sparkWrites.includes(cross.spark);
        const initialPhase = phase(cross);
        const worldY = cross.y1 + (cross.y2 - cross.y1) * initialPhase;
        const trailMatches = cross.spark.getAttribute('cx') === cross.trail.getAttribute('x2')
          && cross.spark.getAttribute('cy') === cross.trail.getAttribute('y2')
          && Math.abs(worldY - Number(cross.spark.getAttribute('cy'))) < 0.05;
        const newActors = canvas.querySelectorAll('[data-actor]');
        const newLabels = canvas.querySelectorAll('.star-label');
        viewportStep();
        const nextSparkWrites = sparkObserver.takeRecords().map(record => record.target);
        const withinRange = (writes) => writes.length === expectedSparks.length
          && expectedSparks.every(spark => writes.includes(spark));
        return {
          cross: Math.min(cross.x1, cross.x2) < left - margin && Math.max(cross.x1, cross.x2) > right + margin && crossWrites,
          phase: Math.abs(initialPhase - expectedPhase) < 0.0001
            && Math.abs(phase(cross) - ((expectedPhase + 0.0016) % 1)) < 0.0001,
          alignment: trailMatches,
          sparkRange: withinRange(sparkWrites) && withinRange(nextSparkWrites),
          offscreenUnchanged: old.spark.getAttribute('cx') === oldSparkPosition,
          labels: labelWrites.has(selectedLabel) && [...labelWrites].every(label => labelBudget.has(label)),
          leavingHidden: oldLabel.getAttribute('aria-hidden') === 'true'
            && oldLabel.querySelector('button').tabIndex === -1,
          selected: selected === nearest && selectedLabel.getAttribute('aria-hidden') === 'false',
          nodes: childObserver.takeRecords().length === 0 && listenerWrites === 0
            && actors.every((actor, index) => actor === newActors[index])
            && labels.every((label, index) => label === newLabels[index])
            && canvas === history.querySelector('.constellation-canvas')
            && linkLayer === canvas.querySelector('.constellation-links'),
        };
      } finally {
        EventTarget.prototype.addEventListener = nativeAdd;
        labelObserver.disconnect();
        sparkObserver.disconnect();
        childObserver.disconnect();
      }
    }""")
    assert all(result.values()), result

    page.emulate_media(reduced_motion="reduce")
    page.wait_for_function("matchMedia('(prefers-reduced-motion: reduce)').matches")
    result = page.evaluate("""() => {
      const history = document.querySelector('#history');
      viewportStep();
      const group = history.querySelector('[data-link-group]');
      const path = group.querySelector('path');
      const spark = group.querySelector('.sequence-spark');
      const trail = group.querySelector('.sequence-trail');
      const stale = spark.getAttribute('cx');
      const [x1, y1, x2, y2] = path.getAttribute('d').slice(1).split(/[,L]/).map(Number);
      history.scrollLeft = (x1 + x2 - history.clientWidth) / 2;
      history.dispatchEvent(new Event('scroll'));
      viewportStep();
      const x = Number(spark.getAttribute('cx'));
      const y = Number(spark.getAttribute('cy'));
      const progress = (x - x1) / (x2 - x1);
      return {
        reentered: getComputedStyle(spark).visibility === 'visible'
          && spark.getAttribute('cx') !== stale && progress >= 0 && progress <= 1
          && Math.abs(y - (y1 + (y2 - y1) * progress)) < 0.05
          && spark.getAttribute('cx') === trail.getAttribute('x2'),
        paused: paintCount() === 0,
      };
    }""")
    assert result == {"reentered": True, "paused": True}


def test_viewport_keeps_offscreen_selection_and_focused_preview_usable(viewport_page):
    page = viewport_page
    result = page.evaluate("""() => {
      const history = document.querySelector('#history');
      const actors = [...history.querySelectorAll('[data-actor]')];
      const label = actor => actor.parentElement.querySelector('.star-label');
      const first = actors[0], last = actors.at(-1);
      const selected = () => history.querySelector('[aria-pressed=true][data-actor]');
      const isUsable = (item, control) => getComputedStyle(control).visibility === 'visible'
        && getComputedStyle(control).display !== 'none'
        && item.getAttribute('aria-hidden') === 'false' && control.tabIndex === 0;
      const outside = actor => {
        const x = parseFloat(actor.style.left);
        return x < history.scrollLeft - 128 || x > history.scrollLeft + history.clientWidth + 128;
      };

      last.click();
      viewportStep();
      const pinnedSelection = selected() === last && outside(last)
        && isUsable(label(last), label(last).querySelector('button'));
      for (let i = 0; i < 160; i++) viewportStep();
      const preview = label(last).querySelector('.star-post');
      preview.focus({preventScroll: true});
      const focusedInitially = document.activeElement === preview;
      history.scrollLeft = history.scrollWidth - history.clientWidth;
      history.dispatchEvent(new Event('scroll'));
      viewportStep();
      const pinnedFocus = focusedInitially && selected() === first && outside(last)
        && document.activeElement === preview && isUsable(label(last), preview);

      preview.blur();
      viewportStep();
      const removedFromTabOrder = label(last).getAttribute('aria-hidden') === 'true'
        && preview.tabIndex === -1;
      const actorAccessible = last.tabIndex === 0 && last.getAttribute('aria-hidden') === 'false';
      return {pinnedSelection, pinnedFocus, removedFromTabOrder, actorAccessible};
    }""")
    assert all(result.values()), result

    # A real key action enables :focus-visible before focusing the far actor without native scrolling.
    page.keyboard.press("Tab")
    assert page.evaluate("""() => {
      const actor = [...document.querySelectorAll('#history [data-actor]')].at(-1);
      actor.focus({preventScroll: true});
      viewportStep();
      return document.activeElement === actor && actor.matches(':focus-visible')
        && actor.getAttribute('aria-pressed') === 'true';
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
      const center = history.scrollLeft + history.clientWidth / 2;
      const visiblePath = [...history.querySelectorAll('.constellation-links path')].find(path => {
        const [x1, , x2] = path.getAttribute('d').slice(1).split(/[,L]/).map(Number);
        return Math.min(x1, x2) <= center && Math.max(x1, x2) >= center;
      });
      const spark = visiblePath.parentNode.querySelector('.sequence-spark');
      const trail = visiblePath.parentNode.querySelector('.sequence-trail');
      const [ax, ay, bx, by] = visiblePath.getAttribute('d').slice(1).split(/[,L]/).map(Number);
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
    page.evaluate("setZoomInput(1); stepFrames()")
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


def journal_events(size):
    anchor = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    events = []
    for index in range(size):
        kind = "follow.follow" if index < size * 3 // 4 else "follow.unfollow"
        city = f"city-{index // 3:03}"
        city_name = f"City {index // 3:03}"
        if index < 3:
            city_name += ' <img src=x onerror="bad()">'
        location = (
            {
                "audience_groups": {"activity": kind, "profile-location": city},
                "audience_group_buckets": {"profile-location": {"key": city, "label": city_name}},
            }
            if index < size - 3
            else {"audience_groups": {"activity": kind}}
        )
        events.append(
            {
                "event_id": f"journal-{index}",
                "actor_id": str(index % 31 + 1000),
                "account_id": "demo",
                "sequence": size - index,
                "kind": kind,
                "name": (
                    'Name <img src=x onerror="bad()">'
                    if index == 0
                    else f"Dummy actor {index}" + " long name" * (30 if index % 11 == 0 else 0)
                ),
                "handle": f"actor_{index % 31}",
                "received_at": (anchor - timedelta(seconds=index)).isoformat(),
                "provider_at": (anchor - timedelta(days=index // 12)).isoformat(),
                **location,
            }
        )
    return events


@pytest.fixture
def paged_history(offline_page, request):
    page = offline_page
    events = journal_events(114)
    if getattr(request, "param", False):
        events[0]["kind"], events[-1]["kind"] = events[-1]["kind"], events[0]["kind"]
        events[0]["audience_groups"]["activity"] = events[0]["kind"]
        events[-1]["audience_groups"]["activity"] = events[-1]["kind"]
    page.evaluate(
        """events => {
          const fetchOriginal = window.fetch;
          const requests = [];
          const history = document.querySelector('#history');
          const byKind = kind => events.filter(event => event.kind === kind);
          const actors = events => new Set(events.map(event => event.actor_id)).size;
          window.fetch = (path, options) => {
            const url = new URL(path, location.href);
            if (url.pathname !== '/api/demo') return fetchOriginal(path, options);
            return new Promise(resolve => requests.push({url, signal:options?.signal, resolve}));
          };
          window.paged = {
            requests: () => requests.map(({url, signal}) => ({...Object.fromEntries(url.searchParams),
              aborted: signal?.aborted ?? false})),
            send(index, mode) {
              const {url, resolve} = requests[index];
              const before = url.searchParams.get('before');
              const scope = Object.fromEntries(url.searchParams);
              const offset = before === '0' ? 0 : Number(before.split('-').at(-1));
              const limit = Math.min(50, Number(url.searchParams.get('limit') || 25));
              const scopedRows = scope.activity_kind ? byKind(scope.activity_kind)
                : scope.kind === 'lost' ? byKind('follow.unfollow') : events;
              const groups = ['follow.follow', 'follow.unfollow'].map((key, index) => ({
                key, label: index ? 'Unfollowed' : 'Followed you', tone: index ? 'negative' : 'positive',
                event_count: byKind(key).length, distinct_actors: actors(byKind(key)),
              })).filter(group => !scope.activity_kind || group.key === scope.activity_kind);
              const end = Math.min(offset + limit, scopedRows.length);
              const payload = mode === 'fail' ? {detail: 'Synthetic older-page failure'} : {
                events: scopedRows.slice(offset, end),
                next: mode === 'repeat' ? before : end < scopedRows.length ? 'page-' + end : null,
                aggregate: !offset ? {total_events: scopedRows.length, distinct_actors: actors(scopedRows),
                  groups: scope.lens === 'activity' ? groups : [], kinds: {}, revision: 'fixture', scope} : null,
              };
              // Resolve even after abort to challenge the caller's generation guard.
              resolve(new Response(JSON.stringify(payload), {status: mode === 'fail' ? 503 : 200,
                headers: {'content-type': 'application/json'}}));
            },
            journalEnd() {
              history.scrollTop = history.scrollHeight;
              for (let index = 0; index < 4; index++) history.dispatchEvent(new Event('scroll'));
              stepFrames();
            },
            constellationEnd() {
              history.scrollLeft = 0;
              history.dispatchEvent(new WheelEvent('wheel', {deltaX: -120, bubbles:true, cancelable:true}));
              stepFrames();
            },
          };
        }""",
        events,
    )
    return page


def receive_history_page(page, index, mode=None):
    page.wait_for_function("index => paged.requests().length === index + 1", arg=index, polling=20)
    page.evaluate("([index, mode]) => paged.send(index, mode)", [index, mode])
    if mode in {"fail", "repeat"}:
        page.wait_for_function(
            "document.querySelector('#history-more').textContent === 'Retry older activity'",
            polling=20,
        )
        assert page.evaluate(
            """index => {
          paged.journalEnd();
          return paged.requests().length === index + 1 &&
            document.querySelector('#history').getAttribute('aria-busy') === 'false';
        }""",
            index,
        ), "A near-end scroll must leave the failed cursor available for explicit retry"
        return
    page.wait_for_function(
        "document.querySelector('#history').getAttribute('aria-busy') === 'false'", polling=20
    )


def test_constellation_scrubber_requests_older_once_on_commit(paged_history):
    page = paged_history
    page.evaluate("document.querySelector('[data-filter=all]').click()")
    receive_history_page(page, 0)
    assert (
        page.locator("#memory-scrubber").evaluate("""input => {
      input.value = '1000';
      input.dispatchEvent(new Event('input', {bubbles:true}));
      const previewRequests = paged.requests().length;
      input.dispatchEvent(new Event('change', {bubbles:true}));
      return previewRequests;
    }""")
        == 1
    )
    receive_history_page(page, 1, "fail")
    assert page.evaluate("paged.requests().length") == 2
    assert page.locator("#history-more").inner_text() == "Retry older activity"


def test_journal_pages_coalesce_retry_and_preserve_anchor_focus(paged_history):
    page = paged_history
    page.evaluate("""() => {
      document.querySelector('[data-layout=vertical]').click();
      document.querySelector('[data-filter=all]').click();
    }""")
    receive_history_page(page, 0)
    initial = page.evaluate("Number(document.querySelector('#memory-scrubber').max) + 1")
    assert 1 < initial <= 50
    assert page.evaluate("paged.requests().map(request => request.before)") == ["0"]
    assert "114" in page.locator("#scene-people-count").text_content()
    page.evaluate("""() => {
      window.journalTrackBefore = document.querySelector('.journal-window');
      window.focusedHistoryRow = document.querySelector('.event-button');
      focusedHistoryRow.focus({preventScroll:true});
      paged.journalEnd();
    }""")
    page.wait_for_function("paged.requests().length === 2", polling=20)
    assert "Loading" in page.locator("#history-page-status").text_content()
    assert page.evaluate("paged.requests().at(-1).before") == f"page-{initial}"
    receive_history_page(page, 1, "fail")
    assert page.locator("#history-more").is_visible()
    assert page.locator("#history-more").inner_text() == "Retry older activity"
    assert page.evaluate(
        "document.activeElement === focusedHistoryRow && journalTrackBefore.isConnected"
    )
    page.evaluate("document.querySelector('#history-more').click()")
    receive_history_page(page, 2, "repeat")
    assert page.evaluate("paged.requests().at(-1).before") == f"page-{initial}"
    assert page.evaluate("Number(document.querySelector('#memory-scrubber').max) + 1") == initial
    page.evaluate("document.querySelector('#history-more').click()")
    page.wait_for_function("paged.requests().length === 4", polling=20)
    page.evaluate("""() => {
      stepFrames();
      const history = document.querySelector('#history');
      const top = history.getBoundingClientRect().top;
      window.anchorBeforeAppend = [...history.querySelectorAll('.event-button')].find(node =>
        node.getBoundingClientRect().bottom > top);
      window.anchorOffsetBeforeAppend = anchorBeforeAppend.getBoundingClientRect().top - top;
      window.selectedBeforeAppend = document.querySelector('#journey-position').textContent;
    }""")
    receive_history_page(page, 3)
    assert page.evaluate("paged.requests().at(-1).before") == f"page-{initial}"
    restored = page.evaluate("""() => ({focus: document.activeElement === focusedHistoryRow,
      track: journalTrackBefore.isConnected, anchor: anchorBeforeAppend.isConnected,
      offset: anchorBeforeAppend.getBoundingClientRect().top - document.querySelector('#history').getBoundingClientRect().top - anchorOffsetBeforeAppend,
      selected: document.querySelector('#journey-position').textContent.split(' of ')[0] === selectedBeforeAppend.split(' of ')[0]})""")
    assert restored == {
        "focus": True,
        "track": True,
        "anchor": True,
        "offset": pytest.approx(0, abs=2),
        "selected": True,
    }
    assert (
        page.evaluate("Number(document.querySelector('#memory-scrubber').max) + 1") == initial * 2
    )
    page.evaluate("document.querySelector('[data-layout=horizontal]').click()")
    assert page.locator("#history .constellation-star").count() == initial * 2
    assert page.evaluate("paged.requests().length") == 4


def test_constellation_pages_preserve_selection_and_show_full_group_counts(paged_history):
    page = paged_history
    page.locator("#lens-trigger").click()
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    receive_history_page(page, 0)
    initial = page.locator("#history .constellation-star").count()
    assert 1 < initial <= 50
    assert "114" in page.locator("#scene-people-count").text_content()
    page.evaluate("""() => {
      const zoom = document.querySelector('#scene-zoom');
      zoom.value = '0'; zoom.dispatchEvent(new Event('input', {bubbles:true})); stepFrames();
    }""")
    assert page.locator("#history .constellation-group .cluster-count").all_text_contents() == [
        "85",
        "29",
    ]
    unloaded = page.locator('#history .constellation-group[data-group="follow.unfollow"]')
    assert "0 actions loaded" in unloaded.get_attribute("title")
    assert unloaded.evaluate("node => node.tagName") == "BUTTON"
    assert page.locator("#history .constellation-star").count() == initial
    page.evaluate("document.querySelector('[data-layout=vertical]').click()")
    assert "85 events" in page.locator('#history [data-group="follow.follow"] summary').inner_text()
    page.evaluate("""() => {
      const history = document.querySelector('#history');
      history.scrollTop = history.scrollHeight - history.clientHeight - 180;
      history.dispatchEvent(new Event('scroll'));
      stepFrames();
    }""")
    summary = page.locator('#history [data-group="follow.unfollow"] .journal-group-summary')
    assert "29 events saved · 0 loaded" in summary.text_content()
    assert summary.locator("button, a").count() == 0
    assert page.evaluate("paged.requests().length") == 1
    page.evaluate("document.querySelector('[data-layout=horizontal]').click()")
    page.evaluate("""() => {
      const zoom = document.querySelector('#scene-zoom');
      zoom.value = '1'; zoom.dispatchEvent(new Event('input', {bubbles:true})); stepFrames();
      paged.constellationEnd();
      const selected = document.querySelector('#history [aria-pressed=true][data-actor]');
      window.selectedStarBefore = {id:selected.dataset.event, x:selected.getBoundingClientRect().x};
    }""")
    receive_history_page(page, 1)
    assert page.locator("#history .constellation-star").count() == 2 * initial
    assert page.evaluate("""() => {
      const selected = document.querySelector('#history [aria-pressed=true][data-actor]');
      return selected.dataset.event === selectedStarBefore.id
        && Math.abs(selected.getBoundingClientRect().x - selectedStarBefore.x) <= 2;
    }""")
    while page.locator("#history .constellation-star").count() < 114:
        count = page.evaluate("paged.requests().length")
        assert count < 6
        page.evaluate("paged.constellationEnd()")
        receive_history_page(page, count)
    assert page.locator("#history .constellation-star").count() == 114
    page.evaluate("""() => {
      const zoom = document.querySelector('#scene-zoom');
      zoom.value = '0'; zoom.dispatchEvent(new Event('input', {bubbles:true})); stepFrames();
    }""")
    assert unloaded.evaluate("node => node.tagName") == "BUTTON"
    assert unloaded.locator(".cluster-count").inner_text() == "29"
    assert "All matching activity loaded" in page.locator("#history-page-status").text_content()
    count = page.evaluate("paged.requests().length")
    page.evaluate("paged.constellationEnd()")
    assert page.evaluate("paged.requests().length") == count


def test_activity_card_loads_its_own_page_and_can_return_to_overview(paged_history):
    page = paged_history
    page.locator("#lens-trigger").click()
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    receive_history_page(page, 0)
    page.locator("#scene-zoom").evaluate(
        "zoom => {zoom.value = '0'; zoom.dispatchEvent(new Event('input', {bubbles:true}));}"
    )
    card = page.get_by_role("button", name="Explore Unfollowed", exact=False)
    assert "0 actions loaded" in card.get_attribute("title")
    card.press("Enter")
    receive_history_page(page, 1)
    request = page.evaluate("paged.requests().at(-1)")
    assert (request["before"], request["activity_kind"], request["local_only"]) == (
        "0",
        "follow.unfollow",
        "true",
    )
    assert page.locator("#history .constellation-star").count() == 29
    assert page.locator("#history .constellation-star[aria-pressed=true]").count() == 1
    assert page.locator("#scene-lens-label").inner_text() == "Unfollowed"
    page.locator("#activity-group-back").click()
    assert page.evaluate("paged.requests().length") == 2
    assert card.is_visible()


@pytest.mark.parametrize("paged_history", [False, True], indirect=True)
def test_returning_to_overview_discards_inflight_activity_page(paged_history):
    page = paged_history
    page.locator("#lens-trigger").click()
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    receive_history_page(page, 0)
    page.locator("#scene-zoom").evaluate(
        "zoom => {zoom.value = '0'; zoom.dispatchEvent(new Event('input', {bubbles:true}));}"
    )
    card = page.get_by_role("button", name="Explore Unfollowed", exact=False)
    card.click()
    page.wait_for_function("paged.requests().length === 2")
    page.locator("#activity-group-back").click()
    assert page.evaluate("paged.requests().length") == 2
    assert page.evaluate("paged.requests()[1].aborted")
    assert page.evaluate("""async () => {
      paged.send(1);
      await new Promise(resolve => setTimeout(resolve, 0));
      return document.querySelector('#scene-lens-label').textContent === 'Activity'
        && document.querySelector('#activity-group-back').hidden;
    }""")
    assert card.is_visible()


def test_all_groups_restores_loaded_pages_selection_zoom_and_cursor(paged_history):
    page = paged_history
    page.locator("#lens-trigger").click()
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    receive_history_page(page, 0)
    page.locator("#history-more").click()
    receive_history_page(page, 1)
    page.locator("#scene-zoom").evaluate(
        "zoom => {zoom.value = '0.25'; zoom.dispatchEvent(new Event('input', {bubbles:true}));}"
    )
    selected = page.locator("#history [data-actor][aria-pressed=true]")
    identity = selected.get_attribute("data-event")
    card = page.get_by_role("button", name="Explore Unfollowed", exact=False)
    card.click()
    receive_history_page(page, 2)
    page.locator("#activity-group-back").click()
    assert page.evaluate("paged.requests().length") == 3
    assert page.locator("#history [data-actor]").count() == 100
    assert selected.get_attribute("data-event") == identity
    assert page.locator("#scene-zoom").input_value() == "0.25"
    assert card.evaluate("node => node === document.activeElement"), page.evaluate(
        "document.activeElement.outerHTML.slice(0, 250)"
    )
    page.locator("#history-more").click()
    receive_history_page(page, 3)
    request = page.evaluate("paged.requests().at(-1)")
    assert request["before"] == "page-100" and "activity_kind" not in request
    assert page.locator("#history [data-actor]").count() == 114


def test_all_groups_uses_new_range_if_range_changes_inside_group(paged_history):
    page = paged_history
    page.locator("#lens-trigger").click()
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    receive_history_page(page, 0)
    page.locator("#scene-zoom").evaluate(
        "zoom => {zoom.value = '0'; zoom.dispatchEvent(new Event('input', {bubbles:true}));}"
    )
    page.get_by_role("button", name="Explore Unfollowed", exact=False).click()
    receive_history_page(page, 1)
    page.locator("#group-range-trigger").click()
    page.get_by_role("menuitemradio", name="30d", exact=True).click()
    receive_history_page(page, 2)
    page.locator("#activity-group-back").click()
    receive_history_page(page, 3)
    request = page.evaluate("paged.requests().at(-1)")
    assert request["since"] == page.evaluate("paged.requests()[2].since")
    assert "activity_kind" not in request


@pytest.mark.parametrize("paged_history", [True], indirect=True)
def test_loaded_activity_card_opens_immediately_and_pages_only_its_group(paged_history):
    page = paged_history
    page.locator("#lens-trigger").click()
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    receive_history_page(page, 0)
    page.locator("#scene-zoom").evaluate(
        "zoom => {zoom.value = '0'; zoom.dispatchEvent(new Event('input', {bubbles:true}));}"
    )
    page.get_by_role("button", name="Explore Followed you", exact=False).press("Enter")
    stars = page.locator("#history [data-actor]")
    selected = page.locator("#history [data-actor][aria-pressed=true]")
    assert stars.count() == 49
    identity = selected.get_attribute("data-event")
    assert identity and page.locator("#scene-lens-label").inner_text() == "Followed you"
    assert page.locator("#scene-zoom").input_value() == "1"
    page.wait_for_function("paged.requests().length === 2")
    assert page.evaluate("paged.requests()[1].activity_kind") == "follow.follow"
    receive_history_page(page, 1, "fail")
    assert stars.count() == 49 and selected.get_attribute("data-event") == identity
    page.locator("#history-more").click()
    receive_history_page(page, 2)
    assert stars.count() == 50
    assert selected.get_attribute("data-event") == identity
    page.locator("#history-more").click()
    receive_history_page(page, 3)
    assert stars.count() == 85
    assert selected.get_attribute("data-event") == identity
    assert not page.locator("#history-more").is_visible()
    assert page.evaluate("""() => paged.requests().slice(1).map(({before, activity_kind}) =>
      [before, activity_kind])""") == [
        ["0", "follow.follow"],
        ["0", "follow.follow"],
        ["page-50", "follow.follow"],
    ]


def test_grouped_journal_replaces_unloaded_summary_in_row_order(paged_history):
    page = paged_history
    page.evaluate("document.querySelector('[data-layout=vertical]').click()")
    page.locator("#lens-trigger").click()
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    receive_history_page(page, 0)
    page.evaluate("""() => {
      window.groupHeader = document.querySelector('[data-group="follow.follow"] summary');
      groupHeader.focus({preventScroll: true});
      paged.journalEnd();
    }""")
    assert (
        page.locator('#history [data-group="follow.unfollow"] .journal-group-summary').count() == 1
    )
    receive_history_page(page, 1)
    assert (
        page.locator('#history [data-group="follow.unfollow"] .journal-group-summary').count() == 0
    )
    assert page.evaluate("document.activeElement === groupHeader && groupHeader.isConnected")
    page.evaluate("paged.journalEnd()")
    receive_history_page(page, 2)
    assert page.locator('#history [data-group="follow.unfollow"] summary').count() == 1
    assert page.locator("#history .journal-window > [data-group]").evaluate_all(
        "groups => groups.map(group => group.dataset.group)"
    ) == ["follow.follow", "follow.unfollow"]
    assert page.evaluate("document.activeElement === groupHeader && groupHeader.isConnected")


def test_stale_older_page_cannot_cross_filter_scope(paged_history):
    page = paged_history
    page.evaluate("document.querySelector('[data-filter=all]').click()")
    receive_history_page(page, 0)
    page.evaluate("document.querySelector('#history-more').click()")
    page.wait_for_function("paged.requests().length === 2", polling=20)
    page.evaluate("document.querySelector('[data-filter=lost]').click()")
    receive_history_page(page, 2)
    assert page.evaluate("paged.requests().map(request => request.before)[2]") == "0"
    assert page.evaluate("paged.requests()[1].aborted")
    page.evaluate(
        """async () => { paged.send(1); await new Promise(resolve => setTimeout(resolve, 0)); }"""
    )
    limit = page.evaluate("Number(paged.requests()[2].limit || 25)")
    assert page.locator("#history .constellation-star").count() == min(29, limit)
    assert all(
        "Unfollowed" in label
        for label in page.locator("#history .constellation-star").evaluate_all(
            "stars => stars.map(star => star.getAttribute('aria-label'))"
        )
    )


def test_parent_unmount_aborts_older_page_and_ignores_late_response(paged_history):
    page = paged_history
    page.evaluate("document.querySelector('[data-filter=all]').click()")
    receive_history_page(page, 0)
    page.evaluate("document.querySelector('#history-more').click()")
    page.wait_for_function("paged.requests().length === 2", polling=20)
    page.evaluate("""() => {
      window.detachedRoot = document.querySelector('#xf');
      detachedRoot.remove();
    }""")
    page.wait_for_function("paged.requests()[1].aborted", polling=20)
    assert page.evaluate("""async () => {
      const before = detachedRoot.outerHTML;
      paged.send(1);
      await new Promise(resolve => setTimeout(resolve, 0));
      stepFrames();
      return !detachedRoot.isConnected && detachedRoot.outerHTML === before && paintCount() === 0;
    }""")


def test_real_demo_timeline_pages_through_the_shared_range(offline_page):
    page = offline_page
    requests = []
    page.on(
        "request",
        lambda request: requests.append(request.url) if "/api/demo?" in request.url else None,
    )
    page.locator("#group-range-trigger").click()
    page.get_by_role("menuitemradio", name="All saved", exact=True).click()
    page.wait_for_function(
        """() => document.querySelectorAll('#history .constellation-star').length === 50
      && document.querySelector('#history').getAttribute('aria-busy') === 'false'""",
        polling=20,
    )
    assert len(requests) == 1
    assert "66 events" in page.locator("#scene-people-count").text_content()
    page.locator("#history-more").press("Enter")
    page.wait_for_function(
        "document.querySelectorAll('#history .constellation-star').length === 66", polling=20
    )
    assert len(requests) == 2
    assert page.locator("#history-more").is_hidden()
    assert (
        len(
            set(
                page.locator("#history [data-actor]").evaluate_all(
                    "stars => stars.map(star => star.dataset.event)"
                )
            )
        )
        == 66
    )


JOURNAL_CONTROLS = """() => {
  const history = document.querySelector('#history');
  const viewport = () => history.getBoundingClientRect();
  const buttons = () => [...history.querySelectorAll('.event-button')];
  const visible = () => buttons().filter(button => {
    const rect = button.getBoundingClientRect();
    return rect.height > 0 && rect.bottom > viewport().top && rect.top < viewport().bottom;
  });
  const settle = async () => {
    for (let index = 0; index < 4; index++) {
      stepFrames();
      await new Promise(resolve => setTimeout(resolve, 20));
    }
  };
  window.journalTest = {
    history, buttons, visible, viewport, settle,
    async scroll(top) {
      history.scrollTop = top;
      history.dispatchEvent(new Event('scroll'));
      await settle();
    },
    async reveal(index) {
      const scrubber = document.querySelector('#memory-scrubber');
      scrubber.value = String(index);
      scrubber.dispatchEvent(new Event('input', {bubbles: true}));
      await settle();
    },
  };
}"""


@pytest.fixture
def journal_page(offline_page):
    page = offline_page
    page.evaluate("document.querySelector('[data-layout=vertical]').click()")

    def history(route):
        kind = route.request.url.split("kind=", 1)[1].split("&", 1)[0]
        route.fulfill(json={"events": events if kind == "all" else [], "next": None})

    events = journal_events(2400)
    page.route("**/api/demo?*", history)
    page.evaluate("document.querySelector('[data-filter=all]').click()")
    page.wait_for_function(
        """() => document.querySelector('#history [data-event="journal-0"]')
        && document.querySelector('#history').getAttribute('aria-busy') === 'false'""",
        polling=50,
    )
    page.evaluate(JOURNAL_CONTROLS)
    page.evaluate("journalTest.settle()")
    return page


def test_journal_mounts_bounded_rows_and_reveals_a_record_after_a_jump(journal_page):
    page = journal_page
    result = page.evaluate("""async () => {
      const {history, buttons, visible, scroll, reveal} = journalTest;
      const first = visible()[0]?.dataset.event;
      const escapedName = buttons()[0]?.querySelector('.event-name')?.textContent;
      const escapedMarkup = !history.querySelector('img');
      const initialExtent = history.scrollHeight;
      const initialCount = buttons().length;
      const initialHeadings = history.querySelectorAll('.date-group').length;

      await scroll(initialExtent / 2);
      const middle = visible().map(button => Number(button.dataset.event.split('-')[1]));
      const middleCount = buttons().length;
      const oldRemoved = !history.querySelector('[data-event=journal-0]');

      await scroll(history.scrollHeight);
      const last = visible().at(-1)?.dataset.event;
      const endCount = buttons().length;

      await reveal(601);
      const selected = visible().find(button => button.dataset.event === 'journal-601');
      const pressed = selected?.getAttribute('aria-pressed');
      const ordinal = selected?.closest('article')?.getAttribute('aria-label');
      const nearDate = history.querySelectorAll('.date-group').length;

      await scroll(0);
      const restored = visible()[0]?.dataset.event;
      return {first, escapedName, escapedMarkup, initialExtent, initialCount, initialHeadings,
        middle, middleCount, oldRemoved, last, endCount, pressed, ordinal, nearDate,
        restored, unmountedSelection: !history.querySelector('[aria-pressed=true][data-event]')};
    }""")
    assert result["first"] == result["restored"] == "journal-0"
    assert result["escapedName"] == 'Name <img src=x onerror="bad()">'
    assert result["escapedMarkup"]
    assert result["initialExtent"] > 200_000
    assert max(result[key] for key in ("initialCount", "middleCount", "endCount")) < 35
    assert result["initialHeadings"] > 0 and result["nearDate"] > 0
    assert result["middle"] and all(1000 < index < 1400 for index in result["middle"])
    assert result["oldRemoved"] and result["last"] == "journal-2399"
    assert result["pressed"] == "true" and result["ordinal"] == "Event 602 of 2400 loaded"
    assert result["unmountedSelection"]
    page.evaluate("journalTest.reveal(601)")
    assert (
        page.locator('#history [data-event="journal-601"]').get_attribute("aria-pressed") == "true"
    )


def test_journal_preserves_keyboard_focus_across_window_boundaries(journal_page):
    page = journal_page
    page.evaluate("""async () => {
      await journalTest.scroll(0);
      window.journalFocused = journalTest.buttons().at(-1);
      journalFocused.focus({preventScroll: true});
    }""")
    original = page.evaluate("Number(journalFocused.dataset.event.split('-')[1])")
    page.evaluate("journalTest.scroll(journalTest.history.scrollHeight * 0.65)")
    assert page.evaluate("journalFocused.isConnected && document.activeElement === journalFocused")
    assert page.evaluate("journalTest.buttons().length") < 35
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.dataset.event") == f"journal-{original + 1}"
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.dataset.event") == f"journal-{original}"
    page.keyboard.press("Enter")
    assert page.locator("#detail-dialog").evaluate("dialog => dialog.open")
    assert (
        page.locator(f'#history [data-event="journal-{original}"]').get_attribute("aria-pressed")
        == "true"
    )


def test_journal_bounds_group_headers_and_reveals_a_collapsed_group(journal_page):
    page = journal_page
    page.locator("#lens-trigger").click()
    page.get_by_role("menuitemradio", name="Activity", exact=True).click()
    page.wait_for_function(
        """() => document.querySelector('#history details[data-group]')
        && document.querySelector('#history').getAttribute('aria-busy') === 'false'""",
        polling=50,
    )
    page.evaluate("journalTest.scroll(0)")
    summary = page.locator('#history details[data-group="follow.follow"] summary')
    assert "1800 events" in summary.inner_text()
    assert page.locator("#history .event-button").count() < 35
    page.evaluate("journalTest.scroll(journalTest.history.scrollHeight * 0.4)")
    assert (
        abs(
            summary.evaluate("node => node.getBoundingClientRect().top")
            - page.evaluate(
                "journalTest.viewport().top + parseFloat(getComputedStyle(journalTest.history).paddingTop)"
            )
        )
        <= 1
    )
    summary.press("Space")
    page.wait_for_function(
        """() => document.activeElement.matches('summary')
        && !document.activeElement.parentElement.open
        && document.activeElement.parentElement.dataset.group === 'follow.follow'""",
        polling=50,
    )
    assert page.locator('#history details[data-group="follow.follow"] .event-button').count() == 0
    page.evaluate("journalTest.reveal(900)")
    assert page.locator('#history details[data-group="follow.follow"]').evaluate(
        "node => node.open"
    )
    assert (
        page.locator('#history [data-event="journal-900"]').get_attribute("aria-pressed") == "true"
    )
    assert page.evaluate("""() => {
      const row = document.querySelector('[data-event=journal-900]').getBoundingClientRect();
      const summary = document.querySelector('#history details[data-group="follow.follow"] summary');
      return row.top >= summary.getBoundingClientRect().bottom - 1
        && row.bottom <= journalTest.viewport().bottom + 1;
    }""")

    # Enable a dynamic lens using the same preference response shape as the app.
    groups = page.evaluate("fetch('/api/status').then(response => response.json())")[
        "audience_groups"
    ]
    for group in groups:
        if group["key"] == "profile-location":
            group["enabled"] = True
    page.route(
        "**/api/audience-groups", lambda route: route.fulfill(json={"audience_groups": groups})
    )
    page.evaluate("""() => {
      const input = document.querySelector('#group-profile-location');
      input.checked = true;
      input.dispatchEvent(new Event('change'));
    }""")
    page.wait_for_function(
        """() => document.querySelector('#audience-lens').textContent.includes('Profile location')
        && document.querySelector('#history').getAttribute('aria-busy') === 'false'""",
        polling=50,
    )
    page.locator("#lens-trigger").click()
    page.get_by_role("menuitemradio", name="Profile location", exact=True).click()
    page.wait_for_function(
        """() => document.querySelector('#history details[data-group^=city-]')
        && document.querySelector('#history').getAttribute('aria-busy') === 'false'""",
        polling=50,
    )
    page.evaluate("journalTest.scroll(0)")
    assert page.locator("#history details[data-group]").count() < 20
    first = page.locator("#history details[data-group]").first
    assert first.get_attribute("data-group") == "city-000"
    assert '<img src=x onerror="bad()">' in first.locator("summary").inner_text()
    assert page.locator("#history img").count() == 0
    page.evaluate("journalTest.scroll(journalTest.history.scrollHeight)")
    assert page.locator("#history details[data-group]").count() < 20
    assert (
        page.locator("#history details[data-group]").last.get_attribute("data-group") == "unknown"
    )
    assert page.locator('#history [data-event="journal-2399"]').count() == 1


def test_journal_height_correction_preserves_the_visible_anchor(journal_page):
    page = journal_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("journalTest.scroll(journalTest.history.scrollHeight * 0.5)")
    result = page.evaluate("""async () => {
      const {buttons, visible, history, viewport, settle} = journalTest;
      const rect = node => node.getBoundingClientRect();
      const before = visible()[0];
      const top = rect(before).top;
      const above = buttons().findLast(button => rect(button).bottom <= viewport().top);
      const oldHeight = rect(above).height;
      const scrollTop = history.scrollTop;
      above.querySelector('.event-name').textContent = 'Wrapped name '.repeat(65);
      await settle();
      return {same: visible()[0]?.dataset.event === before.dataset.event,
        growth: rect(above).height - oldHeight, scrollDelta: history.scrollTop - scrollTop,
        offsetDelta: rect(before).top - top};
    }""")
    assert result["growth"] > 100, result
    assert result["same"] and abs(result["offsetDelta"]) <= 2, result
    assert abs(result["growth"] - result["scrollDelta"]) <= 2, result


def test_journal_route_layout_and_empty_history_cancel_pending_work(journal_page):
    page = journal_page
    result = page.evaluate("""async () => {
      const {history, scroll} = journalTest;
      await scroll(history.scrollHeight * 0.4);
      const transitions = [];
      for (const selector of ['[data-nav=profile]', '[data-layout=horizontal]', '[data-filter=lost]']) {
        const old = history.querySelector('.journal-window');
        const observer = new MutationObserver(() => {});
        observer.observe(old, {attributes: true, childList: true, subtree: true});
        history.scrollTop += 190;
        history.dispatchEvent(new Event('scroll'));
        const queued = journalFrameCount();
        document.querySelector(selector).click();
        stepFrames();
        transitions.push({queued, pending: journalFrameCount(), detached: !old.isConnected,
          writes: observer.takeRecords().length});
        observer.disconnect();
        if (selector === '[data-nav=profile]') document.querySelector('[data-nav=timeline]').click();
        if (selector === '[data-layout=horizontal]') document.querySelector('[data-layout=vertical]').click();
        if (selector !== '[data-filter=lost]') await journalTest.settle();
      }
      return transitions;
    }""")
    assert result == [{"queued": 1, "pending": 0, "detached": True, "writes": 0}] * 3
    page.wait_for_function(
        """() => document.querySelector('#history .empty-state')
        && document.querySelector('#history').getAttribute('aria-busy') === 'false'""",
        polling=50,
    )
    page.evaluate("document.querySelector('[data-filter=all]').click()")
    page.wait_for_selector("#history .event-button")
    assert 0 < page.locator("#history .event-button").count() < 35


MANUAL_POLL = """(() => {
  const nativeTimeout = window.setTimeout;
  window.setTimeout = (callback, delay, ...args) => {
    if (callback?.name === 'poll' && delay === 10000) {
      window.runTimelinePoll = callback;
      return 0;
    }
    return nativeTimeout(callback, delay, ...args);
  };
})()"""


def test_journal_live_history_keeps_the_anchor_and_offscreen_focus(offline_page):
    page = offline_page
    records = journal_events(850)
    first_arrival = datetime.fromisoformat(records[0]["received_at"])
    inserted = [
        {
            **records[0],
            "event_id": f"new-{index}",
            "sequence": 851 + index,
            "received_at": (first_arrival + timedelta(seconds=index + 1)).isoformat(),
        }
        for index in range(175)
    ]
    revision = "850:0::"
    requests = []

    def history(route):
        params = {
            key: value[0] for key, value in parse_qs(urlsplit(route.request.url).query).items()
        }
        requests.append(params)
        before = params.get("before", "0")
        after = params.get("after_revision")
        if after:
            assert int(after.split(":")[0]) == 850
            candidates = inserted[::-1]
            prefix = "delta-"
        else:
            candidates = (
                records if revision == "850:0::" or before != "0" else inserted[::-1] + records
            )
            prefix = "older-"
        limit = int(params.get("limit", 25))
        offset = 0 if before == "0" else int(before.removeprefix(prefix))
        end = offset + limit
        payload = {
            "events": candidates[offset:end],
            "next": f"{prefix}{end}" if end < len(candidates) else None,
        }
        if not offset:
            payload["aggregate"] = {
                "total_events": int(revision.split(":")[0]),
                "distinct_actors": 31,
                "kinds": {},
                "groups": [],
                "scope": {},
                "revision": revision,
            }
        route.fulfill(json=payload)

    def status(route):
        response = route.fetch()
        payload = response.json()
        payload["account"] = {"id": "demo", "name": "Offline fixture"}
        payload["timeline_revision"] = revision
        route.fulfill(response=response, json=payload)

    page.route("**/api/timeline?*", history)
    page.route("**/api/status", status)
    page.add_init_script(MANUAL_POLL)
    page.goto(urljoin(page.url, "/"), wait_until="networkidle")
    assert page.evaluate("typeof window.runTimelinePoll") == "function", page.locator(
        "#notice"
    ).text_content()
    page.evaluate("window.enableFrames(); document.querySelector('[data-layout=vertical]').click()")
    page.evaluate(JOURNAL_CONTROLS)
    page.evaluate("""async () => {
      await journalTest.scroll(0);
      journalTest.buttons()[0].focus({preventScroll: true});
      await journalTest.scroll(journalTest.history.scrollHeight * 0.45);
    }""")
    assert page.evaluate("document.activeElement.dataset.event") == "journal-0"
    anchor = page.evaluate("""() => {
      const row = journalTest.visible()[0];
      return {identity: row.dataset.event, offset: row.getBoundingClientRect().top};
    }""")

    older_page = f"older-{int(requests[0].get('limit', 25))}"
    assert [request.get("before", "0") for request in requests] == ["0"]
    revision = "1025:0::"
    result = page.evaluate("""async () => {
      await runTimelinePoll();
      await journalTest.settle();
      const row = journalTest.visible()[0];
      return {identity: row?.dataset.event, offset: row?.getBoundingClientRect().top,
        focus: document.activeElement.dataset.event, extent: journalTest.history.scrollHeight,
        count: journalTest.buttons().length};
    }""")
    assert result["identity"] == anchor["identity"]
    assert abs(result["offset"] - anchor["offset"]) <= 2
    assert result["focus"] == "journal-0"
    assert result["count"] < 35
    delta = [request for request in requests if request.get("after_revision")]
    assert len(delta) == 3
    assert all(
        request.get("before", "0") == "0" or request["before"].startswith("delta-")
        for request in delta
    )
    assert "Catching up on new activity" in page.locator("#history-page-status").text_content()
    page.evaluate("journalTest.scroll(journalTest.history.scrollHeight)")
    page.wait_for_function(
        "document.querySelector('#history').getAttribute('aria-busy') === 'false'", polling=20
    )
    assert requests[-1].get("before") == older_page and not requests[-1].get("after_revision")
    assert "Catching up on new activity" in page.locator("#history-page-status").text_content()
    pending_polls = 0
    while "Catching up on new activity" in page.locator("#history-page-status").text_content():
        pending_polls += 1
        assert pending_polls <= 3
        before = len(requests)
        page.evaluate("runTimelinePoll()")
        assert 0 < len(requests) - before <= 3
        assert all(request["before"].startswith("delta-") for request in requests[before:])
    assert "Catching up on new activity" not in page.locator("#history-page-status").text_content()
    assert page.evaluate("Number(document.querySelector('#memory-scrubber').max) + 1") == (
        int(older_page.removeprefix("older-")) * 2 + len(inserted)
    )


INSERT_BROWSER_EVENT = """INSERT INTO events
    (event_id,kind,account_id,actor_id,received_at) VALUES (?,?,?,?,?)"""


@pytest.fixture
def encounter_fixture(offline_browser_app):
    _, _, database = offline_browser_app
    account = "9001"
    anchor = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)
    events = [
        (
            f"gain-{index}",
            "follow.follow",
            account,
            str(2000 + index),
            (anchor - timedelta(minutes=index)).isoformat(),
        )
        for index in range(56)
    ]
    with sqlite3.connect(database) as db:
        settings = dict(
            db.execute("SELECT key,value FROM settings WHERE key IN ('account','audience_groups')")
        )
        db.executemany(
            "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
            [
                ("account", json.dumps({"id": account})),
                ("audience_groups", json.dumps({"previous-encounters": True})),
            ],
        )
        db.executemany(INSERT_BROWSER_EVENT, events)
        affected = dict(
            db.execute(
                "SELECT event_id,sequence FROM events WHERE account_id=? AND event_id IN ('gain-0','gain-55')",
                (account,),
            )
        )
    try:
        yield database, events, affected
    finally:
        with sqlite3.connect(database) as db:
            db.execute("DELETE FROM events WHERE account_id=?", (account,))
            db.execute("DELETE FROM settings WHERE key IN ('account','audience_groups')")
            db.executemany("INSERT INTO settings (key,value) VALUES (?,?)", settings.items())


@pytest.mark.parametrize(
    ("kind", "label", "loaded"),
    [("mentions", "Mentions", False), ("quotes", "Quotes", False), ("mentions", "Mentions", True)],
)
def test_real_activity_drilldown_finds_older_activity(
    encounter_fixture, offline_page, kind, label, loaded
):
    page = offline_page
    database, events, _ = encounter_fixture
    account = events[0][2]
    receipt = (datetime.fromisoformat(events[-1][4]) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(database) as db:
        selection = db.execute("SELECT value FROM settings WHERE key='selection'").fetchone()
        saved = json.loads(selection[0]) if selection else {}
        db.execute(
            "INSERT OR REPLACE INTO settings VALUES ('selection',?)",
            (json.dumps({**saved, "interactions": {kind: True}}),),
        )
        db.executemany(
            """INSERT INTO interactions
               (account_id,event_id,person_id,kind,post_id,provider_at,received_at)
               VALUES (?,?,?,?,?,?,?)""",
            [(account, f"old-{kind}", "777", kind, "123", receipt, receipt)]
            + (
                [(account, "new-mention", "777", kind, "124", events[0][4], events[0][4])]
                + [
                    (account, f"older-{index}", "777", kind, str(1000 + index), receipt, receipt)
                    for index in range(50)
                ]
                if loaded
                else []
            ),
        )
    try:
        page.goto(urljoin(page.url, "/"), wait_until="networkidle")
        page.locator("#lens-trigger").click()
        page.get_by_role("menuitemradio", name="Activity", exact=True).click()
        page.wait_for_function("document.querySelectorAll('#history [data-actor]').length === 50")
        page.locator("#scene-zoom").evaluate(
            "zoom => {zoom.value = '0'; zoom.dispatchEvent(new Event('input', {bubbles:true}));}"
        )
        card = page.get_by_role("button", name=f"Explore {label}", exact=False)
        assert ("1 action loaded" if loaded else "0 actions loaded") in card.get_attribute("title")
        with page.expect_response(lambda r: f"activity_kind=interaction.{kind}" in r.url) as hit:
            card.click()
        first = hit.value.json()
        if loaded:
            assert len(first["events"]) == 50
            assert first["events"][0]["post_id"] == "124"
            assert first["next"]
            with page.expect_response(
                lambda r: "activity_kind=interaction.mentions" in r.url
            ) as older:
                page.locator("#history-more").click()
            assert [event["post_id"] for event in older.value.json()["events"]] == ["1000", "123"]
            page.wait_for_function(
                "document.querySelectorAll('#history [data-actor]').length === 52"
            )
        else:
            assert [event["post_id"] for event in first["events"]] == ["123"]
            assert page.locator("#history [data-actor]").count() <= 1
        page.wait_for_selector("#history [data-actor='777'][aria-pressed=true]")
        assert page.locator("#scene-lens-label").inner_text() == label
    finally:
        with sqlite3.connect(database) as db:
            db.execute("DELETE FROM interactions WHERE account_id=?", (account,))
            db.execute("DELETE FROM settings WHERE key='selection'")
            if selection:
                db.execute("INSERT INTO settings VALUES ('selection',?)", selection)


def test_real_live_encounters_reclassify_filtered_history_without_resetting_cursor(
    encounter_fixture, offline_page
):
    page = offline_page
    database, events, affected = encounter_fixture
    page.add_init_script(MANUAL_POLL)
    page.goto(urljoin(page.url, "/"), wait_until="networkidle")
    page.evaluate("document.querySelector('[data-filter=gained]').click()")
    page.wait_for_function(
        "document.querySelector('#history').getAttribute('aria-busy') === 'false'"
    )
    page.locator("#lens-trigger").click()
    with page.expect_response(lambda response: "lens=previous-encounters" in response.url) as first:
        page.get_by_role("menuitemradio", name="Previous encounters", exact=True).click()
    initial = first.value.json()
    older = initial["next"]
    assert len(initial["events"]) == 50 and older
    assert initial["aggregate"]["groups"][0]["key"] == "first-appearance"
    assert initial["aggregate"]["total_events"] == 56
    page.wait_for_function(
        "document.querySelector('#history').getAttribute('aria-busy') === 'false'"
    )
    selected = page.locator('#history [data-actor][aria-pressed="true"]')
    selection = selected.get_attribute("data-event")
    assert selection and selection not in {
        f"timeline:event:{identity}" for identity in affected.values()
    }

    with sqlite3.connect(database) as db:
        db.executemany(
            INSERT_BROWSER_EVENT,
            [
                (
                    f"unfollow-{index}",
                    "follow.unfollow",
                    events[index][2],
                    events[index][3],
                    (datetime.fromisoformat(events[index][4]) - timedelta(seconds=30)).isoformat(),
                )
                for index in (0, 55)
            ],
        )
    with page.expect_response(lambda response: "after_revision=" in response.url) as live:
        page.evaluate("runTimelinePoll()")
    delta = live.value.json()
    assert delta["aggregate"]["total_events"] == 56
    assert {group["key"]: group["event_count"] for group in delta["aggregate"]["groups"]} == {
        "first-appearance": 54,
        "followed-again": 2,
    }
    assert page.locator("#history .constellation-star").count() == 50
    assert selected.get_attribute("data-event") == selection
    page.evaluate("""() => {
      const zoom = document.querySelector('#scene-zoom');
      zoom.value = '0';
      zoom.dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    followed_again = page.locator('#history [data-group="followed-again"]')
    assert followed_again.locator(".cluster-count").inner_text() == "2"
    assert "1 action loaded" in followed_again.get_attribute("title")
    older_event = page.locator(f'#history [data-event="timeline:event:{affected["gain-55"]}"]')
    assert older_event.count() == 0

    with page.expect_response(lambda response: "/api/timeline?" in response.url) as next_page:
        page.locator("#history-more").press("Enter")
    continuation = next_page.value
    assert continuation.ok
    query = parse_qs(urlsplit(continuation.url).query)
    assert query["before"] == [older]
    assert query["local_only"] == ["true"]
    assert query["encounter_revision"] == [delta["aggregate"]["revision"]]
    page.wait_for_function(
        "document.querySelectorAll('#history .constellation-star').length === 56"
    )
    assert selected.get_attribute("data-event") == selection
    assert "loaded" not in followed_again.get_attribute("title")
    assert older_event.count() == 1
    assert page.locator("#history-more").is_hidden()
