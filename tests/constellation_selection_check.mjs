import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
const controlIds = new Set(
  [
    ...readFileSync(join(process.argv[2], "shell.html"), "utf8").matchAll(
      /\bid="([^"]+)"/g,
    ),
  ].map((match) => match[1]),
);
const { createConstellation } = await import(
  new URL("constellation.js", pathToFileURL(process.argv[2] + "/"))
);
globalThis.matchMedia = () => ({
  matches: false,
  addEventListener() {},
  removeEventListener() {},
});
const pending = new Map();
let frameId = 0;
globalThis.requestAnimationFrame = (callback) => {
  pending.set(++frameId, callback);
  return frameId;
};
globalThis.cancelAnimationFrame = (id) => pending.delete(id);
function frame(time) {
  const [id, callback] = pending.entries().next().value;
  pending.delete(id);
  callback(time);
}
globalThis.document = {
  hidden: false,
  addEventListener() {},
  removeEventListener() {},
};
globalThis.MutationObserver = class {
  observe() {}
  disconnect() {}
};
globalThis.ResizeObserver = class {
  observe() {}
  disconnect() {}
};
const controls = new Map(),
  opened = [];
let olderLoads = 0;
const selectedSteps = [];
function button(dataset) {
  return {
    dataset,
    style: {},
    attributes: {},
    handlers: {},
    innerHTML: "",
    classList: { toggle() {} },
    setAttribute(k, v) {
      this.attributes[k] = v;
    },
    addEventListener(k, v) {
      this.handlers[k] = v;
    },
    removeEventListener() {},
    closest() {
      return { classList: { toggle() {} } };
    },
    getBoundingClientRect() {
      return { width: 190, height: 140 };
    },
  };
}
const root = {
  dataset: { route: "timeline", motion: "on" },
  querySelector(key) {
    if (key.startsWith("#") && !controlIds.has(key.slice(1))) return null;
    if (!controls.has(key))
      controls.set(key, {
        handlers: {},
        style: { setProperty() {} },
        classList: { toggle() {} },
        setAttribute() {},
        addEventListener(type, handler) {
          this.handlers[type] = handler;
        },
        removeEventListener() {},
      });
    return controls.get(key);
  },
};
let nodes = [],
  labels = [],
  paths = [];
