const HUES = 11;

export function colorGroups(groups, module) {
  if (!module) return groups;
  const canonical = module.buckets.filter(bucket => bucket.key !== "unknown").map(bucket => bucket.key);
  const used = new Set();
  const styles = new Map();
  for (const group of [...groups].sort((a, b) => a.key.localeCompare(b.key))) {
    if (group.color) {
      styles.set(group.key, { color: group.color, dash: group.dash });
      continue;
    }
    if (group.key === "unknown" || group.key === "overview-more") {
      styles.set(group.key, {
        color: `var(--constellation-${group.key})`,
        dash: group.key === "unknown" ? "3 4" : "1 5",
      });
      continue;
    }
    const fixed = canonical.indexOf(group.key);
    let index = fixed >= 0 ? fixed : 0;
    if (fixed < 0) {
      for (const letter of group.key) index = (index * 31 + letter.charCodeAt(0)) % HUES;
    }
    while (used.has(index)) index++;
    used.add(index);
    styles.set(group.key, {
      color: index < HUES ? `var(--constellation-${index})` : `hsl(${((index - HUES) * 137.508) % 360} 52% 72%)`,
      dash: "",
    });
  }
  return groups.map(group => ({ ...group, ...styles.get(group.key) }));
}

export function groupDescription(group) {
  const actions = group.eventCount ?? group.people.length;
  const people = group.distinctActors ?? group.personCount;
  const total = `${actions} ${actions === 1 ? "action" : "actions"} · ${people} ${people === 1 ? "person" : "people"}`;
  return actions !== group.people.length || people !== group.personCount
    ? `${total} saved · ${group.people.length} ${group.people.length === 1 ? "action" : "actions"} loaded` : total;
}

export function groupKey(groups, escape) {
  return groups.map(group => `<span class="constellation-key-item" role="listitem" tabindex="0" title="${escape(groupDescription(group))}" aria-label="${escape(group.label)}, ${escape(groupDescription(group))}"><svg viewBox="0 0 22 12" aria-hidden="true" style="color:${group.color}"><path d="M1 6H21" stroke-dasharray="${group.dash}"/></svg><span class="constellation-key-label">${escape(group.label)}</span><span class="constellation-key-count">${group.eventCount ?? group.people.length}</span></span>`).join("");
}
