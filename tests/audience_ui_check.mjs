import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
const base = pathToFileURL(process.argv[2] + "/");
const { createAudienceControls } = await import(
  new URL("audience-ui.js", base)
);

class Element {
  children = [];
  attributes = {};
  dataset = {};
  listeners = [];
  style = {};
  setAttribute(name, value) {
    this.attributes[name] = value;
  }
  append(...children) {
    this.children.push(...children);
  }
  replaceChildren() {
    this.children = [];
  }
  addEventListener(name, handler, options = {}) {
    this.listeners.push({ name, handler, ...options });
  }
  querySelectorAll(selector) {
    return this.children.filter((child) =>
      selector === '[role="menuitemradio"]'
        ? child.attributes.role === "menuitemradio"
        : false,
    );
  }
  querySelector() {
    return null;
  }
  matches() {
    return this.open || false;
  }
  getBoundingClientRect() {
    return { right: 370, bottom: 500, top: 456 };
  }
  focus() {
    globalThis.document.activeElement = this;
  }
  hidePopover() {
    this.open = false;
  }
  async fire(name, extra = {}) {
    for (const listener of this.listeners)
      if (listener.name === name && !listener.signal?.aborted)
        await listener.handler(extra);
  }
}
const savedGlobals = Object.fromEntries(
  ["document", "window", "innerWidth", "innerHeight", "getComputedStyle"].map(
    (key) => [key, globalThis[key]],
  ),
);
const elements = new Map(
  [
    "lens-trigger",
    "audience-lens",
    "lens-control",
    "scene-lens-label",
    "audience-group-options",
    "group-range-control",
    "group-range-trigger",
    "group-range-value",
    "group-ranges",
  ].map((id) => [`#${id}`, new Element()]),
);
globalThis.document = {
  body: {},
  createElement: (tag) => Object.assign(new Element(), { tag }),
};
globalThis.window = new Element();
globalThis.innerWidth = 390;
globalThis.innerHeight = 844;
globalThis.getComputedStyle = () => ({ width: "280px" });
const changes = [];
const ranges = [];
let moveFocusDuringSave = false;
const controls = createAudienceControls({
  root: {
    querySelector: (selector) =>
      elements.get(selector) ||
      elements
        .get("#audience-group-options")
        .children.flatMap((row) => row.children)
        .find((element) => `#${element.id}` === selector),
  },
  onToggle: (...args) => {
    changes.push(args);
    document.activeElement = document.body;
    if (moveFocusDuringSave)
      elements.get("#audience-group-options").children[0].children[1].focus();
    controls.render(groups, "activity");
  },
  onLens: () => {},
  onRange: range => ranges.push(range),
});
const groups = [
  {
    key: "activity",
    label: "Activity",
    description: "Received events only.",
    enabled: true,
  },
  {
    key: "account_age",
    label: "Account age",
    description: "No extra X requests.",
    enabled: false,
  },
];
controls.render(groups, "none");
assert.equal(elements.get("#group-range-control").hidden, false);
controls.render(groups, "activity");
assert.deepEqual(elements.get("#group-ranges").children.map(item => item.textContent), ["1h","6h","12h","24h","3d","7d","30d","90d","All saved"]);
assert.equal(elements.get("#group-range-value").textContent, "24h");
await elements.get("#group-ranges").children[5].fire("click");
assert.deepEqual(ranges,["7d"]);
controls.render(groups, "activity", "7d");
assert.equal(elements.get("#group-range-value").textContent, "7d");
const settings = elements.get("#audience-group-options");
assert.equal(settings.children.length, 2);
for (const [index, row] of settings.children.entries()) {
  const [label, help, toggle, popup] = row.children;
  assert.equal(label.htmlFor, toggle.id);
  assert.equal(label.children.length, 1, "Descriptions stay out of the label.");
  assert.equal(popup.textContent, groups[index].description);
  assert.equal(popup.attributes.popover, "auto");
  assert.equal(help.attributes.popovertarget, popup.id);
  assert.equal(toggle.attributes["aria-describedby"], popup.id);
  assert.equal(toggle.checked, groups[index].enabled);
  await help.fire("click");
  assert.equal(changes.length, 0, "Help must not change the preference.");
  await popup.fire("beforetoggle", { newState: "open" });
  assert.equal(popup.style.left, "90px", "Help fits within a phone viewport.");
}
const oldPopup = settings.children[0].children[3];
settings.children[1].children[2].focus();
controls.render(groups, "activity");
assert.ok(oldPopup.listeners.every((listener) => listener.signal.aborted));
const toggle = settings.children[1].children[2];
assert.equal(document.activeElement, toggle, "Saving retains keyboard focus.");
toggle.checked = true;
await toggle.fire("change");
assert.deepEqual(changes, [[groups[1], toggle]]);
assert.equal(
  document.activeElement,
  settings.children[1].children[2],
  "Focus returns after the caller disables and replaces the switch.",
);
moveFocusDuringSave = true;
await settings.children[1].children[2].fire("change");
assert.equal(
  document.activeElement,
  settings.children[0].children[1],
  "Saving must not steal focus after moving to another help button.",
);
controls.destroy();
assert.ok(window.listeners.every((listener) => listener.signal.aborted));
assert.ok(
  window.listeners
    .filter((listener) => listener.name === "scroll")
    .every((listener) => listener.capture),
);

const shell = await readFile(new URL("shell.html", base), "utf8");
assert.match(
  shell,
  /<details class="workspace-settings audience-group-settings">\s*<summary>\s*<h3/,
);
assert.doesNotMatch(shell, /Saved automatically\. Uses received events only/);
assert.match(shell, /id="follow-actions-help"/);
assert.doesNotMatch(shell, /Off until selected\. Extra X charges/);
Object.assign(globalThis, savedGlobals);
