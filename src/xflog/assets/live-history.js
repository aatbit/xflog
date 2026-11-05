export function historyPath(state, before = "0") {
  return `/api/${state.demo ? "demo" : "timeline"}?${new URLSearchParams({
    kind: state.filter, subject: state.subject, before: String(before || "0"),
  })}`;
}

export function updatedSelection(previous, selected, events) {
  const old = previous.find(event => event.event_id === selected);
  if (old && previous.find(event => event.actor_id === old.actor_id)?.event_id === selected)
    return events.find(event => event.actor_id === old.actor_id)?.event_id || events[0]?.event_id || null;
  return events.some(event => event.event_id === selected) ? selected : events[0]?.event_id || null;
}

const historyScope = state => JSON.stringify([state.status?.account?.id,
  state.status?.selection.interactions, state.status?.selection.profile_names, state.subject, state.filter]);

export function createLiveHistory({ api, read, apply, refreshInteractions }) {
  let busy = false;
  let applied = "";
  let appliedScope = "";
  return {
    async refresh() {
      const state = read();
      if (busy || state.demo || !state.status) return;
      const scope = historyScope(state);
      const version = `${scope}/${state.status.timeline_revision}`;
      if (version === applied) return;
      const generation = state.generation;
      const existing = appliedScope && appliedScope !== scope ? [] : state.events;
      const known = new Set(existing.map(event => event.event_id));
      const incoming = [];
      let before = "0";
      busy = true;
      try {
        let page;
        do {
          page = await api(historyPath(state, before));
          const current = read();
          if (current.generation !== generation || current.demo !== state.demo ||
              historyScope(current) !== scope) return;
          incoming.push(...page.events);
          if (!known.size || page.events.some(event => known.has(event.event_id))) break;
          before = page.next;
        } while (before);
        const unique = new Map();
        for (const event of [...incoming, ...existing])
          if (!unique.has(event.event_id)) unique.set(event.event_id, event);
        const profiles = new Map(incoming.filter(event => event.name && event.handle)
          .map(event => [event.actor_id, {name:event.name,handle:event.handle,profile_url:event.profile_url}]));
        const events = [...unique.values()].map(event => profiles.has(event.actor_id)
          ? {...event,...profiles.get(event.actor_id)} : event);
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
