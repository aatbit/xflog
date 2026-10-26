import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const base = pathToFileURL(process.argv[2] + "/");
const {
  constellationLayout,
  peopleFromEvents,
  visibleLabels,
  flowStep,
  wheelDistance,
  normalizeMotionSpeed,
} = await import(new URL("constellation-layout.js", base));
const { createConstellation } = await import(new URL("constellation.js", base));
const { resolveLens } = await import(new URL("audience-ui.js", base));
const modules = JSON.parse(process.argv[3]);
const locations = modules.find((module) => module.key === "profile-location");
const cityEvents = Array.from({ length: 40 }, (_, index) => ({
  actor_id: String(index),
  event_id: String(index),
  sequence: index,
  audience_groups: {
    "profile-location": index ? `location-${index}` : "unknown",
  },
  audience_group_buckets: {
    "profile-location": {
      key: index ? `location-${index}` : "unknown",
      label: index ? `City ${index}` : "Unknown",
      tone: "neutral",
    },
  },
}));
for (const width of [320, 390, 798, 1440])
  for (const height of [420, 560, 772])
    for (const zoom of [0, 0.3, 1, 2]) {
      const layout = constellationLayout({
        events: cityEvents,
        width,
        height,
        zoom,
        modules,
        lens: locations.key,
      });
      assert.ok(layout.groups.length <= 6);
      assert.ok(layout.groups.some((group) => group.key === "overview-more"));
      assert.ok(layout.groups.some((group) => group.key === "unknown"));
      assert.equal(
        layout.groups.reduce((total, group) => total + group.people.length, 0),
        40,
      );
      assert.ok(
        layout.people.every((point) => point.y > 0 && point.y < height),
      );
      assert.ok(layout.center < height / 2);
    }
const inactive = modules.map((module) => ({ ...module, enabled: false }));
assert.equal(
  resolveLens(modules, "none"),
  "none",
  "The grouping picker starts ungrouped even when Activity is available.",
);
assert.equal(
  resolveLens(modules, "none"),
  "none",
  "An explicit Ungrouped lens survives optional-group changes.",
);
assert.equal(resolveLens(inactive, "activity"), "none");
assert.equal(
  resolveLens(modules, "activity"),
  "activity",
  "An explicit grouping choice stays selected while enabled.",
);
const events = Array.from({ length: 50 }, (_, index) => ({
  actor_id: String(index % 19),
  event_id: String(index),
  sequence: index,
  audience_groups: Object.fromEntries(
    modules.map((module) => [
      module.key,
      module.buckets[index % module.buckets.length].key,
    ]),
  ),
})).reverse();
assert.equal(peopleFromEvents(events).length, 19);
assert.equal(
  peopleFromEvents([...events].reverse())[0].event.sequence,
  49,
  "Representative is latest received sequence, independent of input order.",
);
for (const width of [320, 390, 798, 1440])
  for (const height of [560, 772, 920]) {
    for (const lens of [...modules.map((module) => module.key), "none"])
      for (const zoom of [0, 0.25, 0.3, 0.55, 1, 2]) {
        const layout = constellationLayout({
          events,
          width,
          height,
          zoom,
          modules,
          lens,
        });
        assert.equal(layout.people.length, 19);
        assert.equal(
          layout.groups.reduce((sum, group) => sum + group.people.length, 0),
          19,
          "Counts are unique people, not events.",
        );
        assert.ok(layout.center < height / 2);
        assert.ok(
          layout.people.every(
            (point) =>
              Number.isFinite(point.x) &&
              point.x >= 0 &&
              point.x <= layout.width &&
              point.y >= 0 &&
              point.y < height,
          ),
        );
        if (layout.canPan) {
          layout.people
            .slice(1)
            .forEach((point, index) =>
              assert.ok(
                point.x < layout.people[index].x,
                "Newer received sequences must always lie to the right.",
              ),
            );
        }
        if (layout.overview) {
          layout.groups.forEach((a, index) =>
            layout.groups
              .slice(index + 1)
              .forEach((b) =>
                assert.ok(
                  Math.abs(a.x - b.x) >= 150 ||
                    Math.abs(a.y - b.y) >= (width < 680 ? 124 : 156) - 1e-6,
                  "Group hit targets must not overlap.",
                ),
              ),
          );
        }
        if (zoom <= 0.25) {
          assert.equal(layout.width, width);
          assert.equal(layout.canPan, false);
          assert.equal(layout.overview, lens !== "none");
        }
      }
    const disabled = constellationLayout({
      events,
      width,
      height,
      zoom: 0,
      modules: modules.map((module) => ({ ...module, enabled: false })),
      lens: "account-size",
    });
    assert.equal(disabled.overview, false);
    assert.equal(disabled.groups.length, 1);
    const boxes = Array.from({ length: 30 }, (_, index) => ({
      id: String(index),
      left: index * 35,
      right: index * 35 + 125,
      top: (index % 3) * 80,
      bottom: (index % 3) * 80 + 65,
      distance: index,
    }));
    const visible = visibleLabels(boxes, "12");
    assert.ok(visible.has("12"));
    const shown = boxes.filter((box) => visible.has(box.id));
    shown.forEach((a, index) =>
      shown
        .slice(index + 1)
        .forEach((b) =>
          assert.ok(
            a.right + 12 <= b.left ||
              b.right + 12 <= a.left ||
              a.bottom + 10 <= b.top ||
              b.bottom + 10 <= a.top,
          ),
        ),
    );
  }
