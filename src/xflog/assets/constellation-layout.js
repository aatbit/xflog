export const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

export function flowStep(current, target, elapsed) {
  return (
    current + (target - current) * (1 - Math.exp(-clamp(elapsed, 1, 64) / 140))
  );
}

export function wheelDistance(event, viewport) {
  const delta =
    Math.abs(event.deltaX) > Math.abs(event.deltaY)
      ? event.deltaX
      : event.deltaY;
  const unit =
    event.deltaMode === 1 ? 18 : event.deltaMode === 2 ? viewport : 1;
  return clamp(delta * unit * 1.35, -viewport * 0.7, viewport * 0.7);
}

export function normalizeMotionSpeed(value) {
  const speed = Number(value);
  return Number.isFinite(speed) ? clamp(speed, 0.25, 2) : 1;
}

export function seed(value) {
  let hash = 2166136261;
  for (const letter of String(value))
    hash = Math.imul(hash ^ letter.charCodeAt(0), 16777619);
  hash = Math.imul(hash ^ (hash >>> 16), 2246822507);
  hash = Math.imul(hash ^ (hash >>> 13), 3266489909);
  hash ^= hash >>> 16;
  return (hash >>> 0) / 4294967295;
}

export function peopleFromEvents(events) {
  const people = new Map();
  for (const event of events) {
    let person = people.get(event.actor_id);
    if (!person) {
      person = { id: event.actor_id, event, events: [] };
      people.set(person.id, person);
    }
    person.events.push(event);
    if (Number(event.sequence) > Number(person.event.sequence))
      person.event = event;
  }
  return [...people.values()].sort(
    (a, b) => Number(b.event.sequence) - Number(a.event.sequence),
  );
}

export function visibleLabels(candidates, selected) {
  const visible = [];
  [...candidates]
    .sort(
      (a, b) =>
        Number(b.id === selected) - Number(a.id === selected) ||
        a.distance - b.distance,
    )
    .forEach((candidate) => {
      if (
        !visible.some(
          (other) =>
            candidate.left < other.right + 12 &&
            candidate.right > other.left - 12 &&
            candidate.top < other.bottom + 10 &&
            candidate.bottom > other.top - 10,
        )
      )
        visible.push(candidate);
    });
  return new Set(visible.map((item) => item.id));
}

export function constellationLayout({
  events,
  width,
  height,
  zoom,
  modules,
  lens,
}) {
  const people = peopleFromEvents(events);
  const module = modules.find((item) => item.key === lens && item.enabled);
  const definitions = module?.buckets || [
    { key: "all", label: "Loaded audience", tone: "neutral" },
  ];
  const groups = definitions.map((bucket) => ({ ...bucket, people: [] }));
  for (const person of people) {
    const key = module
      ? person.event.audience_groups?.[module.key] || "unknown"
      : "all";
    const group =
      groups.find((item) => item.key === key) ||
      groups.find((item) => item.key === "unknown") ||
      groups[0];
    group.people.push(person);
  }
  const occupied = groups.filter((group) => group.people.length);
  const columns = Math.min(occupied.length, width < 700 ? 2 : 3);
  const rows = Math.ceil(occupied.length / Math.max(1, columns));
  const upper = Math.min(90, height * 0.14);
  const lower = Math.max(
    upper + rows * (width < 680 ? 124 : 156),
    height - Math.min(255, height * 0.36),
  );
  const areaHeight = lower - upper;
  occupied.forEach((group, index) => {
    const row = Math.floor(index / Math.max(1, columns));
    const inRow = Math.min(columns, occupied.length - row * columns);
    group.x = width * (((index % columns) + 0.5) / inRow);
    group.y = upper + areaHeight * ((row + 0.5) / rows);
  });
  const blend = clamp((zoom - 0.25) / 0.75, 0, 1);
  const spacing = (width < 680 ? 245 : 285) * zoom;
  const worldWidth = width + Math.max(0, people.length - 1) * spacing * blend;
  const points = people.map((person, index) => {
    const group = occupied.find((item) => item.people.includes(person));
    const member = group.people.indexOf(person);
    const angle = member * 2.399963229728653;
    const radius = Math.min(width < 600 ? 44 : 76, 14 + Math.sqrt(member) * 13);
    const fitX = clamp(group.x + Math.cos(angle) * radius, 32, width - 32);
    const fitY = clamp(group.y + Math.sin(angle) * radius * 0.6, upper, lower);
    const timelineX = width / 2 + (people.length - 1 - index) * spacing;
    const timelineY = clamp(
      group.y + (seed(person.id) - 0.5) * Math.min(400, areaHeight * 0.9),
      upper + 20,
      lower - 20,
    );
    return {
      ...person,
      group: group.key,
      tone: group.tone,
      x: zoom <= 0.25 ? fitX : width / 2 + (timelineX - width / 2) * blend,
      y: fitY * (1 - Math.sqrt(blend)) + timelineY * Math.sqrt(blend),
    };
  });
  return {
    people: points,
    groups: occupied,
    width: worldWidth,
    upper,
    lower,
    overview: Boolean(module) && zoom <= 0.25,
    canPan: worldWidth > width + 0.5,
    center: (upper + lower) / 2,
  };
}
