export function groupEvents(events, modules, lens) {
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
  const result = [...buckets.values()].filter((group) => group.events.length);
  return module.dynamic_buckets
    ? result.sort((a, b) =>
        a.key === "unknown"
          ? 1
          : b.key === "unknown"
            ? -1
            : a.label.localeCompare(b.label),
      )
    : result;
}
