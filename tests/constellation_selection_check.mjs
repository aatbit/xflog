import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
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
    if (!controls.has(key))
      controls.set(key, {
        style: { setProperty() {} },
        classList: { toggle() {} },
        setAttribute() {},
        addEventListener() {},
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
    return { style: {} };
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
  onSelect() {},
  onOpen: (id) => opened.push(id),
});
scene.render(events, "old-A");
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
assert.ok(
  controls.get("#memory-next").disabled &&
    controls.get("#memory-previous").disabled,
  "Fit hides and disables both side controls.",
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
scene.destroy();
console.log(
  JSON.stringify({
    script: new URL(import.meta.url).pathname,
    selectedRecordOpenedByLabelAndStar: true,
    personCountCorrect: true,
  }),
);
