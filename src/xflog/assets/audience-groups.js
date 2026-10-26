export function groupEvents(events, modules, lens) {
  if (lens === "none") return null;
  const module = modules.find((item) => item.key === lens && item.enabled);
  if (!module) return null;
  const groups = module.buckets.map((bucket) => ({ ...bucket, events: [] }));
  const buckets = new Map(groups.map((group) => [group.key, group]));
  for (const event of events) {
    const key = event.audience_groups?.[module.key];
    const group = buckets.get(key) || buckets.get("unknown");
    group.events.push(event);
  }
  return groups.filter((group) => group.events.length);
}
