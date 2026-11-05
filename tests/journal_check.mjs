import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const base = pathToFileURL(process.argv[2] + "/");
const { groupEvents } = await import(new URL("audience-groups.js", base));
const { createJournal } = await import(new URL("journal.js", base));
const modules = JSON.parse(process.argv[3]);
const stamp = "2026-10-26T12:00:00Z";
const event = (event_id, actor_id, sequence, kind, size) => ({
  event_id,
  actor_id,
  sequence,
  kind,
  name: "Person " + actor_id,
  handle: "person" + actor_id,
  provider_at: stamp,
  received_at: stamp,
  audience_groups: { activity: kind, "account-size": size },
});
const events = [
  event("new-follow", "1", 4, "follow.follow", "under-100"),
  event("new-lost", "1", 3, "follow.unfollow", "100-999"),
  event("old-follow", "2", 2, "follow.follow", "under-100"),
  event("unknown-size", "3", 1, "follow.follow"),
];
const grouped = groupEvents(events, modules, "activity");
assert.deepEqual(
  grouped.map((group) => group.events.map((event) => event.event_id)),
  [["new-follow", "old-follow", "unknown-size"], ["new-lost"]],
);
assert.equal(
  grouped.flatMap((group) => group.events).length,
  4,
  "Repeated people retain every individual event.",
);
assert.equal(
  groupEvents(events, modules, "account-size").at(-1).key,
  "unknown",
);
assert.equal(groupEvents(events, modules, "none"), null);
assert.equal(
  groupEvents(
    events,
    modules.map((module) => ({ ...module, enabled: false })),
    "activity",
  ),
  null,
);
const extension = {
  key: "future",
  enabled: true,
  buckets: [{ key: "unknown", label: "<Future>", tone: "neutral" }],
};
assert.equal(
  groupEvents(events, [extension], "future")[0].events.length,
  4,
  "New catalog modules require no journal-specific logic.",
);

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ],
  );
const opened = [];
let scrolled = null;
const element = {
  html: "",
  groups: [],
  buttons: [],
  set innerHTML(html) {
    this.html = html;
    this.groups = [];
    this.buttons = [];
    const buttons = (markup, parent) => {
      for (const [, id] of markup.matchAll(/data-event="([^"]+)"/g)) {
        this.buttons.push({
          dataset: { event: id },
          handlers: {},
          addEventListener(type, callback) {
            this.handlers[type] = callback;
          },
          closest() {
            return parent;
          },
          scrollIntoView() {
            scrolled = id;
          },
        });
      }
    };
    for (const [, attributes, key, body] of html.matchAll(
      /<details([^>]*data-group="([^"]+)"[^>]*)>([\s\S]*?)<\/details>/g,
    )) {
      const group = {
        dataset: { group: key },
        open: /\sopen(?:\s|$)/.test(attributes),
        handlers: {},
        addEventListener(type, callback) {
          this.handlers[type] = callback;
        },
      };
      this.groups.push(group);
      buttons(body, group);
    }
    if (!this.groups.length) buttons(html, null);
  },
  querySelectorAll(selector) {
    return selector === "details[data-group]" ? this.groups : this.buttons;
  },
};
const journal = createJournal({
  element,
  escape: esc,
  date: new Intl.DateTimeFormat("en"),
  time: new Intl.DateTimeFormat("en"),
  displayDate: (event) => new Date(event.provider_at || event.received_at),
  gained: (event) => event.kind === "follow.follow",
  label: (event) => event.kind,
  initials: () => "P",
  onOpen: (id) => opened.push(id),
});
const options = { modules, lens: "activity", selected: "new-lost" };
journal.render(events, options);
assert.equal(element.groups.length, 2);
assert.ok(
  element.html.includes("3 events") && element.html.includes("1 event"),
);
assert.ok(element.html.includes('data-event="new-lost" aria-pressed="true"'));
element.buttons
  .find((button) => button.dataset.event === "new-lost")
  .handlers.click();
