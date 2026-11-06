import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { renderPersonDetail } = await import(
  new URL("person-detail.js", pathToFileURL(process.argv[2] + "/"))
);
const previewPanel = { innerHTML: "", querySelector: () => ({ insertAdjacentHTML() {} }), insertAdjacentHTML() {} };
const previewRoot = { querySelector: () => previewPanel };
const previewEvent = { kind: "interaction.replies", actor_id: "222", name: "Maya", post_id: "900", post_text: "Hello <script>bad</script>" };
renderPersonDetail(previewRoot, previewEvent);
assert.ok(previewPanel.innerHTML.includes('href="https://x.com/i/status/900"'));
assert.ok(previewPanel.innerHTML.includes("Hello &lt;script&gt;bad&lt;/script&gt;"));
assert.ok(!previewPanel.innerHTML.includes("<script>"));
renderPersonDetail(previewRoot, { ...previewEvent, post_text: "🌟".repeat(300) });
const excerpt = previewPanel.innerHTML.match(/class="detail-post"[^>]*><span>(.*?)<\/span>/s)[1];
assert.equal(Array.from(excerpt).length, 280);
assert.ok(excerpt.endsWith("…"));
for (const changes of [{ post_text: null }, { post_text: "  " }, { post_id: "javascript:alert(1)" }, { kind: "follow.follow" }]) {
  renderPersonDetail(previewRoot, { ...previewEvent, ...changes });
  assert.ok(!previewPanel.innerHTML.includes('class="detail-post"'));
}
const { createInteractionControls, groupInteractions, recordedPosts } =
  await import(
    new URL("interactions.js", pathToFileURL(process.argv[2] + "/"))
  );
const document = { body: {}, activeElement: null };
document.activeElement = document.body;
class Element {
  constructor(host, tag, attrs = "") {
    this.host = host;
    this.tag = tag;
    this.dataset = {};
    this.disabled = false;
    for (const [, name, value] of attrs.matchAll(
      /data-([\w-]+)(?:="([^"]*)")?/g,
    ))
      this.dataset[name.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] =
        value || "";
  }
  matches(selector) {
    if (selector === "summary") return this.tag === "summary";
    const attrs = [...selector.matchAll(/\[data-([\w-]+)(?:="([^"]*)")?\]/g)];
    return (
      attrs.length > 0 &&
      attrs.every(([, name, value]) => {
        const key = name.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        return (
          key in this.dataset &&
          (value === undefined || value === this.dataset[key])
        );
      })
    );
  }
  closest(selector) {
    return this.matches(selector) ? this : null;
  }
  setAttribute(name, value) {
    this[name] = value;
  }
  focus() {
    document.activeElement = this;
  }
}
class Host {
  ownerDocument = document;
  nodes = [];
  markup = "";
  contains(node) {
    return this.nodes.includes(node);
  }
  set innerHTML(value) {
    if (this.contains(document.activeElement))
      document.activeElement = document.body;
    this.markup = value;
    this.nodes = [new Element(this, "summary")];
    this.add(value);
  }
  add(html) {
    for (const [, attrs] of html.matchAll(/<button\b([^>]*)>/g))
      this.nodes.push(new Element(this, "button", attrs));
  }
  querySelector(selector) {
    if (selector === ".interaction-content")
      return { insertAdjacentHTML: (_, html) => this.add(html) };
    return this.nodes.find((node) => node.matches(selector));
  }
  querySelectorAll(selector) {
    return this.nodes.filter((node) => node.matches(selector));
  }
}
const content = new Host();
class Dialog {
  open = false;
  listeners = {};
  title = new Element(null, "h2");
  person = {};
  refresh = new Element(null, "button", "data-refresh-interactions");
  querySelector(selector) {
    if (selector === "[data-interaction-content]") return content;
    if (selector === "#interaction-title") return this.title;
    if (selector === "#interaction-person") return this.person;
    if (selector === "[data-refresh-interactions]") return this.refresh;
    if (selector === "[data-open-interactions]") return trigger;
  }
  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }
  removeEventListener(name) {
    delete this.listeners[name];
  }
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
    this.listeners.close?.();
  }
}
const dialog = new Dialog(),
  personDialog = new Dialog();
const trigger = new Element(null, "button", "data-open-interactions");
const listeners = {};
const root = {
  dataset: { route: "timeline" },
  querySelector: (selector) =>
    selector === "#interaction-dialog" ? dialog : personDialog,
  addEventListener: (name, handler) => (listeners[name] = handler),
  removeEventListener: (name) => delete listeners[name],
};
const calls = [];
let pending = null,
  failure = false;
