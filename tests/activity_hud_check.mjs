import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { createActivityHud, formatReading, formatChange } = await import(
  new URL("activity-hud.js", pathToFileURL(process.argv[2] + "/"))
);

assert.equal(formatReading("ratio", null), "—");
assert.equal(formatReading("ratio", 2.5), "2.5:1");
assert.equal(formatReading("gain_rate", 0.001), "<0.01");
assert.equal(formatReading("gained", 9999), "9,999");
assert.equal(formatReading("gained", 12000), "12K");
assert.equal(formatReading("gain_rate", 12000), "12K");
assert.equal(formatReading("ratio", 1200000), "1.2M:1");
for (const [key, percent, tone] of [
  ["gained", 20, "good"],
  ["gained", -20, "bad"],
  ["lost", 20, "bad"],
  ["lost", -20, "good"],
  ["loss_rate", -20, "good"],
  ["ratio", 20, "good"],
  ["gain_rate", 0, "neutral"],
])
  assert.equal(formatChange(key, { change_percent: percent }).tone, tone);
assert.deepEqual(
  formatChange("lost", { comparison: "new", change_percent: null }),
  { text: "↑ New", tone: "bad" },
);
assert.deepEqual(
  formatChange("ratio", { comparison: "unavailable", change_percent: null }),
  { text: "—", tone: "neutral" },
);
assert.equal(formatChange("gained", { change_percent: 0.005 }).text, "↑ <0.1%");

class Node extends EventTarget {
  children = [];
  dataset = {};
  attributes = {};
  textContent = "";
  hidden = false;
  setAttribute(key, value) {
    this.attributes[key] = value;
  }
  removeAttribute(key) {
    delete this.attributes[key];
  }
  append(...children) {
    this.children.push(...children);
  }
  replaceChildren(...children) {
    this.children = children;
  }
  querySelectorAll() {
    return this.children;
  }
  hidePopover() {}
  focus() {}
}
globalThis.window = new EventTarget();
globalThis.document = { createElement: () => new Node() };
const nodes = new Map(
  [
    "activity-hud",
    "activity-period-trigger",
    "activity-periods",
    "activity-readings",
    "activity-period-value",
    "activity-error",
  ].map((id) => ["#" + id, new Node()]),
);
const requests = [];
let mode = { demo: false, subject: "followers" };
const hud = createActivityHud({
  root: { querySelector: (selector) => nodes.get(selector) },
  context: () => mode,
  api: (url) =>
    new Promise((resolve, reject) => requests.push({ url, resolve, reject })),
});
const result = (value) => ({
  periods: ["1h", "6h", "12h", "24h", "3d", "7d", "30d", "90d"],
  start: "2026-10-25T12:00:00Z",
  end: "2026-10-26T12:00:00Z",
  metrics: Object.fromEntries(
    ["gained", "lost", "gain_rate", "loss_rate", "ratio"].map((key) => [
      key,
      { value, previous: 1, change_percent: 100, comparison: "percent" },
    ]),
  ),
});
const gains = () =>
  nodes.get("#activity-readings").children[0].children[1].textContent;
const first = hud.refresh();
requests[0].resolve(result(2));
await first;
assert.equal(gains(), "2");
assert.equal(nodes.get("#activity-periods").children.length, 8);
assert.equal(
  nodes.get("#activity-periods").children[3].attributes["aria-checked"],
  "true",
);

const old = hud.refresh();
mode = { demo: true, subject: "subscriptions" };
const latest = hud.refresh();
assert.equal(
  gains(),
  "—",
  "An audience change clears stale readings immediately.",
);
requests[2].resolve(result(9));
await latest;
requests[1].resolve(result(3));
await old;
assert.equal(gains(), "9", "An old response cannot overwrite a new audience.");
assert.match(requests[2].url, /subject=subscriptions&demo=true/);

nodes.get("#activity-periods").children[0].dispatchEvent(new Event("click"));
assert.match(requests[3].url, /period=1h/);
nodes.get("#activity-periods").children[7].dispatchEvent(new Event("click"));
assert.match(requests[4].url, /period=90d/);
requests[4].resolve(result(90));
await Promise.resolve();
requests[3].reject(new Error("stale failure"));
await Promise.resolve();
assert.equal(
  gains(),
  "90",
  "An earlier period failure cannot clear the current values.",
);
assert.equal(nodes.get("#activity-error").hidden, true);

const failure = hud.refresh();
requests[5].reject(new Error("offline"));
await failure;
assert.equal(gains(), "—");
assert.equal(nodes.get("#activity-error").hidden, false);
const recovery = hud.refresh();
requests[6].resolve(result(10));
await recovery;
assert.equal(gains(), "10");
assert.equal(nodes.get("#activity-error").hidden, true);
const pending = hud.refresh();
hud.destroy();
requests[7].resolve(result(99));
await pending;
assert.equal(gains(), "10", "A detached HUD ignores its pending request.");
console.log(
  "HUD formatting, comparison colors, stale responses, period races and retry passed.",
);
