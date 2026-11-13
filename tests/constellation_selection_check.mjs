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
const { constellationLayout, seed } = await import(
  new URL("constellation-layout.js", pathToFileURL(process.argv[2] + "/"))
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
let shellQueries = 0, sceneQueries = 0, actorQueries = 0, descendantQueries = 0;
let parentQueries = 0;
let labelReads = 0, previewReads = 0, navigationWrites = 0;
let collisionPasses = 0;
function countNavigation(control) {
  const fields = new Set(["disabled", "value", "textContent", "max", "hidden", "innerHTML"]);
  return new Proxy(control, {
    set(target, key, value) {
      if (fields.has(key)) navigationWrites++;
      return Reflect.set(target, key, value);
    },
  });
}
const selectedSteps = [];
const previewSteps = [];
function button(dataset) {
  const parent = { writes: 0, classList: { toggle() { parent.writes++; } } };
  return {
    dataset,
    parent,
    style: {},
    attributes: {},
    handlers: {},
    markup: "",
    get innerHTML() { return this.markup; },
    set innerHTML(value) {
      this.markup = value;
      this.identityControl = { tabIndex: 0 };
      this.previewControl = value.includes('class="star-post"')
        ? { tabIndex: 0, get offsetHeight() { previewReads++; return 24; }, style: {} } : null;
    },
    classList: { toggle() {} },
    setAttribute(k, v) {
      this.attributeWrites = (this.attributeWrites || 0) + 1;
      this.attributes[k] = v;
    },
    removeAttribute(k) { delete this.attributes[k]; },
    addEventListener(k, v) {
      listenerWrites++;
      this.handlers[k] = v;
    },
    removeEventListener() {},
    closest(selector) {
      if (selector === ".constellation-person") parentQueries++;
      return parent;
    },
    getBoundingClientRect() {
      labelReads++;
      return { width: 190, height: 140 };
    },
    querySelectorAll() { descendantQueries++; return [this.identityControl, this.previewControl].filter(Boolean); },
    querySelector() { descendantQueries++; return this.previewControl; },
  };
}
const root = {
  isConnected: true,
  dataset: { route: "timeline", motion: "on" },
  querySelector(key) {
    shellQueries++;
    if (key.startsWith("#") && !controlIds.has(key.slice(1))) return null;
    if (!controls.has(key))
      controls.set(key, countNavigation({
        handlers: {},
        style: { setProperty() {} },
        classList: { toggle() {} },
        setAttribute() { navigationWrites++; },
        addEventListener(type, handler) {
          this.handlers[type] = handler;
        },
        removeEventListener() {},
      }));
    return controls.get(key);
  },
};
let nodes = [],
  labels = [],
  paths = [];
let renderedLinks = [], renderedTrails = [], renderedSparks = [], groupNodes = [];
let historyWrites = 0, linkWrites = 0, groupWrites = 0, listenerWrites = 0;
let beforeMarkup = false, measureRenderWork = false;
let sceneParts = {};
const handlers = {};
let scrollLeft = 0, roundScroll = false, capturedPointers = 0, releasedPointers = 0;
const element = {
  isConnected: true,
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
  setPointerCapture() { capturedPointers++; },
  hasPointerCapture() {
    return true;
  },
  releasePointerCapture() { releasedPointers++; },
  querySelector(key) {
    sceneQueries++;
    return sceneParts[key];
  },
  querySelectorAll(key) {
    if (key === "[data-actor]") actorQueries++;
    return key === "[data-actor]"
      ? nodes
      : key === "[data-label]"
        ? labels
        : key === ".sequence-trail" ? renderedTrails
        : key === ".sequence-spark" ? renderedSparks
        : [];
  },
  contains(node) { return nodes.includes(node) || labels.includes(node) || groupNodes.includes(node) || Object.values(sceneParts).includes(node); },
  set innerHTML(value) {
    historyWrites++;
    beforeMarkup = false;
    sceneParts = Object.fromEntries([".constellation-sky", ".shooting-star", ".shooting-tail", ".constellation-canvas"]
      .map(key => [key, button({})]));
    sceneParts[".shooting-star"].dataset = {};
    groupNodes = [];
    renderedLinks = [];
    renderedSparks = [];
    renderedTrails = [];
    paths = [];
    sceneParts[".constellation-links"] = {
      ...button({}),
      set innerHTML(markup) {
        linkWrites++;
        renderedLinks = [...markup.matchAll(/<g data-link-group="([^"]*)" style="([^"]*)"><path d="([^"]*)" stroke-dasharray="([^"]*)"\/>/g)]
          .map(([, group, style, d, dash]) => ({group, style, d, dash}));
        paths = [...markup.matchAll(/<path d="M([\d.]+),[\d.]+L([\d.]+),[\d.]+"/g)];
        renderedTrails = renderedLinks.map(() => button({}));
        renderedSparks = renderedLinks.map(() => button({}));
        this.pathNodes = renderedLinks.map(link => ({
          setAttribute(key, value) { if (key === "d") link.d = value; },
        }));
      },
      querySelectorAll(key) {
        if (key === "path") return this.pathNodes;
        return key === ".sequence-trail" ? renderedTrails : renderedSparks;
      },
    };
    sceneParts[".constellation-groups"] = {
      hidden: true,
      contains(node) { return groupNodes.includes(node); },
      set innerHTML(markup) {
        groupWrites++;
        groupNodes = [...markup.matchAll(/data-group="([^"]*)"/g)].map(([, group]) => button({group}));
      },
      querySelectorAll() { return groupNodes; },
    };
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
        style: {left: m[1].match(/left:([\d.]+px)/)?.[1]},
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
const resizeFirstScene = resizeScene;
const firstSceneHandlers = {...handlers};
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
assert.ok(Math.abs(parseFloat(nodes.find(node=>node.dataset.actor === "B").style.left) - element.scrollLeft - element.clientWidth / 2) < 1,
  "The clicked star lands at the viewport center");
assert.equal(nodes.find(node=>node.dataset.actor === "B").attributes["aria-pressed"], "true",
  "A stationary off-center selection survives queued scroll events");
const openedBeforeLabel = opened.length;
labels.find(node=>node.dataset.label === "old-C").handlers.click();
frame(3040);
for (let time = 3056; time <= 4064; time += 16) frame(time);
assert.ok(Math.abs(parseFloat(nodes.find(node=>node.dataset.actor === "C").style.left) - element.scrollLeft - element.clientWidth / 2) < 1,
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
firstSceneHandlers.scroll();
frame(5120);
assert.deepEqual(nodes.filter(node=>node.attributes["aria-pressed"] === "true").map(node=>node.dataset.event), ["old-A"],
  "Manual grouped selection also survives refresh with ambient motion disabled");
const groupedStar = nodes.find(node=>node.dataset.event === "old-A");
assert.equal(element.scrollLeft, Math.round(Math.max(0, Math.min(500, parseFloat(groupedStar.style.left) - element.clientWidth / 2))),
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
  scene.render([record("solo", "Z", 0, "follow.follow")], "solo");
  expectCount("1 person in loaded history");
  otherScene.destroy();
} finally {
  globalThis.Set = NativeSet;
}
const beforeParentRender = parentQueries;
scene.render(events, "old-A");
const initialParents = parentQueries;
assert.equal(initialParents - beforeParentRender, events.length, "Each actor resolves its parent once on render");
const previousParent = nodes[0].parent;
scene.select("other-B");
assert.equal(parentQueries, initialParents, "Selection reuses actor parent references");
const beforePreview = previewSteps.length;
element.scrollLeft = 1;
firstSceneHandlers.scroll();
frame(6992);
assert.ok(previewSteps.length > beforePreview, "Scrolling actually changes selection during paint");
assert.equal(parentQueries, initialParents, "Animation-driven selection reuses actor parents");
const previousSky = sceneParts[".constellation-sky"];
const beforeQueries = {shellQueries, sceneQueries, actorQueries, descendantQueries};
scene.select("other-B");
frame(7000);
frame(7016);
assert.equal(shellQueries, beforeQueries.shellQueries, "Shell controls are reused during selection and frames");
assert.equal(sceneQueries, beforeQueries.sceneQueries, "Frames reuse scene-specific elements");
assert.equal(actorQueries, beforeQueries.actorQueries, "Selection reuses the current actor buttons");
assert.equal(descendantQueries, beforeQueries.descendantQueries, "Unchanged label markup reuses its descendants");
const beforeRedrawParents = parentQueries;
scene.setZoom(1);
assert.equal(parentQueries, beforeRedrawParents, "Zoom reuses actor parents");
assert.equal(sceneParts[".constellation-sky"], previousSky, "Zoom reuses the sky");
scene.render(events, "other-B");
assert.equal(parentQueries - beforeRedrawParents, events.length, "Structural redraw resolves one fresh parent per actor");
const oldParentWrites = previousParent.writes;
assert.notEqual(nodes[0].parent, previousParent, "A redraw creates fresh actor parents");
assert.notEqual(sceneParts[".constellation-sky"], previousSky, "A redraw creates new sky nodes");
previousSky.style.transform = "old scene";
frame(7032);
assert.equal(previousParent.writes, oldParentWrites, "Detached actor parents are not updated");
assert.equal(previousSky.style.transform, "old scene", "Frames never update the detached sky after redraw");
assert.notEqual(sceneParts[".constellation-sky"].style.transform, undefined, "Frames update the new sky");
const beforeResizeSky = sceneParts[".constellation-sky"];
element.clientWidth++;
resizeFirstScene();
element.clientWidth--;
beforeResizeSky.style.transform = "detached after resize";
frame(7040);
assert.equal(beforeResizeSky.style.transform, "detached after resize", "Resize never paints the previous sky");
assert.notEqual(sceneParts[".constellation-sky"].style.transform, undefined, "Resize uses the new sky");
scene.clear();
scene.clear();
assert.equal(pending.size, 0, "Clear cancels the active frame");
scene.render(events, "new-A");
frame(7048);
assert.notEqual(sceneParts[".constellation-sky"].style.transform, undefined, "A new scene works after clear");
firstSceneHandlers.pointerdown({pointerType:"mouse",button:0,pointerId:88,clientX:300,target:{closest:()=>null}});
assert.equal(element.dataset.panning, "true", "A real drag starts before clearing");
const beforeClearRelease = releasedPointers;
scene.clear();
assert.equal(releasedPointers, beforeClearRelease + 1, "Clear releases the pointer capture");
assert.equal(element.dataset.panning, undefined, "Clear releases drag state");
scene.render(events, "new-A");
const afterRecreate = element.scrollLeft;
firstSceneHandlers.pointermove({pointerId:88,clientX:0});
frame(7056);
assert.equal(element.scrollLeft, afterRecreate, "A drag from the cleared scene cannot move its replacement");
const detachedSky = sceneParts[".constellation-sky"];
detachedSky.style.transform = "unmounted";
const detachedParent = nodes[0].parent;
const detachedWrites = detachedParent.writes;
root.isConnected = false;
scene.select("other-B");
frame(7060);
assert.equal(detachedSky.style.transform, "unmounted", "Unmounted scene is not repainted");
assert.equal(detachedParent.writes, detachedWrites, "Unmounted scene is not selected");
assert.equal(pending.size, 0, "Unmounted scene does not queue another frame");
root.isConnected = true;
element.isConnected = false;
scene.select("other-B");
assert.equal(detachedParent.writes, detachedWrites, "Detached history is not selected");
assert.equal(pending.size, 0, "Detached history does not queue another frame");
element.isConnected = true;
const withPreview = {...event("preview", "P", 1, "interaction.replies"), post_id:"123", post_text:"First post"};
scene.render([withPreview], "preview");
const oldLabel = labels[0], oldPreview = oldLabel.previewControl;
frame(7064);
assert.ok(oldPreview && oldPreview.style.top, "Selected post preview is updated by paint");
const beforeSameSelection = descendantQueries;
scene.select("preview");
assert.equal(descendantQueries, beforeSameSelection, "Selecting unchanged markup reuses descendants");
scene.update([{...withPreview, post_text:"Updated post"}], "preview");
const newLabel = labels[0], newPreview = newLabel.previewControl;
assert.notEqual(newPreview, oldPreview, "Updated scene receives new preview controls");
oldPreview.style.top = "detached";
newPreview.tabIndex = -1;
frame(7080);
assert.equal(oldPreview.style.top, "detached", "A detached preview is not updated");
assert.ok(newPreview.style.top, "Updated preview receives positioning");
assert.equal(newPreview.tabIndex, 0, "Visible preview remains keyboard accessible");
scene.render(events, "old-A");
const beforeDestroyCapture = capturedPointers, beforeDestroyRelease = releasedPointers;
firstSceneHandlers.pointerdown({pointerType:"mouse",button:0,pointerId:77,clientX:300,target:{closest:()=>null}});
assert.equal(capturedPointers, beforeDestroyCapture + 1, "Destroy test starts with a captured drag");
scene.destroy();
assert.equal(releasedPointers, beforeDestroyRelease + 1, "Destroy releases the pointer capture");
assert.equal(element.dataset.panning, undefined, "Destroy clears the active drag state");
assert.equal(pending.size, 0, "Destroy cancels the active frame");
scene.select("preview");
assert.equal(pending.size, 0, "Selecting after destroy cannot queue work on released nodes");
const originalRandom = Math.random;
Math.random = () => 0;
try {
  const meteorScene = createConstellation({
    element, root, escape: String, label: (e) => e.kind, initials: (e) => e.actor_id,
    onSelect() {}, onOpen() {},
  });
  meteorScene.render(events, "old-A");
  for (let i = 0; i < 96; i++) frame(10000 + i * 64);
  const oldMeteor = sceneParts[".shooting-star"], oldTail = sceneParts[".shooting-tail"];
  element.clientWidth++;
  resizeScene();
  element.clientWidth--;
  oldMeteor.style.opacity = "detached";
  oldTail.attributes = {};
  frame(10000 + 96 * 64);
  assert.equal(oldMeteor.style.opacity, "detached", "Detached meteor is not repainted");
  assert.deepEqual(oldTail.attributes, {}, "Detached tail is not repainted");
  assert.ok(sceneParts[".shooting-tail"].attributes.x1, "New tail receives active meteor coordinates");
  assert.notEqual(sceneParts[".shooting-star"].style.opacity, undefined, "New meteor is repainted");
  meteorScene.destroy();
} finally {
  Math.random = originalRandom;
}

// Count searches of positioned geometry entries, while leaving normal event searches alone.
const nativeFind = Array.prototype.find;
let geometryFinds = 0;
Array.prototype.find = function(predicate, ...args) {
  if (this.length && this[0]?.event && Array.isArray(this[0]?.events) && "x" in this[0])
    geometryFinds++;
  return nativeFind.call(this, predicate, ...args);
};
try {
  const control = [{event: {}, events: [], x: 0}];
  control.find(() => true);
  assert.equal(geometryFinds, 1, "The geometry-search counter has a positive control");
  const many = Array.from({length: 24}, (_, index) => ({
    ...event(`lookup-${index}`, "same-actor", 24 - index, "follow.follow"),
    name: `Person ${index}`,
  }));
  const previews = [], lookupSelected = [], lookupOpened = [];
  const lookupScene = createConstellation({
    element, root, escape: String, label: (item) => item.kind, initials: (item) => item.actor_id,
    onSelect: (identity) => lookupSelected.push(identity),
    onPreview: (identity) => previews.push(identity), onOpen: (identity) => lookupOpened.push(identity),
  });
  const lookupHandlers = {...handlers};
  root.dataset.motion = "on";
  lookupScene.render(many, "lookup-0");
  assert.equal(nodes.length, many.length, "Every action by one actor has its own button");
  geometryFinds = 0;
  for (const identity of ["lookup-4", "lookup-17", "lookup-0"]) {
    const before = geometryFinds;
    lookupScene.select(identity);
    assert.equal(geometryFinds - before, 0, "Manual selection reuses its indexed geometry entry");
    const selectedNodes = nodes.filter(node => node.attributes["aria-pressed"] === "true");
    assert.deepEqual(selectedNodes.map(node => node.dataset.event), [identity]);
    assert.ok(selectedNodes[0].attributes["aria-label"].includes(`Person ${identity.slice(7)}`));
  }
  const beforePreview = previews.length;
  const beforeFrameSearches = geometryFinds;
  element.scrollLeft = 1;
  lookupHandlers.scroll();
  frame(20000);
  assert.ok(previews.length > beforePreview, "The frame actually changes the highlighted event");
  assert.equal(geometryFinds - beforeFrameSearches, 0, "Animation-driven selection does not scan for the selected event");

  const large = Array.from({length: 500}, (_, index) => ({
    ...event(`lookup-${index}`, "same-actor", 500 - index, "follow.follow"), name: `Person ${index}`,
  }));
  lookupScene.render(large, "lookup-0");
  geometryFinds = 0;
  lookupScene.select("lookup-4");
  assert.equal(geometryFinds, 0, "Manual search count stays constant for 500 actor buttons");
  lookupScene.select("lookup-0");
  const beforeLargePreview = previews.length;
  geometryFinds = 0;
  element.scrollLeft = 1;
  lookupHandlers.scroll();
  frame(20016);
  assert.ok(previews.length > beforeLargePreview, "The large-scene frame changes the highlighted event");
  assert.equal(geometryFinds, 0, "Animation search count stays constant for 500 actor buttons");

  lookupScene.render(many, "lookup-0");
  lookupScene.select("lookup-0");
  const currentButton = nodes.find(node => node.dataset.event === "lookup-0");
  geometryFinds = 0;
  currentButton.handlers.click();
  assert.equal(geometryFinds, 0, "A selected actor click reuses the selected position");
  assert.equal(lookupOpened.at(-1), "lookup-0", "A current selected actor still opens");
  const nonselectedButton = nodes.find(node => node.dataset.event === "lookup-4");
  nonselectedButton.handlers.click();
  assert.equal(lookupSelected.at(-1), "lookup-4", "A current unselected actor still selects");
  const beforeInvalidClicks = [lookupSelected.length, lookupOpened.length, element.scrollLeft];
  const index = nodes.indexOf(nonselectedButton);
  nodes.splice(index, 1);
  nonselectedButton.handlers.click();
  nodes.splice(index, 0, nonselectedButton);
  root.isConnected = false;
  nonselectedButton.handlers.click();
  root.isConnected = true;
  element.isConnected = false;
  nonselectedButton.handlers.click();
  element.isConnected = true;
  nonselectedButton.dataset.event = "changed-id";
  nonselectedButton.handlers.click();
  nonselectedButton.dataset.event = "lookup-4";
  assert.deepEqual([lookupSelected.length, lookupOpened.length, element.scrollLeft], beforeInvalidClicks,
    "Detached or mismatched current buttons cannot act");

  const oldButton = nodes.find(node => node.dataset.event === "lookup-1");
  const removedButton = currentButton;
  const oldParent = nodes[0].parent;
  const oldWrites = oldParent.writes;
  const next = [{...many[1], name: "Updated person"}, ...many.slice(2), event("new-event", "same-actor", 0, "follow.follow")];
  lookupScene.update(next, "lookup-1");
  assert.ok(nodes.find(node => node.dataset.event === "lookup-1").attributes["aria-label"].includes("Updated person"));
  const actionsAfterUpdate = [lookupSelected.length, lookupOpened.length, element.scrollLeft];
  assert.doesNotThrow(() => { oldButton.handlers.click(); removedButton.handlers.click(); });
  assert.deepEqual([lookupSelected.length, lookupOpened.length, element.scrollLeft], actionsAfterUpdate,
    "Detached buttons cannot open, select, or navigate after update, even when an ID is reused");
  nodes.push(oldButton);
  oldButton.handlers.click();
  nodes.pop();
  assert.deepEqual([lookupSelected.length, lookupOpened.length, element.scrollLeft], actionsAfterUpdate,
    "Reattaching a prior button does not make its old handler valid");
  element.scrollLeft = 500;
  lookupScene.seek(next.length - 1);
  oldButton.handlers.click();
  frame(20032);
  assert.ok(element.scrollLeft < 500, "An old click cannot cancel an in-progress navigation");
  lookupScene.select("new-event");
  assert.ok(nodes.find(node => node.dataset.event === "lookup-1").attributes["aria-label"].includes("Updated person"),
    "An unselected event uses the updated representative, not the previous scene's reference");
  assert.equal(oldParent.writes, oldWrites, "An update does not touch detached parents");
  lookupScene.select("lookup-0");
  assert.equal(nodes.filter(node => node.attributes["aria-pressed"] === "true").length, 0,
    "A removed event cannot select a current button");
  const beforeRenderButton = nodes.find(node => node.dataset.event === "lookup-1");
  lookupScene.render(many.slice(0, 2), "lookup-0");
  const actionsAfterRender = [lookupSelected.length, lookupOpened.length, element.scrollLeft];
  beforeRenderButton.handlers.click();
  assert.deepEqual([lookupSelected.length, lookupOpened.length, element.scrollLeft], actionsAfterRender,
    "A prior button with a reused ID cannot act on a freshly rendered scene");
  assert.equal(nodes.find(node => node.dataset.event === "lookup-0").attributes["aria-pressed"], "true",
    "A fresh render reacquires an event removed by the prior update");
  assert.ok(nodes.find(node => node.dataset.event === "lookup-1").attributes["aria-label"].includes("Person 1"),
    "A fresh render replaces the unselected representative for a reused ID");
  const beforeClearButton = nodes[0];
  lookupScene.clear();
  const clearedParent = nodes[0].parent, clearedWrites = clearedParent.writes;
  assert.doesNotThrow(() => beforeClearButton.handlers.click(), "A cleared scene rejects old clicks");
  lookupScene.select("lookup-0");
  assert.equal(clearedParent.writes, clearedWrites, "Clear releases scene-owned button references");
  lookupScene.render([], null);
  lookupScene.select("lookup-0");
  assert.equal(nodes.length, 0, "An empty scene cannot select an old event");
  lookupScene.render(many.slice(0, 2), "lookup-1");
  assert.equal(nodes.find(node => node.dataset.event === "lookup-1").attributes["aria-pressed"], "true");

  const activity = {key:"activity",enabled:true,label:"Activity",buckets:[
    {key:"follow.follow",label:"Followed",tone:"positive"},
    {key:"follow.unfollow",label:"Unfollowed",tone:"negative"},
    {key:"unknown",label:"Unknown",tone:"neutral"},
  ]};
  const firstRecord = {...event("duplicate", "A", 3, "follow.follow"), name:"Current record", audience_groups:{activity:"follow.follow"}};
  const otherGroupRecord = {...event("duplicate", "B", 2, "follow.unfollow"), name:"First geometry record", audience_groups:{activity:"follow.unfollow"}};
  const otherRecord = {...event("other", "C", 1, "follow.follow"), name:"Other record", audience_groups:{activity:"follow.follow"}};
  lookupScene.configure([activity], "activity");
  lookupScene.render([firstRecord, otherGroupRecord, otherRecord], "other");
  const duplicates = nodes.filter(node => node.dataset.event === "duplicate");
  assert.equal(duplicates.length, 2, "A duplicate ID in separate groups keeps both stars");
  assert.ok(duplicates.every(node => node.attributes["aria-label"].includes("First geometry record")),
    "Unselected duplicate IDs retain the first geometry match");
  duplicates[1].handlers.click();
  assert.equal(lookupSelected.at(-1), "duplicate", "A duplicate click selects the first matching event");
  lookupScene.select("duplicate");
  assert.ok(duplicates.every(node => node.attributes["aria-pressed"] === "true" &&
    node.attributes["aria-label"].includes("Current record")),
    "Selected duplicate IDs retain the first current event");
  const opensBeforeDuplicateClick = lookupOpened.length;
  duplicates[1].handlers.click();
  assert.equal(lookupOpened.length, opensBeforeDuplicateClick + 1,
    "Either duplicate button acts on the first matching geometry person");
  assert.equal(lookupOpened.at(-1), "duplicate");
  const duplicateLabels = labels.filter(node => node.dataset.label === "duplicate");
  lookupScene.setZoom(1.5);
  assert.notEqual(duplicates[0].style.left, duplicates[1].style.left, "Duplicate entries keep separate coordinates");
  const opensBeforeLabels = lookupOpened.length;
  duplicateLabels.forEach(node => node.handlers.click());
  assert.deepEqual(lookupOpened.slice(opensBeforeLabels), ["duplicate", "duplicate"],
    "Either retained label opens the selected duplicate event using first-match identity");
  const destroyedParent = duplicates[0].parent, destroyedWrites = destroyedParent.writes;
  lookupScene.destroy();
  assert.doesNotThrow(() => duplicates[0].handlers.click(), "A destroyed scene rejects old clicks");
  lookupScene.select("other");
  assert.equal(destroyedParent.writes, destroyedWrites, "Destroy releases scene-owned button references");
  assert.equal(pending.size, 0, "Selection after destroy cannot schedule a frame");
  const recreated = createConstellation({
    element, root, escape: String, label: (item) => item.kind, initials: (item) => item.actor_id,
    onSelect() {}, onOpen() {},
  });
  recreated.render([otherRecord], "other");
  assert.equal(nodes[0].attributes["aria-pressed"], "true", "A new scene selects normally after destroy");
  const recreatedActions = [lookupSelected.length, lookupOpened.length, element.scrollLeft];
  duplicates[0].handlers.click();
  assert.deepEqual([lookupSelected.length, lookupOpened.length, element.scrollLeft], recreatedActions,
    "A destroyed scene's button cannot act on a recreated scene");
  recreated.destroy();
} finally {
  Array.prototype.find = nativeFind;
}

// Reconstruct the original per-group filter oracle from the actual layout output.
const connectionScene = createConstellation({
  element, root, escape: String, label: item => item.kind, initials: item => item.actor_id,
  onSelect() {}, onOpen() {},
});
const activity = {key:"activity", enabled:true, buckets:[
  {key:"follow.follow",label:"Followed",tone:"positive"},
  {key:"follow.unfollow",label:"Unfollowed",tone:"negative"},
  {key:"interaction.replies",label:"Replies",tone:"neutral"},
  {key:"unknown",label:"Unknown",tone:"neutral"},
]};
const location = {key:"profile-location", enabled:true, dynamic_buckets:true,
  buckets:[{key:"unknown",label:"Unknown",tone:"neutral"}]};
// Invalid non-string keys are unsupported, but must retain the old strict comparison behavior.
const invalid = {key:"invalid", enabled:true, buckets:[
  {key:NaN,label:"Invalid",tone:"neutral",color:"red"},
  {key:"unknown",label:"Unknown",tone:"neutral"},
]};
const connectionEvents = Array.from({length: 18}, (_, index) => {
  const key = ["follow.follow", "follow.unfollow", "interaction.replies", "missing"][index % 4];
  const city = index % 5 ? `city-${index % 7}` : "missing";
  return {...event(`connection-${index}`, `actor-${index % 3}`, 18 - index, key),
    audience_groups:{activity:key, "profile-location":city},
    audience_group_buckets:{"profile-location":city === "missing" ? undefined : {key:city,label:`City ${city}`}}};
});
const crossGroupDuplicate = {...connectionEvents[0],
  audience_groups:{activity:"follow.unfollow", "profile-location":"city-1"},
  audience_group_buckets:{"profile-location":{key:"city-1",label:"City city-1"}}};
const skewedConnections = connectionEvents.map((item, index) => ({...item,
  audience_groups:{...item.audience_groups, activity:index < 15 ? "follow.follow" :
    ["follow.unfollow", "interaction.replies", "missing"][index - 15]}}));
const oneGroup = connectionEvents.map(item => ({...item,
  audience_groups:{...item.audience_groups, activity:"follow.follow"}}));
const largeGroup = Array.from({length: 1000}, (_, index) => ({
  ...oneGroup[index % oneGroup.length], event_id:`large-${index}`,
}));
function expectedConnections(records, modules, lens, zoom) {
  const layout = constellationLayout({events:records,width:element.clientWidth,height:element.clientHeight,zoom,modules,lens});
  const links = layout.groups.flatMap(group => {
    const members = layout.people.filter(person => person.group === group.key);
    return members.slice(1).map((person, index) => ({a:person,b:members[index],color:group.color,dash:group.dash}));
  });
  assert.ok(links.every(link => link.a.group === link.b.group), "Connections stay inside their group");
  return {layout, links};
}
function verifyConnections(records, modules, lens, zoom) {
  connectionScene.clear();
  connectionScene.configure(modules, lens);
  connectionScene.render(records, records[0]?.event_id || null);
  if (records.length) connectionScene.setZoom(zoom);
  const expected = expectedConnections(records, modules, lens, zoom);
  const visible = expected.layout.overview ? [] : expected.links;
  assert.deepEqual(expected.layout.overview ? [] : renderedLinks, visible.map(({a,b,color,dash}) => ({
    group:a.group, style:color ? `color:${color}` : "", d:`M${a.x},${a.y}L${b.x},${b.y}`, dash:dash || "",
  })), "Rendered paths preserve group order, endpoints, direction, colors and dashes");
  assert.equal(sceneParts[".constellation-links"].style.visibility, expected.layout.overview ? "hidden" : "");
  if (!expected.layout.overview) {
    assert.equal(renderedSparks.length, visible.length, "Each visible connection has one spark");
    assert.equal(renderedTrails.length, visible.length, "Each visible connection has one trail");
  }
  return expected;
}
try {
  for (const [records, modules, lens] of [
    [[], [], "none"], [[connectionEvents[0]], [], "none"],
    [connectionEvents, [], "none"], [connectionEvents.slice(0, 1), [activity], "activity"],
    [oneGroup, [activity], "activity"], [largeGroup, [activity], "activity"],
    [connectionEvents, [activity], "activity"],
    [skewedConnections, [activity], "activity"],
    [[...connectionEvents, crossGroupDuplicate], [activity], "activity"],
    [connectionEvents, [location], "profile-location"],
  ]) verifyConnections(records, modules, lens, 0.8);
  const invalidRecords = connectionEvents.slice(0, 2).map(item => ({...item, audience_groups:{invalid:NaN}}));
  verifyConnections(invalidRecords, [invalid], "invalid", 0.8);
  assert.equal(renderedLinks.length, 0, "NaN group keys do not match under the old strict comparison");
  verifyConnections(invalidRecords, [invalid], "invalid", 0);
  const mixedInvalid = [...invalidRecords, ...connectionEvents.slice(2, 4).map(item => ({
    ...item, audience_groups:{invalid:"unknown"},
  }))];
  verifyConnections(mixedInvalid, [invalid], "invalid", 0.8);
  assert.equal(renderedLinks.length, 1, "The indexed path excludes NaN while connecting valid groups");

  const {links: animatedLinks} = verifyConnections(connectionEvents, [activity], "activity", 1);
  assert.ok(animatedLinks.length > 2, "The animation fixture has multiple indexed links");
  frame(30000);
  const inRange = ({a,b}) => Math.max(a.x, b.x) >= element.scrollLeft - 128 &&
    Math.min(a.x, b.x) <= element.scrollLeft + element.clientWidth + 128;
  assert.ok(animatedLinks.some(inRange) && animatedLinks.some(link => !inRange(link)));
  animatedLinks.forEach(({a,b}, index) => {
    if (!inRange({a,b})) {
      assert.equal(renderedSparks[index].attributes.cx, undefined);
      return;
    }
    const part = seed(index) % 1, tail = Math.max(0, part - 0.06);
    assert.equal(renderedSparks[index].attributes.cx, (a.x + (b.x - a.x) * part).toFixed(2));
    assert.equal(renderedSparks[index].attributes.cy, (a.y + (b.y - a.y) * part).toFixed(2));
    assert.equal(renderedTrails[index].attributes.x1, (a.x + (b.x - a.x) * tail).toFixed(2));
    assert.equal(renderedTrails[index].attributes.y1, (a.y + (b.y - a.y) * tail).toFixed(2));
    assert.equal(renderedTrails[index].attributes.x2, (a.x + (b.x - a.x) * part).toFixed(2));
    assert.equal(renderedTrails[index].attributes.y2, (a.y + (b.y - a.y) * part).toFixed(2));
  });
  const oldTrails = renderedTrails, oldTrailAttributes = oldTrails.map(trail => ({...trail.attributes}));
  const oldSparks = renderedSparks, oldSparkAttributes = oldSparks.map(spark => ({...spark.attributes}));
  const oldTrailWrites = oldTrails.map(trail => trail.attributeWrites);
  const oldSparkWrites = oldSparks.map(spark => spark.attributeWrites);
  connectionScene.setZoom(0);
  assert.equal(sceneParts[".constellation-links"].style.visibility, "hidden", "Overview hides the connection layer");
  assert.equal(renderedSparks, oldSparks, "Overview retains the spark nodes");
  assert.equal(renderedTrails, oldTrails, "Overview retains the trail nodes");
  frame(30016);
  assert.deepEqual(oldTrails.map(trail => trail.attributes), oldTrailAttributes, "Overview cannot update old trails");
  assert.deepEqual(oldSparks.map(spark => spark.attributes), oldSparkAttributes, "Overview cannot update old sparks");
  assert.deepEqual(oldTrails.map(trail => trail.attributeWrites), oldTrailWrites, "Overview never writes to old trails");
  assert.deepEqual(oldSparks.map(spark => spark.attributeWrites), oldSparkWrites, "Overview never writes to old sparks");
  connectionScene.setZoom(1);
  const expanded = expectedConnections(connectionEvents, [activity], "activity", 1);
  assert.deepEqual(renderedLinks, expanded.links.map(({a,b,color,dash}) => ({
    group:a.group, style:color ? `color:${color}` : "", d:`M${a.x},${a.y}L${b.x},${b.y}`, dash:dash || "",
  })), "Leaving overview restores the exact ordered connections and styles");
  frame(30032);
  expanded.links.forEach(({a,b}, index) => {
    if (!inRange({a,b})) return;
    assert.notEqual(renderedTrails[index].attributes.x1, undefined, "Active retained trails animate");
    const part = (seed(index) + 32 / 10000) % 1;
    assert.equal(renderedSparks[index].attributes.cx, (a.x + (b.x - a.x) * part).toFixed(2));
    assert.equal(renderedSparks[index].attributes.cy, (a.y + (b.y - a.y) * part).toFixed(2));
  });
  const priorTrails = renderedTrails, priorAttributes = priorTrails.map(trail => ({...trail.attributes}));
  connectionScene.update(connectionEvents.slice(0, 9), connectionEvents[0].event_id);
  frame(30048);
  assert.deepEqual(priorTrails.map(trail => trail.attributes), priorAttributes, "Updates cannot animate stale trails");
  const replacement = expectedConnections(connectionEvents.slice(0, 9), [activity], "activity", 1);
  assert.deepEqual(renderedLinks, replacement.links.map(({a,b,color,dash}) => ({
    group:a.group, style:color ? `color:${color}` : "", d:`M${a.x},${a.y}L${b.x},${b.y}`, dash:dash || "",
  })), "Update rebuilds the exact ordered connections");
  connectionScene.clear();
  assert.equal(pending.size, 0, "Clear cancels connection animation");
} finally {
  connectionScene.destroy();
}

// Count positioned-point for-of/filter passes and link-shaped outputs around markup replacement.
// The post-markup for-of pass builds the separate event-to-person selection lookup.
function measurePreparation(action) {
  const NativeMap = globalThis.Map, nativePush = Array.prototype.push;
  const nativeIterator = Array.prototype[Symbol.iterator], nativeMap = Array.prototype.map;
  const nativeFilter = Array.prototype.filter;
  const counts = {groupIndexes:0, preMarkupForOf:0, postMarkupForOf:0, preMarkupFilters:0, linkObjects:0};
  const isLink = item => item && typeof item === "object" &&
    item.a?.event && item.b?.event && "group" in item.a && "group" in item.b &&
    "color" in item && "dash" in item && !("trail" in item);
  globalThis.Map = class extends NativeMap {
    constructor(entries) {
      super(entries);
      if (measureRenderWork && Array.isArray(entries) && entries.length &&
          entries.every(entry => Array.isArray(entry) && Array.isArray(entry[1]) && !entry[1].length))
        counts.groupIndexes++;
    }
  };
  Array.prototype[Symbol.iterator] = function() {
    if (measureRenderWork && this.length && this[0]?.event && Array.isArray(this[0]?.events) &&
        "group" in this[0] && "x" in this[0])
      counts[beforeMarkup ? "preMarkupForOf" : "postMarkupForOf"]++;
    return nativeIterator.call(this);
  };
  Array.prototype.push = function(...items) {
    if (measureRenderWork) counts.linkObjects += nativeFilter.call(items, isLink).length;
    return nativePush.apply(this, items);
  };
  Array.prototype.map = function(...args) {
    const result = nativeMap.apply(this, args);
    if (measureRenderWork) counts.linkObjects += nativeFilter.call(result, isLink).length;
    return result;
  };
  Array.prototype.filter = function(...args) {
    if (beforeMarkup && this.length && this[0]?.event && Array.isArray(this[0]?.events) &&
        "group" in this[0] && "x" in this[0]) counts.preMarkupFilters++;
    return nativeFilter.apply(this, args);
  };
  try {
    beforeMarkup = measureRenderWork = true;
    action();
    return counts;
  } finally {
    beforeMarkup = measureRenderWork = false;
    globalThis.Map = NativeMap;
    Array.prototype.push = nativePush;
    Array.prototype.map = nativeMap;
    Array.prototype.filter = nativeFilter;
    Array.prototype[Symbol.iterator] = nativeIterator;
  }
}
const point = {event:{},events:[],group:"all",x:0};
assert.deepEqual(measurePreparation(() => {
  new Map([["all", []]]);
  for (const person of [point]) { void person; }
  [].push({a:point,b:point,color:"red",dash:""});
  [point].map(person => ({a:person,b:person,color:"red",dash:""}));
  [point].filter(() => true);
  [].push({a:"unrelated",b:"event",color:"red",dash:""});
}), {groupIndexes:1,preMarkupForOf:1,postMarkupForOf:0,preMarkupFilters:1,linkObjects:2}, "Structural counters have positive controls");
const preparationScene = createConstellation({
  element, root, escape:String, label:item => item.kind, initials:item => item.actor_id,
  onSelect() {}, onOpen() {},
});
try {
  let membershipReads = 0;
  const observedEvents = connectionEvents.map(event => ({
    ...event,
    get audience_groups() { membershipReads++; return event.audience_groups; },
  }));
  preparationScene.configure([activity], "activity");
  assert.deepEqual(measurePreparation(() => preparationScene.render(observedEvents, observedEvents[0].event_id)),
    {groupIndexes:1,preMarkupForOf:0,postMarkupForOf:2,preMarkupFilters:0,linkObjects:14},
    "Structural render builds the selection lookup and indexed connections");
  const originalNodes = nodes, originalLabels = labels, originalParts = sceneParts;
  const originalPaths = sceneParts[".constellation-links"].pathNodes;
  const before = [historyWrites, linkWrites, groupWrites, listenerWrites];
  assert.ok(membershipReads > 0, "Structural rendering reads group membership");
  membershipReads = 0;
  for (const zoom of [1, 1.5, 2, 0.3]) {
    assert.deepEqual(measurePreparation(() => preparationScene.setZoom(zoom)),
      {groupIndexes:0,preMarkupForOf:0,postMarkupForOf:0,preMarkupFilters:0,linkObjects:0},
      "Ordinary zoom does not prepare connection topology or rebuild the selection lookup");
    const expected = expectedConnections(connectionEvents, [activity], "activity", zoom);
    assert.deepEqual(nodes.map(node => parseFloat(node.style.left)), expected.layout.people.map(point => point.x));
    assert.deepEqual(renderedLinks.map(link => link.d), expected.links.map(({a,b}) => `M${a.x},${a.y}L${b.x},${b.y}`));
  }
  assert.deepEqual([historyWrites, linkWrites, groupWrites, listenerWrites], before);
  preparationScene.setZoom(0);
  const firstGroupNodes = groupNodes;
  const afterFirstOverview = [historyWrites, linkWrites, groupWrites, listenerWrites];
  assert.equal(groupWrites, before[2] + 1, "Only the overview layer is created on its first visit");
  for (const zoom of [0.25, 0.3, 0.05, 0.8]) preparationScene.setZoom(zoom);
  assert.deepEqual([historyWrites, linkWrites, groupWrites, listenerWrites], afterFirstOverview);
  assert.equal(membershipReads, 0, "Repeated zoom does not regroup the events");
  assert.equal(nodes, originalNodes);
  assert.equal(labels, originalLabels);
  assert.equal(sceneParts, originalParts);
  assert.equal(sceneParts[".constellation-links"].pathNodes, originalPaths);
  assert.equal(groupNodes, firstGroupNodes);
  preparationScene.setZoom(0);
  groupNodes[0].handlers.click();
  assert.equal(Number(controls.get("#scene-zoom").value), 1, "Overview cluster opens without rebuilding");
  assert.equal(nodes, originalNodes);
  preparationScene.setZoom(0);
  const beforeOverviewRebuild = linkWrites;
  preparationScene.render(observedEvents, observedEvents[0].event_id);
  assert.equal(linkWrites, beforeOverviewRebuild, "An overview rebuild defers connection preparation");
  preparationScene.setZoom(1);
  assert.equal(linkWrites, beforeOverviewRebuild + 1, "First expansion builds only the missing links");

  const priorNodes = nodes;
  assert.deepEqual(measurePreparation(() => preparationScene.update(oneGroup, oneGroup[0].event_id)),
    {groupIndexes:0,preMarkupForOf:0,postMarkupForOf:2,preMarkupFilters:0,linkObjects:17},
    "Replacing data rebuilds single-group connections without an index");
  assert.notEqual(nodes, priorNodes);
  preparationScene.configure([], "none");
  assert.deepEqual(measurePreparation(() => preparationScene.render([], null)),
    {groupIndexes:0,preMarkupForOf:0,postMarkupForOf:0,preMarkupFilters:0,linkObjects:0}, "Empty history produces no connection work");
  const region = {...location, buckets:[{key:"unknown",label:"Unknown"}]};
  const overviewEvents = connectionEvents.slice(0, 2).map(item => ({
    ...item,
    audience_groups:{"profile-location":"overview"},
    audience_group_buckets:{"profile-location":{key:"overview",label:"Overview City"}},
  }));
  preparationScene.configure([region], "profile-location");
  preparationScene.render(overviewEvents, overviewEvents[0].event_id);
  const groupKey = controls.get("#constellation-key");
  preparationScene.setZoom(0.25);
  assert.match(groupKey.innerHTML, /All constellations/);
  preparationScene.setZoom(0.3);
  assert.match(groupKey.innerHTML, /Overview City/, "A group key cannot collide with the overview mode");
} finally {
  preparationScene.destroy();
}

// Count only full-array scans of positioned points, with a positive control.
const nativeFilter = Array.prototype.filter;
let geometryScans = 0;
Array.prototype.filter = function(predicate, ...args) {
  if (this.length && this[0]?.event && Array.isArray(this[0]?.events) && "group" in this[0] && "x" in this[0])
    geometryScans++;
  return nativeFilter.call(this, predicate, ...args);
};
try {
  [{event:{},events:[],group:"all",x:0}].filter(() => true);
  assert.equal(geometryScans, 1, "The scan counter detects positioned-point filters");
  const countedScene = createConstellation({
    element, root, escape:String, label:item => item.kind, initials:item => item.actor_id,
    onSelect() {}, onOpen() {},
  });
  countedScene.configure([activity], "activity");
  geometryScans = 0;
  countedScene.render(connectionEvents, connectionEvents[0].event_id);
  assert.equal(geometryScans, 0, "Rendering no longer scans all points once per group");
  countedScene.destroy();
} finally {
  Array.prototype.filter = nativeFilter;
}
// Collision candidate sorting and label DOM writes identify actual viewport work.
const nativeSort = Array.prototype.sort;
const near = {id: Symbol("test"), top: 0, distance: 0};
const far = {...near, distance: 1};
Array.prototype.sort = function(compare) {
  // The initial candidate sort uses distance. Neighbor sorts use vertical position.
  if ((!this.length || (this[0]?.id?.event && "minTop" in this[0])) && compare?.(near, far) === -1)
    collisionPasses++;
  return nativeSort.call(this, compare);
};
const viewportScene = createConstellation({
  element, root, escape:String, label:item => item.kind, initials:item => item.actor_id,
  onSelect() {}, onOpen() {},
});
try {
  root.dataset.motion = "on";
  viewportScene.render([withPreview, ...events], "preview");
  frame(40000);
  assert.ok(collisionPasses > 0 && labelReads > 0 && previewReads > 0 && navigationWrites > 0,
    "The work counters see initial layout, preview measurement and navigation");
  const labelWrites = () => labels.reduce((sum, item) => sum + item.attributeWrites, 0);
  const work = () => ({collisionPasses, labelReads, previewReads, navigationWrites, labelWrites:labelWrites()});
  const spark = renderedSparks[0];
  const sparkBefore = spark.attributes.cx;
  const idle = work();
  frame(40016);
  frame(40032);
  frame(40048);
  assert.deepEqual(work(), idle, "Ambient-only frames skip all state-driven work");
  assert.notEqual(spark.attributes.cx, sparkBefore, "The ambient clock and spark keep advancing");

  element.scrollLeft = 0;
  frame(40050);
  const beforeDelayedScroll = collisionPasses;
  handlers.scroll();
  frame(40052);
  const leftmost = nodes.reduce((a, b) => parseFloat(a.style.left) < parseFloat(b.style.left) ? a : b);
  assert.equal(leftmost.attributes["aria-pressed"], "true",
    "A scroll event arriving after paint still centers the selection");
  assert.equal(collisionPasses, beforeDelayedScroll + 1, "The new selection invalidates layout at the same offset");
  viewportScene.seek(0, "instant");
  frame(40056);

  const previousLeft = element.scrollLeft;
  viewportScene.seek(1);
  const afterSelect = work();
  frame(40064);
  assert.notEqual(element.scrollLeft, previousLeft, "Smooth navigation advances the viewport");
  assert.equal(collisionPasses, afterSelect.collisionPasses + 1, "One collision pass for a changed viewport");
  assert.equal(labelReads - afterSelect.labelReads, 2, "Only the previous and new selection need measurement");
  const afterScroll = work();
  frame(40080);
  assert.equal(collisionPasses, afterScroll.collisionPasses + 1, "Easing keeps layout current");
  assert.equal(labelReads, afterScroll.labelReads, "Scrolling reuses dimensions");
  assert.equal(Number(controls.get("#memory-scrubber").value),
    Math.round((1 - element.scrollLeft / 500) * 1000), "Scrubber tracks the actual eased position");

  root.dataset.motion = "off";
  frame(40096);
  assert.equal(pending.size, 0, "Paused motion settles after the final scroll step");
  const frozen = spark.attributeWrites;
  const stopped = work();
  element.scrollLeft = element.scrollLeft ? 0 : 500;
  handlers.scroll();
  frame(40112);
  assert.equal(collisionPasses, stopped.collisionPasses + 1, "A native scroll still updates paused labels");
  assert.equal(spark.attributeWrites, frozen, "A scroll-only paused frame does not rewrite frozen sparks");
  assert.equal(pending.size, 0);
  viewportScene.setZoom(0.9);
  frame(40128);
  assert.ok(spark.attributeWrites > frozen, "Paused sparks still rebind to changed geometry");

  const groupedEvents = [withPreview, ...events].map(item => ({
    ...item, audience_groups: {activity: item.kind},
  }));
  viewportScene.configure([activity], "activity");
  viewportScene.setZoom(0);
  viewportScene.render(groupedEvents, "preview");
  const overviewLabels = labels;
  const labelWork = () => [collisionPasses, labelReads, previewReads, labelWrites()];
  const beforeOverview = labelWork();
  frame(40144);
  assert.deepEqual(labelWork(), beforeOverview, "A fresh overview frame skips label layout");
  const assertOverviewHidden = () => {
    assert.ok(labels.every(item => item.style.visibility === "hidden" &&
      item.attributes["aria-hidden"] === "true" && item.identityControl.tabIndex === -1 &&
      (!item.previewControl || item.previewControl.tabIndex === -1)));
  };
  assertOverviewHidden();
  for (const [index, zoom] of [0.05, 0.25, 0].entries()) {
    viewportScene.setZoom(zoom);
    frame(40160 + index * 16);
  }
  assert.deepEqual(labelWork(), beforeOverview, "Overview zoom does no label reads, collision passes or visibility writes");
  assert.ok(labels.every(item => item.style.left === undefined && item.style.top === undefined),
    "Overview zoom leaves fresh labels unpositioned");

  const scrollWidth = element.scrollWidth;
  element.scrollWidth = element.clientWidth;
  viewportScene.setZoom(0.3);
  assertOverviewHidden();
  frame(40208);
  element.scrollWidth = scrollWidth;
  assert.equal(collisionPasses, beforeOverview[0] + 1, "Expansion runs collision layout");
  assert.equal(labelReads - beforeOverview[1], labels.length, "First expansion measures cold labels");
  assert.equal(previewReads - beforeOverview[2], 1, "First expansion measures the selected preview");
  const selectedLabel = labels.find(item => item.dataset.label === "preview");
  assert.equal(selectedLabel.style.visibility, "visible");
  assert.equal(selectedLabel.attributes["aria-hidden"], "false");
  assert.equal(selectedLabel.identityControl.tabIndex, 0);
  assert.equal(selectedLabel.previewControl.tabIndex, 0);

  const measured = [labelReads, previewReads];
  viewportScene.setZoom(0.25);
  frame(40224);
  assertOverviewHidden();
  viewportScene.setZoom(0.4);
  frame(40240);
  assert.equal(labels, overviewLabels, "Repeated transitions preserve the label nodes");
  assert.deepEqual([labelReads, previewReads], measured, "Expansion reuses still-valid dimensions");
  assert.equal(selectedLabel.attributes["aria-hidden"], "false");
  assert.equal(pending.size, 0, "Paused expansion settles after one frame");

  viewportScene.setZoom(0.25);
  viewportScene.select("new-A");
  frame(40256);
  assertOverviewHidden();
  assert.deepEqual([labelReads, previewReads], measured, "Selection in overview defers invalidated sizes");
  element.scrollLeft = 100;
  handlers.scroll();
  const beforeScroll = labelWork();
  frame(40272);
  assert.deepEqual(labelWork(), beforeScroll, "Overview scrolling still skips timeline label work");
  assert.equal(Number(controls.get("#memory-scrubber").value), 800, "The scrubber tracks the overview offset");

  viewportScene.setZoom(0.4);
  frame(40288);
  assert.equal(labelReads - measured[0], 2, "Expansion measures only labels affected by the selection change");
  const newlySelectedLabel = labels.find(item => item.dataset.label === "new-A");
  assert.equal(newlySelectedLabel.attributes["aria-hidden"], "false");
  assert.equal(newlySelectedLabel.identityControl.tabIndex, 0);
} finally {
  viewportScene.destroy();
  Array.prototype.sort = nativeSort;
}
console.log(
  JSON.stringify({
    script: new URL(import.meta.url).pathname,
    selectedRecordOpenedByLabelAndStar: true,
    personCountCorrect: true,
  }),
);