let records = [
  {
    sequence: 2,
    kind: "replies",
    post_id: "900",
    conversation_id: "800",
    author_id: "222",
    text: "<script>unsafe</script>",
    provider_at: "2026-11-04T00:00:00Z",
  },
  {
    sequence: 1,
    kind: "replies",
    post_id: "900",
    conversation_id: "800",
    author_id: "222",
    text: "<script>unsafe</script>",
    provider_at: "2026-11-04T00:00:00Z",
  },
];
let snapshot = {
  conversation_id: "800",
  checked_at: "2026-11-04T00:00:00Z",
  offset: 0,
  total: 1,
  posts: [{ id: "900", author_id: "222", text: "<script>unsafe</script>" }],
  more_available: false,
  more_saved: false,
};
const api = async (path, body) => {
  calls.push({ path, body });
  if (pending) return pending;
  if (failure) throw new Error("X unavailable");
  return body
    ? structuredClone(snapshot)
    : { interactions: structuredClone(records), next: null };
};
let returned = 0;
const controls = createInteractionControls({
  onReturn: () => returned++,
  root,
  api,
  esc: (value) => String(value).replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
});
const person = {
  event_id: "person",
  actor_id: "222",
  name: "Maya",
  handle: "maya",
};
const status = {
  account: { id: "111" },
  interaction_types: [{ key: "replies", label: "Replies received" }],
};
controls.configure(status, false);
controls.select(person);
assert.equal(
  calls.length,
  0,
  "Selecting person must not preload history or threads",
);
assert.equal(
  groupInteractions(records).length,
  1,
  "Same conversation is represented once",
);
assert.equal(
  recordedPosts(records).length,
  1,
  "Repeated activity on a post does not repeat its body",
);
assert.equal(
  groupInteractions([
    { ...records[0], conversation_id: null },
    { ...records[0], post_id: "901", conversation_id: null },
  ]).length,
  2,
  "Unknown conversation IDs do not combine unrelated posts",
);
personDialog.showModal();
trigger.focus();
await listeners.click({ target: trigger });
assert.equal(calls.length, 1, "Opening own modal only reads local history");
assert(dialog.open && !personDialog.open, "Only one modal is active");
assert.equal(
  document.activeElement,
  dialog.title,
  "Reader title receives initial focus",
);
assert(!content.markup.includes("<script>"));
assert.equal((content.markup.match(/data-conversation=/g) || []).length, 1);
assert.ok(content.markup.includes('class="conversation-external" href="https://x.com/i/status/800"'));
assert.ok(content.markup.includes('rel="noopener noreferrer">Open thread on X'));
assert(content.markup.includes("2 replies"));
assert(!content.markup.includes("Costs &amp; updates"));
assert(!content.markup.includes("Open post ↗"));
let button = content.querySelector('[data-thread-action="open"]');
button.focus();
let resolve;
pending = new Promise((done) => (resolve = done));
const loading = listeners.click({ target: button });
await listeners.click({
  target: content.querySelector('[data-thread-action="open"]'),
});
assert.equal(calls.length, 2, "Busy state prevents duplicate paid loads");
assert.equal(
  document.activeElement,
  content.querySelector('[data-thread-action="open"]'),
);
pending = null;
resolve(structuredClone(snapshot));
await loading;
assert.equal(calls[1].body.accepted_costs, true);
assert.equal(
  (content.markup.match(/unsafe/g) || []).length,
  1,
  "Loaded thread replaces preview rather than duplicating it",
);
assert(content.markup.includes("Snapshot"));
const beforeCollapse = calls.length;
await listeners.click({
  target: content.querySelector('[data-thread-action="open"]'),
});
await listeners.click({
  target: content.querySelector('[data-thread-action="open"]'),
});
assert.equal(
  calls.length,
  beforeCollapse,
  "Collapse and expand a loaded conversation never reads X",
);
failure = true;
await listeners.click({
  target: content.querySelector('[data-thread-action="refresh"]'),
});
assert(
  content.markup.includes("X unavailable") && content.markup.includes("unsafe"),
  "Failed refresh retains saved posts",
);
failure = false;
records.unshift({
  ...records[0],
  sequence: 3,
  post_id: "950",
  text: "New saved reply",
});
snapshot.posts.push({ id: "950", author_id: "222", text: "New saved reply" });
snapshot.total = 2;
await controls.refresh();
assert.equal(calls.at(-1).body.action, "cached");
assert.equal(calls.at(-1).body.accepted_costs, false);
assert(
  content.markup.includes("3 replies") &&
    content.markup.includes("New saved reply"),
);
dialog.close();
assert.equal(returned, 1, "Returning resumes shared person controls");
assert(
  personDialog.open && !dialog.open,
  "Closing reader returns to person dialog",
);
assert.equal(
  document.activeElement,
  trigger,
  "Close returns keyboard focus to current invoker",
);
await listeners.click({ target: trigger });
assert.equal(
  calls.at(-1).body.action,
  "cached",
  "Reopening only refreshes the database copy",
);
snapshot.more_saved = true;
await controls.refresh();
snapshot = {
  ...snapshot,
  offset: 2,
  total: 4,
  posts: [
    { id: "950", author_id: "222", text: "New saved reply" },
    { id: "960", author_id: "222", text: "Next page" },
  ],
  more_saved: true,
};
await listeners.click({
  target: content.querySelector('[data-thread-action="cached"]'),
});
assert.equal(calls.at(-1).body.offset, 2);
snapshot = {
  ...snapshot,
  offset: 4,
  posts: [{ id: "970", author_id: "222", text: "Last page" }],
  more_saved: false,
};
await listeners.click({
  target: content.querySelector('[data-thread-action="cached"]'),
});
assert.equal(
  calls.at(-1).body.offset,
  4,
  "Local paging advances server cursor even when a page overlaps existing posts",
);
assert.equal((content.markup.match(/New saved reply/g) || []).length, 1);

