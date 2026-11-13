import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const base = pathToFileURL(process.argv[2] + "/");
const { createLiveHistory, historyPath, groupSince, mergeHistory } = await import(new URL("live-history.js", base));
const { eventLabel, eventTone } = await import(new URL("format.js", base));
const { peopleFromEvents } = await import(new URL("constellation-layout.js", base));

const event = (id, received_at = new Date(Date.UTC(2026, 10, 5, 10, 0, id)).toISOString()) => ({
  event_id: `timeline:interaction:${id}`, kind: "interaction.replies", actor_id: "222",
  sequence: -id, received_at,
});
const ids = rows => rows.map(item => -item.sequence);
const scope = {
  demo: false, subject: "followers", filter: "all", lens: "none", groupRange: "all",
  status: { account: {id:"111"}, timeline_revision: "0:10::", selection: {interactions:{replies:true}} },
};
const aggregate = (revision, total_events, oldest_received_at, profile_revision = "") =>
  ({revision, total_events, oldest_received_at, profile_revision, distinct_actors: 1, groups: []});
function fixture(respond) {
  const state = {...scope, events: [], next: null, aggregate: null, selected: null};
  const calls = [], errors = [];
  let status, refreshed = 0;
  const feed = createLiveHistory({
    read: () => state, connected: () => state.connected !== false,
    api: (path, signal) => {
      const params = new URL(path, "http://local").searchParams;
      calls.push({params, signal});
      return respond(params);
    },
    clear: () => Object.assign(state, {events: [], next: null, aggregate: null, selected: null}),
    apply: result => Object.assign(state, result),
    change: value => { status = value; },
    failure: (error, phase) => errors.push([error.message, phase]),
    refreshInteractions: async () => { refreshed++; },
  });
  return {
    feed, state, calls, errors, get status() { return status; }, get refreshed() { return refreshed; },
    revision: timeline_revision => { state.status = {...state.status, timeline_revision}; },
  };
}
function deferred() {
  let resolve;
  const promise = new Promise(accept => { resolve = accept; });
  return {promise, resolve};
}

const initial = {events: [event(10), event(9)], next: "old-a", aggregate: aggregate("0:10::", 5, event(6).received_at)};
const held = deferred();
let olderReply = held.promise;
const manual = fixture(params => params.get("before") === "0" ? initial : olderReply);
await manual.feed.load();
assert.equal(manual.calls.length, 1, "First render accepts one page");
assert.deepEqual(ids(manual.state.events), [10, 9]);
assert.equal(manual.state.aggregate.total_events, 5);
assert.equal(manual.state.next, "old-a");
manual.state.selected = event(9).event_id;
const older = manual.feed.older();
await manual.feed.older();
await manual.feed.refresh();
assert.equal(manual.calls.length, 2, "Near-end and poll cannot duplicate an active older request");
assert.equal(manual.status.phase, "older");
held.resolve({events: [event(9), event(8)], next: "old-b"});
await older;
assert.deepEqual(ids(manual.state.events), [10, 9, 8]);
assert.equal(manual.state.selected, event(9).event_id);
assert.equal(manual.state.next, "old-b");
assert.equal(manual.calls[1].params.get("local_only"), "true");
olderReply = {events: [event(7)], next: "old-a"};
await manual.feed.older();
assert.match(manual.errors.at(-1)[0], /did not advance/);
assert.equal(manual.state.next, "old-b", "A cycle cannot consume the accepted continuation");
assert.deepEqual(ids(manual.state.events), [10, 9, 8]);
olderReply = {events: [event(7), event(6)], next: null};
const beforeRetry = manual.calls.length;
await manual.feed.older(false);
assert.equal(manual.calls.length, beforeRetry, "A near-end signal cannot retry a failed page by itself");
await manual.feed.older();
assert.equal(manual.state.next, null);
assert.deepEqual(ids(manual.state.events), [10, 9, 8, 7, 6]);
assert.equal(manual.status.olderError, false);

for (const update of [
  {filter:"lost"}, {subject:"subscriptions"}, {lens:"activity"}, {groupRange:"24h"},
  {demo:true}, {groupSignature:"new"}, {status:{...scope.status, account:{id:"333"}}},
  {status:{...scope.status, selection:{interactions:{replies:false}}}},
]) {
  const old = deferred();
  const race = fixture(params => params.get("before") === "old-a" ? old.promise
    : { ...initial, events: initial.events.map(row => ({...row, received_at: new Date().toISOString()})) });
  await race.feed.load();
  const request = race.feed.older();
  Object.assign(race.state, update);
  await race.feed.load();
  assert.equal(race.calls[1].signal.aborted, true);
  old.resolve({events:[event(8)],next:null});
  await request;
  assert.deepEqual(ids(race.state.events), [10, 9]);
}

