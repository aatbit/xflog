import { TIME_RANGES } from "./time-range.js";
import { compareEvents } from "./format.js";

export function groupSince(state, now = Date.now()) {
  if (!state.groupRange || state.groupRange === "all") return "";
  const window = state.rangeWindow;
  if (window?.period === state.groupRange && window.subject === state.subject && window.demo === state.demo) return window.start || "";
  const [, amount, unit] = TIME_RANGES.includes(state.groupRange)
    ? state.groupRange.match(/^(\d+)(h|d)$/) : [];
  return amount ? new Date(Math.floor(now / 60000) * 60000 - Number(amount) * (unit === "h" ? 3600000 : 86400000)).toISOString() : "";
}

export function historyPath(state, before = "0") {
  const params = new URLSearchParams({
    kind: state.filter, subject: state.subject, before: String(before || "0"),
  });
  if (state.lens && state.lens !== "none") {
    params.set("local_only", "true");
    params.set("limit", "50");
  }
  if (state.since) {
    params.set("since", state.since);
    if (before !== "0") params.set("local_only", "true");
  }
  return `/api/${state.demo ? "demo" : "timeline"}?${params}`;
}

export function mergeHistory(events) {
  const unique = new Map();
  for (const event of events)
    if (!unique.has(event.event_id)) unique.set(event.event_id, event);
  return [...unique.values()].sort(compareEvents);
}

export async function* historyPages(api, state, before = "0") {
  const seen = new Set([String(before)]);
  while (before) {
    const page = await api(historyPath(state, before));
    yield page;
    before = page.next;
    if (before && seen.has(String(before))) throw new Error("Saved history pagination did not advance.");
    seen.add(String(before));
  }
}

export function updatedSelection(previous, selected, events) {
  const old = previous.find(event => event.event_id === selected);
  if (old && previous.find(event => event.actor_id === old.actor_id)?.event_id === selected)
    return events.find(event => event.actor_id === old.actor_id)?.event_id || events[0]?.event_id || null;
  return events.some(event => event.event_id === selected) ? selected : events[0]?.event_id || null;
}

const historyScope = state => JSON.stringify([state.status?.account?.id,
  state.status?.selection.interactions, state.status?.selection.profile_names, state.subject, state.filter, state.lens, state.groupRange]);

export function createLiveHistory({ api, read, apply, refreshInteractions }) {
  let busy = false;
  let applied = "";
  let appliedScope = "";
  return {
    async refresh() {
      const state = read();
      state.since = groupSince(state);
      if (busy || state.loading || state.demo || !state.status) return;
      const scope = historyScope(state);
      const version = `${scope}/${state.status.timeline_revision}/${state.since}`;
      if (version === applied) return;
      const generation = state.generation;
      const existing = appliedScope && appliedScope !== scope ? [] : state.events;
      const known = new Set(existing.map(event => event.event_id));
      const incoming = [];
      busy = true;
      try {
        let page;
        for await (page of historyPages(api, state)) {
          const current = read();
          if (current.generation !== generation || current.demo !== state.demo ||
              historyScope(current) !== scope) return;
          incoming.push(...page.events);
          const selectionLoaded = !state.selected || !known.has(state.selected) ||
            incoming.some(event => event.event_id === state.selected);
          if ((!known.size && (!state.lens || state.lens === "none") && !state.since) ||
              (selectionLoaded && page.events.some(event => known.has(event.event_id)))) break;
        }
        const profiles = new Map(incoming.filter(event => event.name && event.handle)
          .map(event => [event.actor_id, {name:event.name,handle:event.handle,profile_url:event.profile_url}]));
        const events = mergeHistory([...incoming, ...existing])
          .filter(event => !state.since || Date.parse(event.received_at) >= Date.parse(state.since))
          .map(event => profiles.has(event.actor_id) ? {...event,...profiles.get(event.actor_id)} : event);
        apply(events, existing.length ? state.next : page.next);
        await refreshInteractions();
        applied = version;
        appliedScope = scope;
      } finally {
        busy = false;
      }
    },
  };
}
