import { groupEvents } from "./audience-groups.js";
import { colorGroups } from "./constellation-colors.js";
import { compareEvents } from "./format.js";

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
    if (compareEvents(event, person.event) < 0)
      person.event = event;
  }
  return [...people.values()].sort(
    (a, b) => compareEvents(a.event, b.event),
  );
}

export function entriesFromEvents(events) {
  const entries = new Map();
  for (const event of events)
    if (!entries.has(event.event_id))
      entries.set(event.event_id, { id: event.event_id, event, events: [event] });
  return [...entries.values()].sort((a, b) => compareEvents(a.event, b.event));
}

function labelsOverlap(a, b) {
  return (
    a.left < b.right + 12 && a.right > b.left - 12 &&
    a.top < b.bottom + 10 && a.bottom > b.top - 10
  );
}

export function visibleLabels(candidates, selected) {
  const visible = new Map();
  [...candidates]
    .sort(
      (a, b) =>
        Number(b.id === selected) - Number(a.id === selected) ||
        a.distance - b.distance,
    )
    .forEach((candidate) => {
      const neighbors = [...visible.values()];
      const alternatives = (candidate.alternates || []).map((alternative) => {
        const direction = alternative.top < candidate.top ? -1 : 1;
        const height = alternative.bottom - alternative.top;
        let box = alternative;
        for (const other of [...neighbors].sort(
          (a, b) => direction * (a.top - b.top),
        )) {
          if (!labelsOverlap(box, other)) continue;
          const top = direction < 0 ? other.top - height - 10 : other.bottom + 10;
          box = { ...box, top, bottom: top + height };
        }
        return box;
      });
      const placement = [candidate, ...alternatives].find(
        (placement) =>
          (candidate.id === selected || (
            placement.top >= (candidate.minTop ?? -Infinity) &&
            placement.bottom <= (candidate.maxBottom ?? Infinity)
          )) &&
          !neighbors.some((other) => labelsOverlap(placement, other)),
      );
      if (placement) visible.set(candidate.id, placement);
    });
  return visible;
}

export function constellationLayout({zoom, ...options}) {
  return prepareConstellation(options)(zoom);
}

export function prepareConstellation({
  events,
  width,
  height,
  modules,
  lens,
  aggregate,
}) {
  const people = entriesFromEvents(events);
  const upper = Math.min(90, height * 0.14);
  const rowHeight = width < 680 ? 124 : 156;
  const availableColumns = width < 700 ? 2 : 3;
  const availableRows = Math.max(
    1,
    Math.floor((height - upper - Math.max(80, upper + 1)) / rowHeight),
  );
  const rawBuckets = groupEvents(events, modules, lens, {totals: aggregate?.groups, summaries: true});
  const module = modules.find(module => module.key === lens && module.enabled);
  const groups = rawBuckets
    ? colorGroups(rawBuckets, module).map(({ events, ...bucket }) => ({
        ...bucket,
        people: entriesFromEvents(events),
        personCount: peopleFromEvents(events).length,
      }))
    : [{ key: "all", label: "Loaded audience", tone: "neutral", people }];
  const occupied = groups.filter(group => group.people.length);
  const positions = new Map();
  occupied.forEach((group, groupIndex) => {
    group.people.forEach((person, member) => {
      positions.set(person, { group, member, groupIndex });
    });
  });
  const ordered = rawBuckets ? [...occupied].reverse().flatMap(group => group.people) : people;
  const placements = ordered.map(person => {
    const { group, member, groupIndex } = positions.get(person);
    const angle = member * 2.399963229728653;
    const radius = Math.min(width < 600 ? 44 : 76, 14 + Math.sqrt(member) * 13);
    return {
      group, groupIndex,
      dx: Math.cos(angle) * radius,
      dy: Math.sin(angle) * radius * 0.6,
      drift: seed(person.id) - 0.5,
    };
  });
  // Scene bindings keep these point identities while zoom changes their coordinates.
  const geometry = {
    people: ordered.map((person, index) => {
      const {group} = placements[index];
      return {...person, group: group.key, tone: group.tone, color: group.color};
    }),
    groups: occupied,
    overviewGroups: groups,
    grouped: rawBuckets !== null,
    upper,
  };
  const grouped = geometry.grouped;
  const count = geometry.people.length;
  return (zoom) => {
    const overview = grouped && zoom <= 0.25;
    const positioned = overview ? groups : occupied;
    const columns = overview
      ? Math.min(positioned.length, Math.max(availableColumns, Math.ceil(positioned.length / availableRows)))
      : Math.min(positioned.length, availableColumns);
    const overviewWidth = grouped ? Math.max(width, columns * 160) : width;
    const rows = zoom <= 0.25 ? Math.ceil(positioned.length / Math.max(1, columns)) : 1;
    const lower = Math.max(
      upper + rows * rowHeight,
      height - Math.min(255, height * 0.36),
    );
    const areaHeight = lower - upper;
    positioned.forEach((group, index) => {
      const row = Math.floor(index / Math.max(1, columns));
      const inRow = Math.min(columns, positioned.length - row * columns);
      group.x = (zoom <= 0.25 ? overviewWidth : width) * (((index % columns) + 0.5) / inRow);
      group.y = zoom <= 0.25 ? upper + areaHeight * ((row + 0.5) / rows) : upper + areaHeight / 2;
    });
    const blend = clamp((zoom - 0.25) / 0.75, 0, 1);
    const spacing = (width < 680 ? 245 : 285) * zoom;
    const groupGap = grouped ? width * 0.5 * blend : 0;
    const worldWidth = zoom <= 0.25 ? overviewWidth : width + Math.max(0, count - 1) * spacing * blend +
      Math.max(0, occupied.length - 1) * groupGap;
    const blendY = Math.sqrt(blend);
    geometry.people.forEach((point, index) => {
      const { group, groupIndex, dx, dy, drift } = placements[index];
      const fitX = clamp(group.x + dx, 32, (zoom <= 0.25 ? overviewWidth : width) - 32);
      const fitY = clamp(group.y + dy, upper, lower);
      const timelineX = width / 2 + (count - 1 - index) * spacing;
      const groupOffset = groupIndex * groupGap;
      const timelineY = clamp(
        group.y + drift * Math.min(400, areaHeight * 0.9),
        upper + 20,
        lower - 20,
      );
      point.x = zoom <= 0.25 ? fitX : width / 2 + (timelineX - width / 2) * blend + groupOffset;
      point.y = fitY * (1 - blendY) + timelineY * blendY;
    });
    return Object.assign(geometry, {
      width: worldWidth,
      lower,
      overview,
      canPan: worldWidth > width + 0.5,
      center: (upper + lower) / 2,
    });
  };
}