const burst = Array.from({length: 7}, (_, index) => event(17 - index));
let rejectBatch = true, profileOnly = false, expire = false;
const live = fixture(params => {
  const before = params.get("before");
  if (!params.has("after_revision") && before === "0") return profileOnly
    ? { ...initial, events: initial.events.map(row => ({...row, name:"Maya",handle:"maya",profile_url:"https://x.com/maya"})) }
    : initial;
  if (before === "old-a") return {events:[event(8),event(7)],next:"old-b"};
  if (profileOnly || expire) return {
    events: [], next: null, selected_event: profileOnly ? {...event(9),post_text:"Newly saved thread text"} : null,
    aggregate: aggregate(profileOnly ? "0:17:profile:thread" : "0:17::", expire ? 0 : 12, null,
      profileOnly ? "profile" : ""),
  };
  assert.equal(params.get("after_revision"), "0:10::");
  const offset = before === "0" ? 0 : Number(before.slice(6));
  if (offset === 4 && rejectBatch) throw new Error("Local database unavailable");
  const events = burst.slice(offset, offset + 2);
  return {
    events, next: offset + 2 < burst.length ? `delta-${offset+2}` : null,
    aggregate: offset === 0 ? aggregate("0:17::", 12, event(6).received_at) : null,
  };
});
await live.feed.refresh();
assert.equal(live.calls.length, 1, "Live initialization is bounded too");
assert.equal(live.state.next, "old-a");
live.revision("0:17::");
await live.feed.refresh();
assert.equal(live.calls.length, 4);
assert.deepEqual(ids(live.state.events), [10, 9], "Failure does not commit part of a live batch");
assert.equal(live.errors.at(-1)[1], "live");
rejectBatch = false;
await live.feed.refresh();
assert.equal(live.calls.length, 7);
assert.equal(live.status.catchingUp, true);
assert.deepEqual(ids(live.state.events), [17,16,15,14,13,12,10,9]);
await live.feed.older();
assert.equal(live.state.next, "old-b");
assert.equal(live.calls.at(-1).params.get("after_revision"), null);
await live.feed.refresh();
assert.equal(live.calls.at(-1).params.get("before"), "delta-6");
assert.equal(live.status.catchingUp, false);
assert.equal(live.state.next, "old-b", "Live catch-up preserves the latest accepted older cursor");
assert.deepEqual(ids(live.state.events), [17,16,15,14,13,12,11,10,9,8,7]);
assert.equal(live.state.aggregate.total_events, 12);
const callCount = live.calls.length;
await live.feed.refresh();
assert.equal(live.calls.length, callCount, "Unchanged revision does no history work");
live.state.selected = event(9).event_id;
profileOnly = true;
live.revision("0:17:profile:thread");
await live.feed.refresh();
assert.equal(live.calls.at(-2).params.get("selected"), live.state.selected);
assert.equal(live.calls.at(-1).params.get("local_only"), "true");
assert.equal(live.state.events.find(row => row.event_id === live.state.selected).post_text, "Newly saved thread text");
assert.ok(live.state.events.every(row => row.handle === "maya"), "Cached names update previously loaded rows");
live.state.demo = true;
await live.feed.refresh();
assert.equal(live.refreshed, 3, "Live history leaves demo rows alone");

const liveHold = deferred();
const priority = fixture(params => params.has("after_revision") ? liveHold.promise
  : params.get("before") === "0" ? initial : {events:[event(8)],next:null});
await priority.feed.load();
priority.revision("0:11::");
const pending = priority.feed.refresh();
await priority.feed.older();
assert.equal(priority.calls[1].signal.aborted, true, "Manual older navigation can preempt a live read");
liveHold.resolve({events:[event(11)],next:null});
await pending;
assert.deepEqual(ids(priority.state.events), [10,9,8]);

