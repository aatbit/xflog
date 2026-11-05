import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { join } from "node:path";
const { createSelectedSignal } = await import(
  new URL("selected-signal.js", pathToFileURL(process.argv[2] + "/"))
);
const { verificationBadge } = await import(
  new URL("verification-badge.js", pathToFileURL(process.argv[2] + "/"))
);
class Node extends EventTarget {
  renderedWidth = 100;
  getBoundingClientRect() {
    return { width: this.renderedWidth };
  }
  clientWidth = 520;
  children = [];
  textContent = "";
  hidden = true;
  dataset = {};
  attributes = {};
  setAttribute(key, value) {
    this.attributes[key] = value;
  }
  append(...children) {
    this.children.push(...children);
  }
  replaceChildren(...children) {
    this.children = children;
  }
  set innerHTML(value) {
    if (this === nodes.get("#signal-verification")) {
      this.markup = value;
      return;
    }
    throw new Error("Selected profile text must not become HTML");
  }
}
globalThis.document = { createElement: () => new Node() };
const modules = JSON.parse(process.argv[3]);
const html = readFileSync(join(process.argv[2], "shell.html"), "utf8");
const nodes = new Map(
  [...html.matchAll(/id="([^"]+)"/g)].map((match) => [
    "#" + match[1],
    new Node(),
  ]),
);
globalThis.getComputedStyle = (node) => ({
  gap: node === nodes.get("#signal-identity") ? "20px" : "16px",
  width: "100px",
});
let resized,
  disconnected = false;
globalThis.ResizeObserver = class {
  constructor(callback) {
    resized = callback;
  }
  observe() {}
  disconnect() {
    disconnected = true;
  }
};
const opened = [];
const readout = createSelectedSignal({
  root: {
    querySelector: (selector) => {
      assert(nodes.has(selector), selector);
      return nodes.get(selector);
    },
  },
  label: (event) =>
    event.kind === "follow.follow" ? "Followed you" : "Unfollowed",
  gained: (event) => event.kind === "follow.follow",
  date: { format: (date) => date.toISOString().slice(0, 10) },
  time: { format: (date) => date.toISOString().slice(11, 16) },
  fullDate: { format: (date) => date.toISOString() },
  onOpen: (identity) => opened.push(identity),
});
const button = nodes.get("#selected-signal");
const event = {
  event_id: "latest",
  actor_id: "123",
  name: "<img src=x onerror=alert(1)>",
  handle: "maya",
  kind: "follow.follow",
  provider_at: "2020-01-01T01:00:00Z",
  received_at: "2026-10-26T12:30:00Z",
};
readout.render(event);
assert.equal(button.hidden, false);
assert.equal(nodes.get("#signal-name").textContent, event.name);
assert.equal(nodes.get("#signal-handle").textContent, "@maya");
assert.equal(nodes.get("#signal-received").dateTime, event.received_at);
assert.equal(nodes.get("#signal-received").textContent, "2026-10-26 · 12:30");
assert.equal(nodes.get("#signal-activity").textContent, "Followed you");
assert.equal(button.dataset.tone, "gained");
button.dispatchEvent(new Event("click"));
readout.render({
  ...event,
  event_id: "older",
  kind: "follow.unfollow",
  name: null,
  handle: null,
});
button.dispatchEvent(new Event("click"));
assert.equal(nodes.get("#signal-name").textContent, "X account");
assert.equal(nodes.get("#signal-handle").textContent, "ID 123");
assert.equal(button.dataset.tone, "lost");
assert.equal(nodes.get("#signal-activity").textContent, "Unfollowed");
assert.deepEqual(opened, ["latest", "older"]);
const profileEvent = {
  ...event,
  audience_groups: {
    verification: "blue",
    "account-size": "100-999",
    "account-age": "3-plus-years",
  },
};
const facts = () => nodes.get("#signal-profile").children;
const labels = () =>
  facts().map((fact) => fact.children.map((child) => child.textContent));
readout.render(profileEvent, modules);
assert.deepEqual(labels(), [
  ["Verification", "Blue badge"],
  ["Account size", "100–999 followers"],
  ["Account age", "3+ years"],
]);
assert.match(nodes.get("#signal-verification").markup, /aria-label="Verified"/);
assert.equal(facts().filter((fact) => !fact.hidden).length, 3);
nodes.get("#signal-identity").clientWidth = 380;
resized();
assert.equal(facts().filter((fact) => !fact.hidden).length, 2);
facts()[2].renderedWidth = 50;
nodes.get("#signal-identity").clientWidth = 448;
resized();
assert.equal(
  facts().filter((fact) => !fact.hidden).length,
  3,
  "Shorter fields reuse available space without truncation.",
);
nodes.get("#signal-identity").clientWidth = 270;
resized();
assert.equal(facts().filter((fact) => !fact.hidden).length, 1);
nodes.get("#signal-identity").clientWidth = 180;
resized();
assert.equal(facts().filter((fact) => !fact.hidden).length, 0);
assert.equal(nodes.get("#signal-profile").hidden, true);
nodes.get("#signal-identity").clientWidth = 520;
resized();
readout.render(
  profileEvent,
  modules.map((module) => ({
    ...module,
    enabled: module.key === "account-age",
  })),
);
assert.deepEqual(
  labels(),
  [["Account age", "3+ years"]],
  "Disabled groups cannot leak cached metadata into the HUD.",
);
assert.equal(nodes.get("#signal-verification").markup, "");
readout.destroy();
assert.equal(disconnected, true);
readout.render(
  profileEvent,
  modules.map((module) => ({ ...module, enabled: false })),
);
assert.equal(facts().length, 0);
readout.render({ ...profileEvent, audience_groups: {} }, modules);
assert.deepEqual(
  labels().map((fact) => fact[1]),
  ["Unknown", "Unknown", "Unknown"],
);
readout.render(
  { ...profileEvent, audience_groups: { verification: "unverified" } },
  modules,
);
assert.equal(labels()[0][1], "Unverified");
assert.equal(nodes.get("#signal-verification").markup, "");
for (const key of ["blue", "business", "government", "verified"])
  assert.match(
    verificationBadge(
      { ...event, audience_groups: { verification: key } },
      modules,
    ),
    /verified-badge/,
  );
for (const key of ["unknown", "unverified", undefined, "unexpected"])
  assert.equal(
    verificationBadge(
      { ...event, audience_groups: { verification: key } },
      modules,
    ),
    "",
  );
assert.equal(
  verificationBadge(
    profileEvent,
    modules.map((module) => ({ ...module, enabled: false })),
  ),
  "",
);
readout.render(null);
button.dispatchEvent(new Event("click"));
assert.equal(button.hidden, true);
assert.equal(facts().length, 0);
assert.deepEqual(
  opened,
  ["latest", "older"],
  "Clearing selection must not open an old profile.",
);
console.log(
  "Selected signal text, receipt time, latest selection and empty-state checks passed.",
);
