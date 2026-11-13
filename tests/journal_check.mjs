import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const base = pathToFileURL(process.argv[2] + "/");
const { groupEvents } = await import(new URL("audience-groups.js", base));
const { createJournalModel } = await import(new URL("journal-model.js", base));
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

const day = (record) => (record.provider_at || record.received_at).slice(0, 10);
const collapsed = new Set();
const model = (records, lens = "activity") =>
  createJournalModel(records, {modules, lens, collapsed, day});
const eventsIn = (journal) =>
  journal.rows.filter((row) => row.type === "event").map((row) => row.event.event_id);

assert.deepEqual(eventsIn(model(events)), ["new-follow", "old-follow", "unknown-size", "new-lost"]);
assert.deepEqual(eventsIn(model(events, "none")), events.map((record) => record.event_id));
assert.deepEqual(model([], "activity").rows, []);
assert.equal(model([], "none").heights.at(0), -1);

for (const module of modules.filter((item) => item.enabled)) {
  const records = module.buckets.map((bucket, index) => ({
    ...events[0],
    event_id: `${module.key}-${index}`,
    audience_groups: { [module.key]: bucket.key },
  }));
  const journal = model(records, module.key);
  assert.deepEqual(journal.groups.map((group) => group.key), module.buckets.map((bucket) => bucket.key));
  assert.deepEqual(eventsIn(journal), records.map((record) => record.event_id));
}

const dateChanges = [
  {...events[0], event_id:"first"},
  {...events[1], event_id:"next", provider_at:"2026-10-25T00:00:00Z"},
  {...events[2], event_id:"earlier-again"},
  {...events[3], event_id:"same-day"},
];
const ungroupedDates = model(dateChanges, "none").rows;
assert.deepEqual(
  ungroupedDates.map((row) => row.type === "date" ? row.text : row.event.event_id),
  ["2026-10-26", "first", "2026-10-25", "next", "2026-10-26", "earlier-again", "same-day"],
  "Each change in the input date creates one heading, including a repeated nonconsecutive day.",
);
const groupedDates = model(dateChanges);
assert.deepEqual(groupedDates.rows.filter((row) => row.type === "date").map(({text, first}) => [text, first]),
  [["2026-10-26", true], ["2026-10-25", true]],
  "Each group starts its own date heading.");

const groupedBefore = model(events);
const oldEventKey = groupedBefore.byEvent.get("old-follow").key;
const oldDateKey = groupedBefore.rows.find((row) => row.type === "date").key;
collapsed.add("activity:follow.follow");
const appended = [...events, event("older", "4", 0, "follow.follow", "under-100")];
const closedJournal = model(appended);
const closedGroup = closedJournal.groups[0];
assert.equal(closedGroup.events.length, 4);
assert.equal(closedGroup.open, false);
assert.deepEqual(
  closedJournal.rows.slice(closedGroup.start, closedGroup.end).map((row) => row.type),
  ["group", "gap"],
);
assert.deepEqual(eventsIn(closedJournal), ["new-lost"]);
assert.equal(closedJournal.byEvent.get("older").index, -1, "Collapsed records retain logical lookup.");
assert.equal(closedJournal.byEvent.get("new-lost").position, 5, "Logical positions include collapsed events.");
assert.equal(closedJournal.byKey.get(oldEventKey), closedJournal.byEvent.get("old-follow"));
assert.equal(closedJournal.byKey.get(oldDateKey).index, -1);
assert.equal(model(appended, "account-size").groups[0].open, true, "Collapse is scoped to its lens.");
collapsed.delete("activity:follow.follow");
const reopened = model(appended);
assert.equal(reopened.rows[reopened.byEvent.get("older").index].event, appended.at(-1));
assert.deepEqual(eventsIn(reopened), ["new-follow", "old-follow", "unknown-size", "older", "new-lost"]);

const prepended = model([{...events[0], event_id:"latest"}, ...events]);
assert.equal(prepended.byKey.get(oldEventKey).event, events[2]);
assert.equal(prepended.byKey.get(oldDateKey).text, "2026-10-26");

const duplicate = {...events[0], name:"Second record with the same ID"};
const duplicateAcrossGroup = {...events[1], event_id:duplicate.event_id};
const duplicates = model([events[0], duplicate, duplicateAcrossGroup]);
const duplicateRows = duplicates.rows.filter((row) => row.type === "event");
assert.equal(new Set(duplicateRows.map((row) => row.key)).size, 3);
assert.deepEqual(duplicateRows.map((row) => row.event), [events[0], duplicate, duplicateAcrossGroup]);
assert.equal(duplicates.byEvent.get(duplicate.event_id), duplicateRows[0], "Reveal resolves the first match.");
assert.ok(duplicateRows.every((row) => duplicates.byKey.get(row.key) === row));

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
const locationsJournal = model(locationRows, locations.key);
assert.deepEqual(locationsJournal.groups.map((group) => [group.label, group.events.length]),
  [["London", 2], ["New York City", 1], ["Unknown", 1]]);
assert.deepEqual(eventsIn(locationsJournal), ["location-1", "location-3", "location-2", "unknown-location"]);

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

function checkHeights(journal) {
  const {heights, rows} = journal;
  const sizes = rows.map((_, index) => heights.height(index));
  for (const index of [1, rows.length - 1, 0, 2, 1]) {
    const measured = 1.25 * (index + 1) + 12.5;
    sizes[index] = measured;
    heights.update(index, measured);
    let top = 0;
    sizes.forEach((size, row) => {
      assert.equal(heights.prefix(row), top, "Incremental correction equals a direct sum.");
      assert.equal(heights.at(top), row, "A row starts at its exact prefix.");
      assert.equal(heights.at(top + size / 2), row, "Offsets inside a row retain their logical index.");
      top += size;
    });
    assert.equal(heights.total, top);
    assert.equal(heights.at(top), rows.length - 1);
    assert.equal(heights.at(-20), 0);
  }
}
checkHeights(reopened);

const manyLocations = Array.from({length: 5000}, (_, index) =>
  locationRecord(index, `City ${String(index).padStart(4, "0")}`));
const largeJournal = model(manyLocations, locations.key);
assert.equal(largeJournal.groups.length, 5000);
assert.equal(largeJournal.byEvent.size, 5000);
for (const index of [0, 1, 2499, 4901, 4999]) {
  const row = largeJournal.byEvent.get(`location-${index}`);
  const top = largeJournal.heights.prefix(row.index);
  assert.equal(largeJournal.rows[largeJournal.heights.at(top + 1)], row);
  const first = largeJournal.heights.at(Math.max(0, top - 480));
  const last = largeJournal.heights.at(top + 1100);
  assert.ok(last - first < 40, "A fixed viewport and overscan find a bounded slice among many group headers.");
}