const withEncounter = (id, bucket) => ({
  ...event(id), audience_groups: {"previous-encounters": bucket},
});
const corrected = id => ({...withEncounter(id, "seen-before"), encounter_correction: true});
const encounter = fixture(params => {
  const before = params.get("before");
  if (!params.has("after_revision")) {
    if (before === "0") return {...initial, events: [withEncounter(10, "first-appearance"), event(9)]};
    assert.equal(params.get("encounter_revision"), "0:13::");
    return before === "old-a"
      ? {events:[withEncounter(8, "seen-before")], next:"old-b"}
      : {events:[withEncounter(7, "seen-before")], next:null};
  }
  return ({
    "0": {events:[event(13)], next:"delta-1", aggregate:aggregate("0:13::", 8, event(6).received_at)},
    "delta-1": {events:[event(12)], next:"delta-2"},
    "delta-2": {events:[event(11)], next:"delta-3"},
    "delta-3": {events:[corrected(10), corrected(8), corrected(7)], next:null},
  })[before];
});
encounter.state.lens = "previous-encounters";
encounter.state.groups = [{key: "previous-encounters", enabled: true}];
await encounter.feed.load();
encounter.state.selected = event(9).event_id;
encounter.revision("0:13::");
await encounter.feed.refresh();
assert.equal(encounter.status.catchingUp, true);
await encounter.feed.older();
await encounter.feed.refresh();
const bucket = (id) => encounter.state.events.find(row => row.event_id === event(id).event_id)
  ?.audience_groups?.["previous-encounters"];
assert.equal(bucket(10), "seen-before", "Live correction updates a loaded, unselected event");
assert.equal(bucket(8), "seen-before", "A page accepted between live batches uses the current context");
assert.equal(bucket(7), undefined, "A correction cannot load an unvisited row");
assert.equal(encounter.state.next, "old-b", "Live corrections do not take over the older cursor");
assert.equal(encounter.state.selected, event(9).event_id);
assert.equal(encounter.state.events.some(row => row.encounter_correction), false);
await encounter.feed.older();
assert.equal(bucket(7), "seen-before");

const range = fixture(params => params.has("after_revision")
  ? {events:[],next:null,aggregate:aggregate("0:10::",0,null)}
  : {events:[event(10)],next:"expired-cursor",aggregate:aggregate("0:10::",2,event(9).received_at)});
range.state.groupRange = "24h";
range.state.rangeWindow = {period:"24h",subject:"followers",demo:false,start:"2026-11-05T10:00:00Z"};
await range.feed.load();
range.state.rangeWindow.start = "2026-11-05T10:00:05Z";
await range.feed.refresh();
assert.equal(range.calls.length, 1, "A moving cutoff before the oldest match does not re-count history");
range.state.rangeWindow.start = "2026-11-05T10:01:00Z";
await range.feed.refresh();
assert.equal(range.state.events.length, 0, "Expired rows disappear even without a new timeline revision");
assert.equal(range.state.next, null, "An exact empty aggregate exhausts the expired continuation");

const disconnected = deferred();
const detached = fixture(() => disconnected.promise);
const loading = detached.feed.load();
detached.state.connected = false;
detached.feed.cancel();
disconnected.resolve(initial);
await loading;
assert.deepEqual(detached.state.events, []);
assert.equal(detached.calls[0].signal.aborted, true);

assert.match(historyPath(scope), /^\/api\/timeline\?/);
assert.match(historyPath({...scope,demo:true}), /^\/api\/demo\?/);
const query = state => new URL(historyPath(state), "http://local").searchParams;
assert.equal(query(scope).has("local_only"), false);
assert.equal(query({...scope,lens:"activity"}).get("local_only"), "true");
assert.equal(query({...scope,lens:"activity"}).get("lens"), "activity");
assert.equal(query(scope).get("limit"), "50");
for (const [range, hours] of [["1h",1],["6h",6],["12h",12],["3d",72],["24h",24]]) {
  const end = Date.parse("2026-11-06T10:00:00Z");
  assert.equal(Date.parse(groupSince({...scope,groupRange:range},end)), end-hours*3600000);
}
assert.equal(groupSince(scope), "");
const follow = {...event(1),event_id:"timeline:event:1",sequence:1,kind:"follow.follow"};
const reply = event(1);
assert.deepEqual(mergeHistory([reply,follow,reply]), [follow,reply], "Mixed ties keep source order and deduplicate");
const wholeSecond = event(1, "2026-11-05T10:00:01+00:00");
const fraction = event(2, "2026-11-05T10:00:01.100000+00:00");
assert.deepEqual(mergeHistory([wholeSecond,fraction]), [fraction,wholeSecond],
  "Client ordering matches the SQLite receipt key across optional fractional seconds");
assert.equal(peopleFromEvents([follow,event(2)])[0].event.sequence, -2);
assert.equal(eventLabel(reply), "Replied to you");
assert.equal(eventLabel({...reply,kind:"interaction.likes_given"}), "You liked their post");
assert.equal(eventTone(reply), "neutral");
assert.equal(eventTone({kind:"follow.unfollow"}), "negative");
