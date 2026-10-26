import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { join } from "node:path";
const { createSelectedSignal } = await import(
  new URL("selected-signal.js", pathToFileURL(process.argv[2] + "/"))
);
class Node extends EventTarget {
  textContent = "";
  hidden = true;
  dataset = {};
  attributes = {};
  setAttribute(key, value) {
    this.attributes[key] = value;
  }
  set innerHTML(value) {
    throw new Error("Selected profile text must not become HTML");
  }
}
const html = readFileSync(join(process.argv[2], "shell.html"), "utf8");
const nodes = new Map(
  [...html.matchAll(/id="([^"]+)"/g)].map((match) => [
    "#" + match[1],
    new Node(),
  ]),
);
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
readout.render(null);
button.dispatchEvent(new Event("click"));
assert.equal(button.hidden, true);
assert.deepEqual(
  opened,
  ["latest", "older"],
  "Clearing selection must not open an old profile.",
);
console.log(
  "Selected signal text, receipt time, latest selection and empty-state checks passed.",
);
