export function historyCount(loadedEvents, loadedActors, aggregate) {
  const people = count => `${count} ${count === 1 ? "person" : "people"}`;
  const records = count => `${count} ${count === 1 ? "event" : "events"}`;
  const loaded = `${records(loadedEvents)} · ${people(loadedActors)}`;
  if (!aggregate) return `${loaded} loaded`;
  const saved = `${records(aggregate.total_events)} saved`;
  return loadedEvents === aggregate.total_events
    ? saved : `${loadedEvents} of ${records(aggregate.total_events)} loaded`;
}

export function groupEvents(events, modules, lens, {totals = [], summaries = false} = {}) {
  if (lens === "none") return null;
  const module = modules.find((item) => item.key === lens && item.enabled);
  if (!module) return null;
  const groups = module.buckets.map((bucket) => ({ ...bucket, events: [] }));
  const buckets = new Map(groups.map((group) => [group.key, group]));
  for (const event of events) {
    const key = event.audience_groups?.[module.key];
    const descriptor = event.audience_group_buckets?.[module.key];
    if (
      module.dynamic_buckets &&
      !buckets.has(key) &&
      typeof key === "string" &&
      /^[a-z0-9-]{1,96}$/.test(key) &&
      descriptor?.key === key &&
      typeof descriptor.label === "string" &&
      descriptor.label.trim() &&
      [...descriptor.label].length <= 160
    ) {
      buckets.set(key, {
        key,
        label: descriptor.label,
        tone: "neutral",
        events: [],
      });
    }
    const group = buckets.get(key) || buckets.get("unknown");
    group.events.push(event);
  }
  for (const total of totals) {
    const loaded = buckets.get(total.key);
    if (!summaries && !loaded?.events.length) continue;
    const bucket = loaded ?? {key: total.key, tone: total.tone, events: []};
    Object.assign(bucket, {
      label: total.label,
      eventCount: total.event_count,
      distinctActors: total.distinct_actors,
    });
    buckets.set(total.key, bucket);
  }
  const groupsWithEvents = [...buckets.values()].filter(group => group.events.length || group.eventCount);
  return module.dynamic_buckets
    ? groupsWithEvents.sort((a, b) =>
        a.key === "unknown"
          ? 1
          : b.key === "unknown"
            ? -1
            : a.label.localeCompare(b.label),
      )
    : groupsWithEvents;
}
