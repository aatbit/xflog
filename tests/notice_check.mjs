import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const { createNotice, statusNotice } = await import(pathToFileURL(process.argv[2]));
const callbacks = new Map();
let sequence = 0;
globalThis.setTimeout = (callback, delay) => {
  assert.equal(delay, 6000);
  callbacks.set(++sequence, callback);
  return sequence;
};
globalThis.clearTimeout = (id) => callbacks.delete(id);
const listeners = new Map();
const close = { addEventListener: (_, callback) => listeners.set("dismiss", callback) };
const text = { textContent: "" };
const icon = { innerHTML: "" };
const kind = { textContent: "" };
const element = {
  hidden: true,
  dataset: {},
  interacting: false,
  querySelector: (selector) => ({
    "#notice-message": text, ".notice-icon": icon, "#notice-kind": kind, "#notice-dismiss": close,
  })[selector],
  addEventListener: (event, callback) => listeners.set(event, callback),
  matches: () => element.interacting,
};
const notice = createNotice(element);
notice.show("Preferences saved.", "success");
assert.equal(element.dataset.tone, "success");
assert.equal(kind.textContent, "success: ");
assert.equal(callbacks.size, 1);
const oldTimer = sequence;
notice.show("New activity.");
assert.equal(callbacks.has(oldTimer), false, "Old notice must not dismiss a replacement");
assert.equal(element.dataset.tone, "info");
callbacks.get(sequence)();
assert.equal(element.hidden, true);

notice.show("Saved.", "success");
element.interacting = true;
listeners.get("pointerenter")();
assert.equal(callbacks.size, 0);
element.interacting = false;
listeners.get("pointerleave")();
assert.equal(callbacks.size, 1);
element.interacting = true;
listeners.get("focusin")();
assert.equal(callbacks.size, 0);
element.interacting = false;
listeners.get("focusout")();
assert.equal(callbacks.size, 1);

for (const tone of ["warning", "error"]) {
  notice.show("Needs attention.", tone);
  assert.equal(callbacks.size, 0, `${tone} must wait for dismissal`);
  assert.equal(element.hidden, false);
  listeners.get("dismiss")();
  assert.equal(element.hidden, true);
}
const failure = { message: "X denied access.", tone: "error" };
notice.update(failure);
listeners.get("dismiss")();
notice.update({ ...failure });
assert.equal(element.hidden, true, "Unchanged polling must respect dismissal");
notice.update(null);
notice.update(failure);
assert.equal(element.hidden, false, "A new failure after recovery must be shown");
notice.update(null);
assert.equal(element.hidden, true);
notice.show("Preferences saved.", "success");
notice.update(failure);
notice.show("A newer message.");
notice.update(null);
assert.equal(notice.message, "A newer message.", "Recovery must preserve a newer notice");
notice.show('<img src=x onerror="alert(1)">');
assert.equal(text.textContent, '<img src=x onerror="alert(1)">');
listeners.get("dismiss")();
notice.show("Saved again.", "success");
listeners.get("dismiss")();
notice.show("Saved again.", "success");
assert.equal(element.hidden, false, "Explicit actions can show the same notice again");
notice.destroy();
assert.equal(callbacks.size, 0);

assert.equal(statusNotice({ state: "tracking" }), null);
assert.equal(statusNotice({ state: "reconnecting", message: "Retrying" }).tone, "warning");
assert.equal(statusNotice({ state: "reconnect", message: "X denied access" }).tone, "error");
assert.equal(statusNotice({ state: "error", message: "Storage failed" }).tone, "error");
assert.equal(statusNotice({ cleanup_warning: "Cleanup incomplete" }).tone, "warning");
assert.equal(statusNotice({ preference_warning: "Not applied" }).tone, "warning");