assert.deepEqual(opened, ["new-lost"]);
element.groups[0].open = false;
element.groups[0].handlers.toggle();
const appended = [
  ...events,
  event("older", "4", 0, "follow.follow", "under-100"),
];
journal.render(appended, options);
assert.equal(
  element.groups[0].open,
  false,
  "Pagination preserves collapsed groups.",
);
assert.equal(element.buttons.length, 5);
journal.reveal("new-follow");
assert.equal(
  element.groups[0].open,
  true,
  "Latest can reveal an event inside a collapsed group.",
);
assert.equal(scrolled, "new-follow");
journal.render(appended, options);
assert.equal(element.groups[0].open, true);
journal.reveal("new-lost");
assert.equal(
  scrolled,
  "new-lost",
  "Navigation finds the selected record across bucket order.",
);
journal.render(events, { ...options, lens: "none" });
assert.equal(element.groups.length, 0);
assert.deepEqual(
  element.buttons.map((button) => button.dataset.event),
  events.map((event) => event.event_id),
  "Ungrouped retains the full input order.",
);
for (const module of modules.filter((module) => module.enabled)) {
  const records = module.buckets.map((bucket, index) => ({
    ...events[0],
    event_id: `${module.key}-${index}`,
    audience_groups: { [module.key]: bucket.key },
  }));
  journal.render(records, { ...options, lens: module.key });
  assert.equal(element.groups.length, module.buckets.length);
  assert.deepEqual(
    element.buttons.map((button) => button.dataset.event),
    records.map((event) => event.event_id),
    `${module.label} renders all registered buckets and keeps every record.`,
  );
}
const locations = modules.find((module) => module.key === "profile-location");
assert.equal(locations.dynamic_buckets, true);
const locationRecord = (index, label) => ({
  ...events[0],
  event_id: `location-${index}`,
  sequence: index,
  audience_groups: { "profile-location": `location-${index}` },
  audience_group_buckets: {
    "profile-location": { key: `location-${index}`, label, tone: "neutral" },
  },
});
const locationRows = [
  locationRecord(1, "London"),
  locationRecord(2, "New York City"),
  {
    ...locationRecord(3, "London"),
    audience_groups: { "profile-location": "location-1" },
  },
  { ...events[0], event_id: "unknown-location" },
];
locationRows[2].audience_group_buckets["profile-location"].key = "location-1";
const namedGroups = groupEvents(locationRows, modules, locations.key);
assert.deepEqual(
  namedGroups.map((group) => [group.label, group.events.length]),
  [
    ["London", 2],
    ["New York City", 1],
    ["Unknown", 1],
  ],
);
journal.render(locationRows, { ...options, lens: locations.key });
assert.equal(element.groups.length, 3);
element.groups[0].open = false;
element.groups[0].handlers.toggle();
journal.reveal("location-3");
assert.equal(element.groups[0].open, true);
assert.equal(scrolled, "location-3");
const manyLocations = Array.from({ length: 30 }, (_, index) =>
  locationRecord(index, `City ${index}`),
);
journal.render(manyLocations, { ...options, lens: locations.key });
assert.equal(
  element.groups.length,
  30,
  "Journal retains every named location.",
);
assert.equal(element.buttons.length, 30);
for (const descriptor of [
  null,
  {},
  { key: "wrong", label: "London" },
  { key: "location-1", label: {} },
  { key: "location-1", label: "a".repeat(161) },
]) {
  const row = locationRecord(1, "London");
  row.audience_group_buckets[locations.key] = descriptor;
  assert.equal(groupEvents([row], modules, locations.key)[0].key, "unknown");
}
assert.equal(
  groupEvents(
    [locationRecord(1, "London")],
    [{ ...locations, dynamic_buckets: false }],
    locations.key,
  )[0].key,
  "unknown",
);
assert.equal(
  groupEvents(
    [locationRecord(1, "🏔️".repeat(60) + "London")],
    modules,
    locations.key,
  )[0].key,
  "location-1",
);
journal.render([locationRecord(1, '<img src=x onerror="bad()">')], {
  ...options,
  lens: locations.key,
});
assert.ok(element.html.includes("&lt;img"));
assert.ok(!element.html.includes("<img"));
journal.render([{ ...events[0], name: '<img src=x onerror="bad()">' }], {
  ...options,
  modules: [extension],
  lens: "future",
});
assert.ok(element.html.includes("&lt;Future&gt;"));
assert.ok(element.html.includes("&lt;img"));
assert.ok(!element.html.includes("<img"));