let late;
pending = new Promise((done) => (late = done));
const request = listeners.click({
  target: content.querySelector('[data-thread-action="refresh"]'),
});
controls.select({ ...person, event_id: "other", actor_id: "333" });
document.activeElement = document.body;
pending = null;
late({ ...snapshot, posts: [{ id: "900", text: "STALE PERSON" }] });
await request;
assert(!dialog.open, "Changing person closes old interaction reader");
await listeners.click({ target: trigger });
assert(!content.markup.includes("STALE PERSON"));
assert.equal(document.activeElement, dialog.title);
controls.configure({ ...status, account: { id: "999" } }, false);
assert(
  !dialog.open && !personDialog.open,
  "Account change does not reopen old person",
);
controls.configure(status, false);
controls.select(person);
records = [
  {
    ...records[0],
    sequence: 1,
    post_id: "900",
    conversation_id: null,
    thread_saved: false,
  },
  {
    ...records[0],
    sequence: 2,
    post_id: "950",
    conversation_id: "800",
    thread_saved: true,
  },
];
snapshot = {
  ...snapshot,
  offset: 0,
  conversation_id: "800",
  posts: [
    { id: "900", text: "Root" },
    { id: "950", text: "Reply" },
  ],
  total: 2,
  more_saved: false,
};
await listeners.click({ target: trigger });
assert.equal((content.markup.match(/data-conversation=/g) || []).length, 2);
await listeners.click({
  target: content.querySelector(
    '[data-thread-action="open"][data-group="p900"]',
  ),
});
assert.equal(
  (content.markup.match(/data-conversation=/g) || []).length,
  1,
  "Resolving a missing conversation combines it with the existing thread",
);
assert(content.markup.includes("2 replies"));
snapshot = {
  ...snapshot,
  posts: [
    { id: "800", author_id: "111", text: "Your post" },
    { id: "900", author_id: "222", text: "Selected person's post" },
    { id: "950", author_id: "333", text: "Another participant's post" },
    { id: "960", text: "Author not supplied" },
  ],
  total: 4,
};
await controls.refresh();
assert(content.markup.includes("<strong>You</strong>"));
assert(content.markup.includes("<strong>Maya</strong>"));
assert.equal(
  (content.markup.match(/<strong>Other participant<\/strong>/g) || []).length,
  2,
  "Other and missing authors retain the honest fallback label",
);
const historyReadsBefore = calls.filter(call=>!call.body).length;
const callsBeforeQueued = calls.length;
let releaseHistory;
pending = new Promise(resolve=>releaseHistory=resolve);
const runningRefresh = controls.refresh();
await Promise.resolve();
controls.refresh();
const earlierRows = structuredClone(records);
records.push({...records[0],sequence:99,post_id:"9999",conversation_id:"9999",text:"Arrived during local refresh"});
pending = null;
releaseHistory({interactions:earlierRows,next:null});
await runningRefresh;
await new Promise(resolve=>setImmediate(resolve));
assert.equal(calls.filter(call=>!call.body).length,historyReadsBefore+2,"A change received while busy queues another local read");
assert(content.markup.includes("Arrived during local refresh"));
assert(calls.slice(callsBeforeQueued).every(call=>!call.body || call.body.action==="cached"),"Queued updates never load threads from X");
controls.destroy();
console.log(
  "Grouped threads, post deduplication, modal focus/return, explicit costs, local refresh and async guards passed",
);
