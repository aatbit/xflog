import { TIME_RANGES } from "./time-range.js";
import { compareEvents } from "./format.js";

export const HISTORY_PAGE_SIZE = 50;

export function groupSince(state, now = Date.now()) {
  if (!state.groupRange || state.groupRange === "all") return "";
  const window = state.rangeWindow;
  if (window?.period === state.groupRange && window.subject === state.subject && window.demo === state.demo) return window.start || "";
  const [, amount, unit] = TIME_RANGES.includes(state.groupRange)
    ? state.groupRange.match(/^(\d+)(h|d)$/) : [];
  return amount ? new Date(Math.floor(now / 60000) * 60000 - Number(amount) * (unit === "h" ? 3600000 : 86400000)).toISOString() : "";
}

export function historyPath(state, before = "0", options = {}) {
  const params = new URLSearchParams({
    kind: state.filter, subject: state.subject, before: String(before || "0"),
    lens: state.lens || "none", limit: String(HISTORY_PAGE_SIZE),
  });
  if (before !== "0" || options.localOnly || state.lens && state.lens !== "none")
    params.set("local_only", "true");
  if (state.since) params.set("since", state.since);
  if (state.activityKind) params.set("activity_kind", state.activityKind);
  if (options.afterRevision) params.set("after_revision", options.afterRevision);
  if (options.selected && before === "0") params.set("selected", options.selected);
  if (options.encounterRevision) params.set("encounter_revision", options.encounterRevision);
  return `/api/${state.demo ? "demo" : "timeline"}?${params}`;
}

export function mergeHistory(events) {
  const unique = new Map();
  for (const event of events)
    if (!unique.has(event.event_id)) unique.set(event.event_id, event);
  return [...unique.values()].sort(compareEvents);
}

export function historyScope(state) {
  const selection = state.status?.selection;
  return JSON.stringify([
    state.demo, state.demo ? null : state.status?.account?.id, state.subject,
    state.filter, state.lens, state.activityKind, state.groupRange, state.groupSignature,
    state.demo ? null : selection?.interactions, state.demo ? null : selection?.profile_names,
  ]);
}

function inRange(events, since) {
  if (!since) return events;
  const cutoff = Date.parse(since);
  return events.filter(event => Date.parse(event.received_at) >= cutoff);
}

function revisionPending(status, observed) {
  if (!status || status === observed) return false;
  const [events, interactions] = status.split(":");
  const [seenEvents, seenInteractions] = observed.split(":");
  const compare = (a, b) => a.length - b.length || (a < b ? -1 : Number(a !== b));
  const eventOrder = compare(events, seenEvents);
  const interactionOrder = compare(interactions, seenInteractions);
  // Compare sequence bounds losslessly. Profile and thread changes use equality.
  return eventOrder > 0 || interactionOrder > 0 || (!eventOrder && !interactionOrder);
}

