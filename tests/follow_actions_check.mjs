import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { createFollowControls } = await import(
  new URL("follow-actions.js", pathToFileURL(process.argv[2] + "/"))
);
const state = (following = false) => ({
  following,
  pending: false,
  blocked: false,
});
const event = (id) => ({ event_id: id, actor_id: id, name: id, handle: id });
const enabled = {
  follow_actions: { enabled: true, available: true, reason: "" },
  account: { id: "owner" },
};

class Element extends EventTarget {
  hidden = false;
  _disabled = false;
  isConnected = true;
  get disabled() {
    return this._disabled;
  }
  set disabled(value) {
    this._disabled = value;
    if (value && globalThis.document?.activeElement === this)
      globalThis.document.activeElement = globalThis.document.body;
  }
  focus() {
    globalThis.document.activeElement = this;
  }
  open = false;
  dataset = {};
  style = {};
  children = [];
  attributes = {};
  textContent = "";
  rect = { width: 0, height: 44, top: 10, left: 100, right: 100 };
  inner = new Map();
  setAttribute(key, value) {
    this.attributes[key] = value;
  }
  replaceChildren(...children) {
    this.children = children;
  }
  getBoundingClientRect() {
    return this.rect;
  }
  querySelector(key) {
    if (!this.inner.has(key)) this.inner.set(key, new Element());
    return this.inner.get(key);
  }
  set innerHTML(value) {
    assert(!value.includes("<img"));
  }
  showModal() {
    this.open = true;
    this.querySelector(".dialog-close").focus();
  }
  contains(node) {
    return (
      node === this ||
      [...this.inner.values()].some((child) => child.contains(node))
    );
  }
  close(value = "") {
    this.open = false;
    this.returnValue = value;
    this.dispatchEvent(new Event("close"));
  }
}
function fixture() {
  const timers = new Map();
  let sequence = 0;
  globalThis.setTimeout = (fn) => {
    timers.set(++sequence, fn);
    return sequence;
  };
  globalThis.clearTimeout = (id) => timers.delete(id);
  globalThis.document = {
    body: new Element(),
    createElement: () => new Element(),
    createRange: () => ({
      selectNodeContents() {},
      getBoundingClientRect: () => ({ width: 80 }),
    }),
  };
  globalThis.document.activeElement = globalThis.document.body;
  const nodes = new Map();
  const root = new Element();
  root.dataset.route = "timeline";
  root.querySelector = (key) => {
    if (!nodes.has(key)) nodes.set(key, new Element());
    return nodes.get(key);
  };
  const hud = root.querySelector("#signal-follow");
  const detail = new Element();
  const feedback = new Element();
  const buttons = [hud, detail];
  root.querySelectorAll = (key) =>
    key === "[data-follow-button]" ? buttons : [feedback];
  const listeners = new Map();
  root.addEventListener = (key, fn) => listeners.set(key, fn);
  root.removeEventListener = (key) => listeners.delete(key);
  for (const button of buttons) button.closest = () => button;
  hud.parentElement = new Element();
  const person = root
    .querySelector("#signal-identity")
    .querySelector(".signal-person");
  person.rect = { ...person.rect, width: 500, right: 600 };
  root.querySelector("#timeline-view").dataset.layout = "horizontal";
  root.querySelector("#selected-signal").hidden = false;
  const calls = [];
  let respond = async () => state();
  const announced = [];
  const controls = createFollowControls({
    root,
    api: (path, body) => {
      calls.push({ path, body });
      return respond(path, body);
    },
    announce: (message) => announced.push(message),
  });
  return {
    root,
    hud,
    detail,
    buttons,
    feedback,
    person,
    calls,
    controls,
    announced,
    respond(fn) {
      respond = fn;
    },
    click(button = detail) {
      return listeners.get("click")({ target: button });
    },
    next() {
      const first = timers.entries().next().value;
      assert(first, "a relationship check was scheduled");
      timers.delete(first[0]);
      return first[1]();
    },
    get pending() {
      return timers.size;
    },
    get label() {
      return detail.children[0].textContent;
    },
  };
}

