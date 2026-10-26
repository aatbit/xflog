import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { createStrandLife, normalizeTwistSpeed, visibleMemoryLabels } = await import(pathToFileURL(process.argv[2]));

function exercise(refreshRate, speed = 1, duration = 1000) {
  const pending = new Map();
  let nextId = 0,
    writes = 0,
    observer,
    motionOff = false;
  const near = {
    value: "",
    setAttribute(_name, value) {
      this.value = value;
      writes++;
    },
  };
  const far = { setAttribute() {} };
  const rungs = { setAttribute() {} };
  globalThis.requestAnimationFrame = (callback) => {
    pending.set(++nextId, callback);
    return nextId;
  };
  globalThis.cancelAnimationFrame = (id) => pending.delete(id);
  globalThis.document = {
    hidden: false,
    addEventListener() {},
    removeEventListener() {},
  };
  globalThis.MutationObserver = class {
    constructor(callback) {
      this.callback = callback;
      observer = this;
    }
    observe() {}
    disconnect() {
      this.disconnected = true;
    }
  };
  const root = { isConnected: true, dataset: { route: "timeline", twistSpeed: String(speed) } };
  const element = {
    scrollLeft: 0,
    clientWidth: 800,
    dataset: {},
    querySelectorAll(selector) {
      if (selector.includes('data-lane="1"')) return [];
      if (selector.startsWith(".thread-near")) return [near];
      if (selector.startsWith(".thread-far")) return [far];
      return [];
    },
    querySelector() {
      return rungs;
    },
  };
  const geometry = {
    width: 800,
    spacing: 360,
    center: 280,
    amplitude: 95,
    padding: 400,
    points: [],
    compact: false,
    canPan: false,
  };
  const life = createStrandLife({ element, root, noMotion: () => motionOff });
  const frame = (time) => {
    assert.equal(pending.size, 1);
    const [id, callback] = pending.entries().next().value;
    pending.delete(id);
    callback(time);
  };
  life.mount(geometry);
  const frames = refreshRate * duration / 1000;
  for (let index = 0; index <= frames; index++)
    frame(1000 + (index * 1000) / refreshRate);
  assert.equal(
    writes,
    frames + 2,
    "Every display frame must paint; no fixed FPS cap.",
  );
  const finalPath = near.value;
  root.dataset.twistSpeed = "2";
  frame(1000 + duration);
  assert.equal(near.value, finalPath, "Changing speed must preserve the current phase.");
  root.dataset.route = "profile";
  observer.callback();
  assert.equal(pending.size, 0);
  root.dataset.route = "timeline";
  observer.callback();
  frame(100000);
  assert.equal(
    near.value,
    finalPath,
    "Returning from Profile must resume without a jump.",
  );
  assert.equal(element.dataset.living, "running");
  motionOff = true;
  life.refresh();
  assert.equal(pending.size, 0);
  motionOff = false;
  life.refresh();
  assert.equal(pending.size, 1);
  life.destroy();
  assert.equal(pending.size, 0);
  assert.equal(observer.disconnected, true);
  return finalPath;
}
assert.equal(
  exercise(60),
  exercise(120),
  "Refresh rate must not change rotation speed.",
);
assert.equal(
  exercise(60),
  exercise(144),
  "144Hz must retain the same elapsed-time speed.",
);
assert.equal(exercise(60, 2), exercise(60, 1, 2000), "Double speed must cover twice the rotation.");
assert.equal(normalizeTwistSpeed("invalid"), 1);
assert.equal(normalizeTwistSpeed(-1), 0.25);
assert.equal(normalizeTwistSpeed(20), 2);

function labels(width, spacing) {
  const size = spacing < 168 ? 128 : 216;
  const candidates = Array.from({length: 25}, (_, index) => {
    const x = width / 2 + (index - 12) * spacing;
    const w = index === 12 ? 216 : size;
    const top = index % 2 ? 180 : 0;
    return {index, left:x-w/2, right:x+w/2, top, bottom:top+120, distance:Math.abs(x-width/2)};
  }).filter(c => c.left >= 16 && c.right <= width-16);
  const shown = visibleMemoryLabels(candidates, 12);
  assert.ok(shown.has(12), "The selected person must remain visible.");
  const boxes = candidates.filter(c => shown.has(c.index));
  boxes.forEach((a, i) => boxes.slice(i+1).forEach(b => {
    assert.ok(a.right+12 <= b.left || b.right+12 <= a.left || a.bottom+12 <= b.top || b.bottom+12 <= a.top, "Visible labels must not overlap.");
  }));
  assert.deepEqual(visibleMemoryLabels(candidates, 12, shown), shown, "Stable layouts must not flicker between labels.");
  return shown.size;
}
for (const width of [375, 768, 1440]) for (const spacing of [20, 40, 80, 180, 360]) labels(width, spacing);
assert.ok(labels(1440, 80) > labels(1440, 360), "Zooming out must reveal more people when they fit.");
assert.ok(labels(1440, 80) > labels(375, 80), "A larger viewport must accommodate more people.");