const extension = {
  key: "future",
  enabled: true,
  buckets: [{ key: "unknown", label: "Unknown", tone: "neutral" }],
};
assert.equal(
  constellationLayout({
    events,
    width: 390,
    height: 772,
    zoom: 0,
    modules: [extension],
    lens: "future",
  }).groups[0].people.length,
  19,
  "New registered module needs no renderer branch.",
);
assert.ok(
  Math.abs(flowStep(flowStep(0, 100, 8), 100, 8) - flowStep(0, 100, 16)) < 1e-8,
);
assert.ok(
  wheelDistance({ deltaX: 0, deltaY: 100, deltaMode: 0 }, 390) > 0,
  "Wheel down travels right toward newer events.",
);
assert.equal(normalizeMotionSpeed("invalid"), 1);
assert.equal(normalizeMotionSpeed(-1), 0.25);
assert.equal(normalizeMotionSpeed(20), 2);

function exercise(refreshRate, speed = 1, duration = 1000) {
  const pending = new Map();
  let nextId = 0,
    writes = 0,
    observer;
  const handlers = {};
  const control = () => ({
    style: { setProperty() {} },
    classList: { toggle() {} },
    setAttribute() {},
    addEventListener() {},
    removeEventListener() {},
  });
  const controls = new Map();
  const star = {
    style: {
      set opacity(value) {
        this.value = value;
        writes++;
      },
    },
  };
  const sky = { style: {}, setAttribute() {} };
  const meteor = { style: {}, dataset: {}, setAttribute() {} };
  const reduced = {
    matches: false,
    addEventListener(type, callback) {
      this.callback = callback;
    },
    removeEventListener() {},
  };
  globalThis.matchMedia = () => reduced;
  globalThis.requestAnimationFrame = (callback) => {
    pending.set(++nextId, callback);
    return nextId;
  };
  globalThis.cancelAnimationFrame = (id) => pending.delete(id);
  globalThis.document = {
    hidden: false,
    addEventListener(type, callback) {
      handlers[type] = callback;
    },
    removeEventListener() {},
  };
  globalThis.MutationObserver = class {
    constructor(callback) {
      observer = this;
      this.callback = callback;
    }
    observe() {}
    disconnect() {
      this.disconnected = true;
    }
  };
  globalThis.ResizeObserver = class {
    observe() {}
    disconnect() {}
  };
  const root = {
    dataset: { route: "timeline", motion: "on", motionSpeed: String(speed) },
    querySelector(selector) {
      if (!controls.has(selector)) controls.set(selector, control());
      return controls.get(selector);
    },
  };
  const element = {
    dataset: {},
    clientWidth: 800,
    clientHeight: 700,
    scrollWidth: 800,
    scrollLeft: 0,
    classList: { contains: () => true, toggle() {} },
    querySelector: (selector) => (selector === ".shooting-star" ? meteor : sky),
    querySelectorAll: (selector) => (selector === ".sky-star" ? [star] : []),
    addEventListener() {},
    removeEventListener() {},
  };
  const scene = createConstellation({ element, root });
  scene.render([], null);
  const frame = (now) => {
    assert.equal(pending.size, 1, "Exactly one animation frame is scheduled.");
    const [id, callback] = pending.entries().next().value;
    pending.delete(id);
    callback(now);
  };
  for (let index = 0; index <= (refreshRate * duration) / 1000; index++)
    frame(1000 + (index * 1000) / refreshRate);
  assert.equal(
    writes,
    (refreshRate * duration) / 1000 + 1,
    "Every available display frame paints; no fixed FPS cap.",
  );
  const finalOpacity = star.style.value;
  root.dataset.motionSpeed = "2";
  observer.callback();
  frame(1000 + duration);
  assert.equal(
    star.style.value,
    finalOpacity,
    "Speed change preserves current phase.",
  );
  root.dataset.route = "profile";
  observer.callback();
  assert.equal(pending.size, 0);
  assert.equal(root.dataset.animating, "false");
  root.dataset.route = "timeline";
  observer.callback();
  frame(100000);
  assert.equal(
    star.style.value,
    finalOpacity,
    "Profile return resumes without a time jump.",
  );
  document.hidden = true;
  handlers.visibilitychange();
  assert.equal(pending.size, 0);
  document.hidden = false;
  handlers.visibilitychange();
  frame(100100);
  root.dataset.motion = "off";
  observer.callback();
  frame(100200);
  assert.equal(pending.size, 0);
  root.dataset.motion = "on";
  observer.callback();
  frame(100300);
  reduced.matches = true;
  reduced.callback();
  frame(100400);
  assert.equal(pending.size, 0, "Reduced motion stops the continuous loop.");
  scene.destroy();
  assert.equal(pending.size, 0);
  assert.ok(observer.disconnected);
  return Number(finalOpacity);
}
assert.ok(Math.abs(exercise(60) - exercise(120)) < 1e-10);
assert.ok(Math.abs(exercise(60) - exercise(144)) < 1e-10);
assert.ok(Math.abs(exercise(60, 2) - exercise(60, 1, 2000)) < 1e-10);