{
  const f = fixture();
  f.controls.configure(
    { ...enabled, follow_actions: { enabled: false, available: true } },
    false,
  );
  f.controls.select(event("a"));
  assert(f.buttons.every((b) => b.disabled));
  assert.equal(f.pending, 0);
  f.controls.configure(enabled, true);
  assert.match(f.detail.title, /offline demo/);
  assert.equal(f.calls.length, 0);
  f.controls.destroy();
}
{
  const f = fixture();
  f.respond(async (path) =>
    path.endsWith("relationship") ? state(true) : state(false),
  );
  f.controls.configure(enabled, false);
  f.controls.select(event("a"));
  await f.next();
  assert(f.buttons.every((b) => b.dataset.following === "true" && !b.disabled));
  for (let i = 0; i < 4; i++) f.controls.configure(enabled, false);
  f.controls.select({ ...event("a"), event_id: "another-event-for-a" });
  assert.equal(
    f.calls.length,
    1,
    "polls and another event for the same person do not repeat the lookup",
  );
  f.hud.focus();
  const cancelled = f.click(f.hud);
  f.root
    .querySelector("#dialog-body")
    .querySelector("[data-cancel-unfollow]")
    .onclick();
  await cancelled;
  assert.equal(f.calls.length, 1);
  assert.equal(
    document.activeElement,
    f.hud,
    "Cancel restores the keyboard invoker",
  );
  const action = f.click(f.hud);
  const modal = f.root.querySelector("#action-dialog");
  assert(modal.open);
  f.root
    .querySelector("#dialog-body")
    .querySelector("[data-confirm-unfollow]")
    .onclick();
  await action;
  assert.equal(
    document.activeElement,
    f.hud,
    "settlement restores the keyboard invoker",
  );
  assert.equal(f.calls[1].body.following, false);
  assert.equal(f.calls[1].body.event_id, "another-event-for-a");
  assert(
    f.buttons.every((b) => b.dataset.following === "false" && !b.disabled),
  );
  assert.equal(f.label, "Follow");
  f.controls.destroy();
}
{
  const f = fixture();
  f.controls.configure(enabled, false);
  f.controls.select(event("a"));
  await f.next();
  let finish;
  f.respond(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const action = f.click(f.hud);
  await f.click(f.detail);
  assert.equal(f.calls.length, 2, "HUD and details share one in-flight write");
  assert(f.buttons.every((b) => b.disabled));
  finish(state(true));
  await action;
  assert.equal(f.label, "Following");
  f.controls.destroy();
}
{
  const f = fixture();
  let old;
  f.respond((path, body) =>
    body.event_id === "a"
      ? new Promise((resolve) => {
          old = resolve;
        })
      : Promise.resolve(state(false)),
  );
  f.controls.configure(enabled, false);
  f.controls.select(event("a"));
  const readingA = f.next();
  f.controls.select(event("b"));
  await f.next();
  old(state(true));
  await readingA;
  assert.equal(f.label, "Follow", "late A cannot turn B into Following");
  assert.match(f.detail.attributes["aria-label"], /@b/);
  f.controls.destroy();
}
{
  const f = fixture();
  f.controls.configure(enabled, false);
  f.controls.select(event("a"));
  f.controls.select(event("b"));
  f.controls.select(event("c"));
  assert.equal(f.pending, 1);
  await f.next();
  assert.deepEqual(
    f.calls.map((call) => call.body.event_id),
    ["c"],
  );
  f.controls.destroy();
}
{
  const f = fixture();
  f.respond(async () => {
    throw new Error("X denied read access.");
  });
  f.controls.configure(enabled, false);
  f.controls.select(event("a"));
  await f.next();
  assert.equal(f.label, "Retry");
  assert.match(f.feedback.textContent, /denied read/);
  f.respond(async () => state());
  f.detail.focus();
  await f.click();
  await f.next();
  assert.equal(
    document.activeElement,
    f.detail,
    "Retry restores focus after the check completes",
  );
  assert.equal(f.label, "Follow");
  assert(
    f.calls.every((call) => call.path.endsWith("relationship")),
    "retry only checks state",
  );
  f.controls.destroy();
}
for (const result of [
  { ...state(), pending: true },
  { ...state(), blocked: true },
  { following: false },
]) {
  const f = fixture();
  f.respond(async () => result);
  f.controls.configure(enabled, false);
  f.controls.select(event("a"));
  await f.next();
  if (result.pending || result.blocked)
    assert(f.buttons.every((b) => b.disabled));
  else
    assert.equal(
      f.label,
      "Retry",
      "missing state must not turn into an actionable Follow",
    );
  assert.equal(f.calls.length, 1);
  f.controls.destroy();
}
{
  const f = fixture();
  f.person.rect.width = 100;
  f.controls.configure(enabled, false);
  f.controls.select(event("a"));
  assert(f.hud.hidden);
  assert.equal(f.pending, 0, "no paid lookup when no action can be shown");
  f.root.querySelector("#detail-dialog").open = true;
  f.controls.select(event("a"));
  await f.next();
  assert(!f.detail.disabled);
  f.controls.destroy();
}
{
  const f = fixture();
  let finish;
  f.respond(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  f.controls.configure(enabled, false);
  f.controls.select(event("a"));
  const reading = f.next();
  f.controls.configure(
    { ...enabled, follow_actions: { enabled: false, available: true } },
    false,
  );
  finish(state(true));
  await reading;
  assert(f.buttons.every((b) => b.disabled));
  assert.equal(f.label, "Follow");
  f.controls.destroy();
}
{
  const f = fixture();
  f.respond(async () => state(true));
  f.controls.configure(enabled, false);
  f.controls.select(event("a"));
  await f.next();
  const action = f.click();
  f.controls.configure(enabled, true);
  f.root
    .querySelector("#dialog-body")
    .querySelector("[data-confirm-unfollow]")
    .onclick();
  await action;
  assert.equal(
    f.calls.length,
    1,
    "entering demo while confirming prevents the mutation",
  );
  f.controls.destroy();
}
console.log(
  "Follow controls: opt-in, shared state, confirmation, races, retry and available-space checks passed.",
);