const handlers = {};
const element = {
  dataset: {},
  clientWidth: 800,
  clientHeight: 700,
  scrollWidth: 1300,
  scrollLeft: 0,
  classList: {
    contains() {
      return true;
    },
    toggle() {},
  },
  addEventListener(type, handler) {
    handlers[type] = handler;
  },
  removeEventListener() {},
  setPointerCapture() {},
  hasPointerCapture() {
    return true;
  },
  releasePointerCapture() {},
  querySelector() {
    return { style: {}, dataset: {}, setAttribute() {} };
  },
  querySelectorAll(key) {
    return key === "[data-actor]"
      ? nodes
      : key === "[data-label]"
        ? labels
        : [];
  },
  set innerHTML(value) {
    paths = [...value.matchAll(/<path d="M([\d.]+),[\d.]+L([\d.]+),[\d.]+"/g)];
    const buttons = [
      ...value.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g),
    ].map((m) => {
      const dataset = {};
      for (const [, key, v] of m[1].matchAll(
        /data-(actor|event|label)="([^"]+)"/g,
      ))
        dataset[key] = v;
      return Object.assign(button(dataset), { innerHTML: m[2] });
    });
    nodes = buttons.filter((n) => n.dataset.actor);
    labels = buttons.filter((n) => n.dataset.label);
  },
};
const stamp = "2026-10-26T12:00:00Z";
const event = (event_id, actor_id, sequence, kind) => ({
  event_id,
  actor_id,
  sequence,
  kind,
  name: actor_id,
  received_at: stamp,
});
const events = [
  event("new-A", "A", 3, "follow.follow"),
  event("other-B", "B", 2, "follow.follow"),
  event("old-A", "A", 1, "follow.unfollow"),
];
const scene = createConstellation({
  element,
  root,
  escape: String,
  label: (e) => e.kind,
  initials: (e) => e.actor_id,
  date: new Intl.DateTimeFormat("en"),
  time: new Intl.DateTimeFormat("en"),
  gained: (e) => e.kind === "follow.follow",
  onSelect: (id) => selectedSteps.push(id),
  onOpen: (id) => opened.push(id),
  hasOlder: () => true,
  onOlder: () => olderLoads++,
});
scene.render(events, "old-A");
assert.equal(
  Number(controls.get("#scene-zoom").value),
  0.8,
  "First render starts at 80% zoom.",
);
assert.equal(controls.get("#zoom-value").textContent, "80%");
controls.get("#zoom-in").handlers.click();
assert.equal(Number(controls.get("#scene-zoom").value), 1.05);
controls.get("#zoom-out").handlers.click();
assert.equal(Number(controls.get("#scene-zoom").value), 0.8);
controls.get("#scene-zoom").handlers.input({ target: { value: "1.2" } });
assert.equal(controls.get("#zoom-value").textContent, "120%");
scene.setZoom(0.8);
const label = labels.find((n) => n.dataset.label === "A");
assert.ok(label.innerHTML.includes("follow.unfollow"));
assert.ok(label.innerHTML.includes("2 recorded events"));
label.handlers.click();
nodes.find((n) => n.dataset.actor === "A").handlers.click();
assert.deepEqual(opened, ["old-A", "old-A"]);
assert.ok(
  nodes
    .find((node) => node.dataset.actor === "A")
    .attributes["aria-label"].includes("follow.unfollow"),
);
assert.ok(
  paths.every((path) => Number(path[1]) < Number(path[2])),
  "Light paths run from older to newer, left to right.",
);
const start = element.scrollLeft;
scene.seek(1);
frame(1000);
assert.ok(
  element.scrollLeft > 0 && element.scrollLeft < start,
  "Manual seek uses eased travel, not an immediate jump.",
);
element.scrollLeft = 200;
handlers.pointerdown({
  pointerType: "mouse",
  button: 0,
  pointerId: 1,
  clientX: 300,
  target: { closest: () => null },
});
handlers.pointermove({ pointerId: 1, clientX: 200 });
frame(1016);
assert.ok(
  element.scrollLeft > 200 && element.scrollLeft < 300,
  "Dragging follows the same eased target as wheel input.",
);
handlers.pointerup({ pointerId: 1 });
frame(1032);
assert.ok(
  element.scrollLeft < 300,
  "Release preserves the remaining smooth travel.",
);
scene.setZoom(0);
assert.equal(
  controls.get("#memory-scrubber").disabled,
  true,
  "Overview disables panning instead of moving a meaningless thumb.",
);
assert.ok(
  controls.get("#memory-next").disabled &&
    controls.get("#memory-previous").disabled,
  "Full overview hides and disables both side controls.",
);
scene.setZoom(0.8);
element.scrollLeft = 0;
handlers.wheel({ deltaY: -100, deltaX: 0, deltaMode: 0, preventDefault() {} });
assert.equal(
  olderLoads,
  1,
  "Wheel at the oldest edge can request the next history page.",
);
scene.travel(1);
assert.equal(
  olderLoads,
  2,
  "The Older side control can request the next page at the edge.",
);
handlers.keydown({
  key: "Home",
  target: { closest: () => null },
  preventDefault() {},
});
assert.equal(
  nodes.find((node) => node.dataset.actor === "B").attributes["aria-pressed"],
  "true",
  "Home selects the oldest displayed person, not a later repeated actor.",
);
scene.render([...events, event("old-C", "C", 0, "follow.follow")], "new-A");
selectedSteps.length = 0;
scene.travel(1);
scene.travel(1);
scene.travel(-1);
scene.travel(-1);
assert.deepEqual(
  selectedSteps,
  ["other-B", "old-C", "other-B", "new-A"],
  "Rapid Older/Newer clicks step exactly one selected profile before any animation frame.",
);
scene.seek(0);
for (const progress of [1, 0, 0.72, 0.13, 1, 0.5]) {
  scene.scrub(progress);
  assert.ok(Math.abs(element.scrollLeft - (1 - progress) * 500) < 0.001);
  assert.equal(
    Number(controls.get("#memory-scrubber").value),
    Math.round(progress * 1000),
  );
  assert.equal(
    Number(controls.get("#scene-zoom").value),
    0.8,
    "Scrubbing never changes zoom.",
  );
}
frame(1048);
assert.equal(
  element.scrollLeft,
  250,
  "A pending eased seek cannot resume after scrubbing reverses direction.",
);
assert.equal(
  Number(controls.get("#memory-scrubber").value),
  500,
  "The thumb stays aligned with the actual viewport, not a repeated actor's event index.",
);
scene.destroy();
console.log(
  JSON.stringify({
    script: new URL(import.meta.url).pathname,
    selectedRecordOpenedByLabelAndStar: true,
    personCountCorrect: true,
  }),
);
