"""Exercise parent-owned scene replacement against the real offline UI."""

import importlib.util
import os
import socket
import subprocess
import sys
import time
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
  window.paintCount = () => [...frames.values()].filter(cb => cb.name === 'paint').length;
  window.stepFrames = () => {
    const callbacks = [...frames.values()]; frames.clear();
    callbacks.forEach(cb => cb(performance.now()));
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