const catchupPages = 3;
export function createLiveHistory({ api, read, clear, apply, change, failure, refreshInteractions, connected }) {
  let active = null, accepted = null, catchup = null, olderError = false, liveError = false;
  const report = () => change({
    phase: active?.phase,
    catchingUp: Boolean(catchup) || active?.phase === "live" || liveError ||
      Boolean(accepted?.revisionPending),
    olderError,
  });
  function cancel() {
    active?.controller.abort();
    active = null;
    report();
  }
  function start(phase) {
    active?.controller.abort();
    const ticket = {
      controller: new AbortController(), phase, scope: historyScope(read()),
    };
    active = ticket;
    report();
    return ticket;
  }
  const owns = ticket => ticket === active && connected() && historyScope(read()) === ticket.scope;
  async function page(ticket, state, before, seen, options) {
    const result = await api(historyPath(state, before, options), ticket.controller.signal);
    if (!owns(ticket)) return null;
    const next = result.next == null ? null : String(result.next);
    if (next !== null && (!next || next === "0" || next === before || seen.has(next) || !result.events.length))
      throw new Error("Saved history pagination did not advance. Try again.");
    return { ...result, next };
  }
  function syncProfiles(events, sources) {
    if (!sources.length) return events;
    const profiles = new Map();
    for (const event of sources)
      if (event.name && event.handle && !profiles.has(event.actor_id))
        profiles.set(event.actor_id, event);
    return events.map(event => {
      const profile = profiles.get(event.actor_id);
      if (!profile || profile.name === event.name && profile.handle === event.handle) return event;
      return {...event, name: profile.name, handle: profile.handle, profile_url: profile.profile_url};
    });
  }
  async function run(ticket, work) {
    try {
      await work();
    } catch (error) {
      if (owns(ticket)) {
        if (ticket.phase === "older") olderError = true;
        if (ticket.phase === "live") liveError = true;
        failure(error, ticket.phase);
      }
    } finally {
      if (active === ticket) {
        active = null;
        report();
      }
    }
  }
  async function load(prepare, preview) {
    accepted = catchup = null;
    olderError = liveError = false;
    const ticket = start(preview ? "older" : "initial");
    if (preview) apply({...preview, next: null}, "initial");
    else clear();
    await run(ticket, async () => {
      if (prepare) await prepare();
      if (!owns(ticket)) return;
      const state = read();
      const since = groupSince(state);
      const result = await page(ticket, {...state, since}, "0", new Set());
      if (!result) return;
      const revision = result.aggregate?.revision;
      if (!state.demo && !revision)
        throw new Error("Saved history snapshot revision is missing. Try again.");
      const events = inRange(mergeHistory(result.events), since);
      // The preview may come from an older snapshot. Only the scoped response owns the cursor.
      apply({...result, events}, preview ? "update" : "initial");
      accepted = {
        scope: ticket.scope, since, revision, initialRevision: revision, lastSince: since,
        cursors: new Set(result.next ? [result.next] : []),
      };
    });
  }
  async function older(retry = true) {
    const state = read();
    if (active?.phase === "initial" || active?.phase === "older" || (olderError && !retry)) return;
    if (accepted?.scope !== historyScope(state)) {
      if (olderError && state.activityKind && state.events.length)
        return load(undefined, {events: state.events, aggregate: state.aggregate});
      return;
    }
    if (!state.next) return;
    const ticket = start("older");
    await run(ticket, async () => {
      const revision = state.aggregate?.revision;
      const encounters = state.groups?.some(group => group.key === "previous-encounters" && group.enabled);
      const encounterRevision = !state.demo && encounters &&
        revision !== accepted.initialRevision ? revision : undefined;
      const result = await page(ticket, {...state, since: accepted.since}, state.next, accepted.cursors, {
        encounterRevision,
      });
      if (!result) return;
      const current = read();
      const rows = inRange(result.events, accepted.lastSince);
      // Once the ordered continuation passes the rolling cutoff, all subsequent pages are older.
      const next = rows.length === result.events.length ? result.next : null;
      // Incoming older pages normally extend the ordered tail. Live backfills can interleave.
      const known = new Set(current.events.map(event => event.event_id));
      const olderRows = mergeHistory(rows.filter(event => !known.has(event.event_id)));
      const tail = !current.events.length || !olderRows.length ||
        compareEvents(current.events.at(-1), olderRows[0]) <= 0;
      const events = tail ? current.events.concat(olderRows) : mergeHistory([...current.events, ...olderRows]);
      apply({events, next, aggregate: current.aggregate}, tail ? "older" : "update");
      if (next) accepted.cursors.add(next);
      olderError = false;
    });
  }
  async function refresh() {
    const state = read();
    if (active || !connected() || state.demo || !state.status) return;
    if (accepted?.scope !== historyScope(state)) {
      if (!olderError) return load();
      return;
    }
    const since = groupSince(state);
    const version = state.status.timeline_revision;
    const oldest = state.aggregate?.oldest_received_at;
    const empty = state.aggregate?.total_events === 0;
    const stillInRange = since === accepted.lastSince || (
      since && accepted.lastSince && Date.parse(since) >= Date.parse(accepted.lastSince) &&
      (empty || oldest && Date.parse(since) <= Date.parse(oldest))
    );
    if (!catchup && !liveError && version === accepted.revision && stillInRange) {
      if (accepted.revisionPending) {
        accepted.revisionPending = false;
        report();
      }
      return;
    }
    // A clock correction that widens a rolling range needs a new older snapshot.
    if (!catchup && since && accepted.lastSince &&
        Date.parse(since) < Date.parse(accepted.lastSince)) return load();
    const ticket = start("live");
    await run(ticket, async () => {
      const batch = catchup || {
        before: "0", seen: new Set(), since, afterRevision: accepted.revision,
      };
      const seen = new Set();
      let before = batch.before;
      let aggregate = batch.aggregate;
      const incoming = [];
      const corrections = new Map();
      let selectedRecord;
      const rows = {...state, since: batch.since};
      for (let count = 0; before && count < catchupPages; count++) {
        const result = await page(ticket, rows, before, seen, {
          afterRevision: batch.afterRevision, selected: state.selected,
        });
        if (!result) return;
        if (result.next && batch.seen.has(result.next))
          throw new Error("Saved history pagination did not advance. Try again.");
        aggregate = result.aggregate || aggregate;
        if (!aggregate?.revision)
          throw new Error("Saved history snapshot revision is missing. Try again.");
        for (const event of result.events) {
          if (event.encounter_correction) {
            const {encounter_correction, ...record} = event;
            corrections.set(record.event_id, record);
          } else incoming.push(event);
        }
        if (result.selected_event) {
          selectedRecord = result.selected_event;
          corrections.set(selectedRecord.event_id, selectedRecord);
        }
        before = result.next;
        if (before) seen.add(before);
      }
      // A profile-only revision can change cached names on loaded rows without a new event.
      let profileRows = [];
      if (batch.before === "0" && !before && !incoming.length &&
          aggregate?.profile_revision !== state.aggregate?.profile_revision) {
        const result = await page(ticket, rows, "0", new Set(), {localOnly: true});
        if (!result) return;
        profileRows = result.events;
      }
      const current = read();
      // Corrections update loaded rows. They never expand the loaded window.
      const prior = corrections.size
        ? current.events.map(event => corrections.get(event.event_id) ?? event)
        : current.events;
      const events = syncProfiles(
        inRange(mergeHistory([...incoming, ...prior]), batch.since),
        [...profileRows, ...incoming, ...(selectedRecord ? [selectedRecord] : [])],
      );
      const metadata = aggregate || current.aggregate;
      const next = metadata?.total_events === events.length ? null : current.next;
      if (events.length !== current.events.length || events.some((event, index) => event !== current.events[index]) ||
          metadata?.revision !== current.aggregate?.revision || batch.since !== accepted.lastSince || next !== current.next)
        apply({events, next, aggregate: metadata}, "update");
      if (before) {
        for (const cursor of seen) batch.seen.add(cursor);
        catchup = {...batch, before, aggregate};
      } else catchup = null;
      accepted.lastSince = batch.since;
      if (!before) {
        accepted.revision = aggregate.revision;
        accepted.revisionPending = revisionPending(current.status.timeline_revision, accepted.revision);
      }
      liveError = false;
      await refreshInteractions();
    });
  }
  function snapshot() {
    const state = read();
    if (accepted?.scope !== historyScope(state)) return null;
    const {events, next, aggregate} = state;
    return {events, next, aggregate, accepted, catchup, olderError, liveError};
  }
  function restore(saved) {
    if (saved?.accepted.scope !== historyScope(read())) return false;
    cancel();
    ({accepted, catchup, olderError, liveError} = saved);
    apply(saved, "initial");
    report();
    return true;
  }
  return { load, older, refresh, cancel, snapshot, restore, needsLoad: () => {
    const scope = historyScope(read());
    return accepted?.scope !== scope && active?.scope !== scope;
  }};
}
