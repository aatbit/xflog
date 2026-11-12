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
let resizeScene;
globalThis.ResizeObserver = class {
  constructor(callback) { resizeScene = callback; }
  observe() {}
  disconnect() {}
};
const controls = new Map(),
  opened = [];
let olderLoads = 0;
const selectedSteps = [];
const previewSteps = [];
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
let scrollLeft = 0, roundScroll = false;
const element = {
  dataset: {},
  clientWidth: 800,
  clientHeight: 700,
  scrollWidth: 1300,
  get scrollLeft() { return scrollLeft; },
  set scrollLeft(value) { scrollLeft = roundScroll ? Math.round(value) : value; },
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
      ...value.matchAll(/<(?:button|div(?= class="star-label"))\b([^>]*)>([\s\S]*?)<\/(?:button|div)>/g),
    ].map((m) => {
      const dataset = {};
      for (const [, key, v] of m[1].matchAll(
        /data-(actor|event|label)="([^"]+)"/g,
      ))
        dataset[key] = v;
      return Object.assign(button(dataset), {
        innerHTML: m[2],
        x: Number(m[1].match(/left:([\d.]+)px/)?.[1]),
      });
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
  gained: (e) => e.kind === "follow.follow",
  onSelect: (id) => selectedSteps.push(id),
  onPreview: (id) => previewSteps.push(id),
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
assert.ok(labels.find(n=>n.dataset.label==="new-A").innerHTML.includes("Followed you"));
const label = labels.find((n) => n.dataset.label === "old-A");
assert.ok(label.innerHTML.includes("Unfollowed"));
assert.ok(!label.innerHTML.includes("recorded events"));
assert.ok(!label.innerHTML.includes("<time>"));
label.handlers.click();
nodes.find((n) => n.dataset.event === "old-A").handlers.click();
assert.deepEqual(opened, ["old-A", "old-A"]);
assert.ok(
  nodes
    .find((node) => node.dataset.event === "old-A")
    .attributes["aria-label"].includes("follow.unfollow"),
);
assert.ok(
  paths.every((path) => Number(path[1]) < Number(path[2])),
  "Light paths run from older to newer, left to right.",
);
scene.seek(0, "instant");
const start = element.scrollLeft;
scene.seek(1);
frame(1000);
assert.ok(
  element.scrollLeft > 0 && element.scrollLeft < start,
  "Manual seek uses eased travel, not an immediate jump.",
);
element.scrollLeft = 0;
handlers.pointerdown({
  pointerType: "mouse",
  button: 0,
  pointerId: 1,
  clientX: 300,
  target: { closest: () => null },
});
handlers.pointermove({ pointerId: 1, clientX: 0 });
frame(1016);
assert.ok(
  element.scrollLeft > 0 && element.scrollLeft < 300,
  "Dragging follows the same eased target as wheel input.",
);
assert.equal(previewSteps.at(-1), "old-A", "The centered person highlights before dragging ends");
assert.equal(nodes.find(n=>n.dataset.event === "old-A").attributes["aria-pressed"], "true");
assert.equal(selectedSteps.at(-1), "other-B", "Paid selection work waits until travel settles");
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
  nodes.find((node) => node.dataset.event === "old-A").attributes["aria-pressed"],
  "true",
  "Home selects the oldest displayed action, including repeated actors.",
);
scene.render([...events, event("old-C", "C", 0, "follow.follow")], "new-A");
selectedSteps.length = 0;
scene.travel(1);
scene.travel(1);
scene.travel(-1);
scene.travel(-1);
assert.deepEqual(
  selectedSteps,
  ["other-B", "old-A", "other-B", "new-A"],
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
const oldScroll = element.scrollLeft;
const oldZoom = controls.get("#scene-zoom").value;
const anchorIdentity = nodes.find(node => node.attributes["aria-pressed"] === "true").dataset.event;
scene.update([...events, event("old-C", "C", 0, "follow.follow")], anchorIdentity);
assert.equal(element.scrollLeft, oldScroll, "Local updates preserve the viewport anchor");
assert.equal(controls.get("#scene-zoom").value, oldZoom, "Local updates preserve zoom");
scene.render([...events, event("old-C", "C", 0, "follow.follow")], "new-A");
const manualStart = element.scrollLeft;
roundScroll = true;
handlers.wheel({ deltaY: -90, deltaX: 0, deltaMode: 0, preventDefault() {} });
nodes.find(node=>node.dataset.actor === "B").handlers.click();
handlers.scroll(); // A queued scroll event from the previous movement arrives after the click.
assert.equal(element.scrollLeft, manualStart, "Click travel starts without an immediate jump");
frame(2000);
assert.ok(element.scrollLeft < manualStart, "A manual click smoothly centers the chosen star");
for (let time = 2016; time <= 3024; time += 16) frame(time);
assert.ok(Math.abs(nodes.find(node=>node.dataset.actor === "B").x - element.scrollLeft - element.clientWidth / 2) < 1,
  "The clicked star lands at the viewport center");
assert.equal(nodes.find(node=>node.dataset.actor === "B").attributes["aria-pressed"], "true",
  "A stationary off-center selection survives queued scroll events");
const openedBeforeLabel = opened.length;
labels.find(node=>node.dataset.label === "old-C").handlers.click();
frame(3040);
for (let time = 3056; time <= 4064; time += 16) frame(time);
assert.ok(Math.abs(nodes.find(node=>node.dataset.actor === "C").x - element.scrollLeft - element.clientWidth / 2) < 1,
  "Clicking a name also centers its star");
assert.equal(nodes.find(node=>node.dataset.actor === "C").attributes["aria-pressed"], "true",
  "Clicking another person's label selects that person too");
assert.equal(opened.length, openedBeforeLabel, "First click selects; a second click opens details");
labels.find(node=>node.dataset.label === "old-C").handlers.click();
assert.equal(opened.at(-1), "old-C");
handlers.wheel({ deltaY: 300, deltaX: 0, deltaMode: 0, preventDefault() {} });
for (let time = 4080; time <= 5088; time += 16) frame(time);
assert.notEqual(nodes.find(node=>node.dataset.actor === "C").attributes["aria-pressed"], "true",
  "Actual viewport movement resumes center-based selection");
const activityEvents = events.map(event=>({...event,audience_groups:{activity:event.kind}}));
scene.render(activityEvents, "old-A");
scene.configure([{key:"activity",enabled:true,label:"Activity",buckets:[
  {key:"follow.follow",label:"Followed you",tone:"positive"},
  {key:"follow.unfollow",label:"Unfollowed",tone:"negative"},
]}], "activity");
assert.equal(nodes.filter(node=>node.dataset.actor === "A").length, 2,
  "The same person can have separate follow and unfollow stars");
assert.deepEqual(nodes.filter(node=>node.attributes["aria-pressed"] === "true").map(node=>node.dataset.event), ["old-A"],
  "Only the selected activity's star is highlighted");
nodes.find(node=>node.dataset.event === "new-A").handlers.click();
frame(5104);
assert.deepEqual(nodes.filter(node=>node.attributes["aria-pressed"] === "true").map(node=>node.dataset.event), ["new-A"]);
labels.find(node=>node.dataset.label === "new-A").handlers.click();
assert.equal(opened.at(-1), "new-A", "Details use the selected group record, not another activity by the same person");
root.dataset.motion = "off";
scene.update(activityEvents, "new-A");
nodes.find(node=>node.dataset.event === "old-A").handlers.click();
handlers.scroll();
frame(5120);
assert.deepEqual(nodes.filter(node=>node.attributes["aria-pressed"] === "true").map(node=>node.dataset.event), ["old-A"],
  "Manual grouped selection also survives refresh with ambient motion disabled");
const groupedStar = nodes.find(node=>node.dataset.event === "old-A");
assert.equal(element.scrollLeft, Math.round(Math.max(0, Math.min(500, groupedStar.x - element.clientWidth / 2))),
  "With motion off, grouped click centering is immediate and stays within the scroll bounds");
let prevented = 0;
const zoomWheel = (deltaY, buttons = 4, extra = {}) => handlers.wheel({
  deltaY, deltaX: 0, deltaMode: 0, buttons,
  preventDefault() { prevented++; }, ...extra,
});
scene.setZoom(0);
zoomWheel(-100);
assert.equal(Number(controls.get("#scene-zoom").value), 0.25,
  "Held middle wheel zooms in even from an overview that cannot pan");
assert.equal(prevented, 1);
zoomWheel(100);
assert.equal(Number(controls.get("#scene-zoom").value), 0);
zoomWheel(100);
assert.equal(Number(controls.get("#scene-zoom").value), 0, "Zoom stays above its lower bound");
scene.setZoom(2);
zoomWheel(-100);
assert.equal(Number(controls.get("#scene-zoom").value), 2, "Zoom stays below its upper bound");
zoomWheel(100, 4, { ctrlKey: true });
assert.equal(Number(controls.get("#scene-zoom").value), 2, "Browser zoom shortcuts are left alone");
scene.setZoom(0.8);
for (let i = 0; i < 100; i++) zoomWheel(-1);
assert.ok(Number(controls.get("#scene-zoom").value) > 0.8,
  "Fine-resolution middle-wheel deltas accumulate instead of being rounded away");
scene.setZoom(0.8);
scene.scrub(0.5);
const wheelStart = element.scrollLeft;
zoomWheel(100, 0);
frame(5140);
assert.ok(element.scrollLeft > wheelStart, "Ordinary wheel still travels through history");
assert.equal(Number(controls.get("#scene-zoom").value), 0.8,
  "Releasing middle restores ordinary timeline scrolling without sticky state");
root.dataset.route = "profile";
zoomWheel(-100);
assert.equal(Number(controls.get("#scene-zoom").value), 0.8,
  "The gesture is confined to the active constellation");
root.dataset.route = "timeline";
for (const type of ["mousedown", "auxclick"]) {
  let cancelled = false;
  handlers[type]({ button: 1, target: { closest: () => null }, preventDefault() { cancelled = true; } });
  assert.equal(cancelled, true, "Middle zoom does not start native autoscroll");
  cancelled = false;
  handlers[type]({ button: 1, target: { closest: () => ({}) }, preventDefault() { cancelled = true; } });
  assert.equal(cancelled, false, "Middle-clicking links retains normal browser behavior");
}
// The fixture prefix identifies actor-count inputs without relying on stack frames.
const NativeSet = globalThis.Set;
let actorScans = 0;
globalThis.Set = class extends NativeSet {
  constructor(values) {
    super(values);
    if (Array.isArray(values) && values.length && values.every(value =>
      typeof value === "string" && value.startsWith("count-actor-"))) actorScans++;
  }
};
const record = (id, actor, sequence, kind) => event(id, `count-actor-${actor}`, sequence, kind);
const expectCount = (text) => assert.equal(controls.get("#scene-people-count").textContent, text);
try {
  root.dataset.motion = "on";
  scene.configure([], "none");
  const records = [record("a1", "A", 4, "follow.follow"), record("a2", "A", 3, "follow.unfollow"), record("b1", "B", 2, "follow.follow")];
  const beforeRender = actorScans;
  scene.render(records, "a1");
  assert.equal(actorScans, beforeRender + 1, "New history recalculates the actor count once");
  expectCount("2 people in loaded history");
  records.push(record("a3", "A", 1, "follow.follow"));
  const beforeUpdate = actorScans;
  scene.update(records, "a1");
  assert.equal(actorScans, beforeUpdate + 1, "Data updates recalculate even for an existing actor");
  expectCount("2 people in loaded history");
  records.push(record("c1", "C", 0, "follow.follow"));
  scene.update(records, "a1");
  expectCount("3 people in loaded history");
  records[0].actor_id = "count-actor-D";
  scene.render(records, "a1");
  expectCount("4 people in loaded history");
  records[0].actor_id = "count-actor-B";
  scene.update(records, "a1");
  expectCount("3 people in loaded history");
  const beforeLayout = actorScans;
  scene.select("a2");
  scene.scrub(0.4);
  frame(6000);
  frame(6016);
  controls.get("#scene-zoom").handlers.input({ target: { value: "1.2" } });
  zoomWheel(-100);
  resizeScene();
  assert.equal(actorScans, beforeLayout, "Frames, selection, scrubbing, zoom and resize reuse the actor count");

  const groupModules = [
    {key:"activity",enabled:true,label:"Activity",buckets:[
      {key:"follow.follow",label:"Followed you",tone:"positive"},
      {key:"follow.unfollow",label:"Unfollowed",tone:"negative"},
      {key:"unknown",label:"Unknown",tone:"neutral"},
    ]},
    {key:"region",enabled:true,label:"Region",buckets:[
      {key:"known",label:"Known",tone:"neutral"},
      {key:"unknown",label:"Unknown",tone:"neutral"},
    ]},
  ];
  const groupedRecords = [
    {...record("follow-A", "A", 3, "follow.follow"), audience_groups:{activity:"follow.follow",region:"known"}},
    {...record("unfollow-A", "A", 2, "follow.unfollow"), audience_groups:{activity:"follow.unfollow"}},
    {...record("follow-B", "B", 1, "follow.follow"), audience_groups:{activity:"follow.follow",region:"unknown"}},
  ];
  scene.render(groupedRecords, "follow-A");
  expectCount("2 people in loaded history");
  const beforeConfigure = actorScans;
  scene.configure(groupModules, "activity");
  expectCount("2 people in saved history");
  scene.configure(groupModules, "region");
  expectCount("2 people in saved history");
  scene.configure(groupModules, "none");
  expectCount("2 people in loaded history");
  assert.equal(actorScans, beforeConfigure, "Changing grouping lenses reuses the actor count");
  scene.configure(groupModules, "activity");
  scene.setZoom(0);
  const beforeSeek = actorScans;
  scene.seek(0, "instant");
  assert.equal(actorScans, beforeSeek, "Leaving the grouped overview reuses the actor count");
  expectCount("2 people in saved history");
  scene.configure(groupModules, "none");
  scene.clear();
  scene.render([record("solo", "Z", 0, "follow.follow")], "solo");
  expectCount("1 person in loaded history");
  scene.update([record("z1", "Z", 1, "follow.follow"), record("z2", "Z", 0, "follow.follow")], "z1");
  expectCount("1 person in loaded history");
  const otherScene = createConstellation({
    element, root, escape: String, label: (e) => e.kind, initials: (e) => e.actor_id,
    onSelect() {}, onOpen() {},
  });
  otherScene.render([record("x", "X", 1, "follow.follow"), record("y", "Y", 0, "follow.follow")], "x");
  expectCount("2 people in loaded history");
  scene.setZoom(0.8);
  expectCount("1 person in loaded history");
  otherScene.destroy();
} finally {
  globalThis.Set = NativeSet;
}
scene.destroy();
console.log(
  JSON.stringify({
    script: new URL(import.meta.url).pathname,
    selectedRecordOpenedByLabelAndStar: true,
    personCountCorrect: true,
  }),
);
