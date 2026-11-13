import { groupEvents } from "./audience-groups.js";

function createHeightIndex(estimates) {
  let length = estimates.length;
  let heights = Float64Array.from(estimates);
  let tree = new Float64Array(length + 1);
  // Each Fenwick entry owns a suffix of the prefix ending at its index.
  for (let index = 1; index < tree.length; index++) {
    tree[index] += heights[index - 1];
    const parent = index + (index & -index);
    if (parent < tree.length) tree[parent] += tree[index];
  }
  let searchBit = 1;
  while (searchBit * 2 <= length) searchBit *= 2;

  function prefix(end) {
    let offset = 0;
    for (let index = end; index > 0; index -= index & -index)
      offset += tree[index];
    return offset;
  }

  return {
    prefix,
    get total() { return prefix(length); },
    height(index) { return heights[index]; },
    append(values) {
      const size = length + values.length;
      if (size > heights.length) {
        const capacity = Math.max(size, heights.length * 2, 16);
        const nextHeights = new Float64Array(capacity);
        const nextTree = new Float64Array(capacity + 1);
        nextHeights.set(heights);
        nextTree.set(tree);
        heights = nextHeights;
        tree = nextTree;
      }
      for (const value of values) {
        heights[length++] = value;
        tree[length] = value + prefix(length - 1) - prefix(length - (length & -length));
      }
      while (searchBit * 2 <= length) searchBit *= 2;
    },
    at(offset) {
      let index = 0;
      for (let bit = searchBit; bit > 0; bit >>= 1) {
        const next = index + bit;
        if (next <= length && tree[next] <= offset) {
          index = next;
          offset -= tree[next];
        }
      }
      return Math.min(index, length - 1);
    },
    update(index, height) {
      const difference = height - heights[index];
      if (!difference) return;
      heights[index] = height;
      for (let parent = index + 1; parent <= length; parent += parent & -parent)
        tree[parent] += difference;
    },
  };
}

export function createJournalModel(events, {modules, lens, collapsed, day, aggregate}) {
  const groups = groupEvents(events, modules, lens, {totals: aggregate?.groups, summaries: true});
  const rows = [], estimates = [], byEvent = new Map(), byKey = new Map();
  let position = 0;

  function add(row, estimate, visible = true) {
    row.index = visible ? rows.length : -1;
    byKey.set(row.key, row);
    if (visible) {
      rows.push(row);
      estimates.push(estimate);
    }
  }

  function eventAppender(group, visible) {
    const prefix = [group ? lens : "none", group?.key ?? null];
    const occurrences = new Map();
    function key(type, identity) {
      const scopedIdentity = JSON.stringify([type, identity]);
      const count = occurrences.get(scopedIdentity) ?? 0;
      occurrences.set(scopedIdentity, count + 1);
      return JSON.stringify([...prefix, type, identity, count]);
    }
    let prior = "", last = null;
    return records => {
      if (last && records.length) last.last = false;
      records.forEach((event, index) => {
        const text = day(event);
        if (text !== prior) {
          const first = last === null && index === 0;
          add({type:"date", key:key("date", text), text, group, first}, group && first ? 42 : 58, visible);
        }
        prior = text;
        const row = {
          type: "event", key: key("event", event.event_id), event, group,
          position: ++position, last: index === records.length - 1,
        };
        if (row.last) last = row;
        add(row, 102, visible);
        if (!byEvent.has(event.event_id)) byEvent.set(event.event_id, row);
      });
    };
  }

  let appendEvents = null;
  if (groups) {
    for (const group of groups) {
      group.start = rows.length;
      group.open = group.events.length > 0 && !collapsed.has(`${lens}:${group.key}`);
      add({type:group.events.length ? "group" : "summary", key:JSON.stringify([lens, group.key, "group"]), group}, 57);
      eventAppender(group, group.open)(group.events);
      add({type:"gap", key:JSON.stringify([lens, group.key, "gap"]), group}, 20);
      group.end = rows.length;
    }
  } else {
    appendEvents = eventAppender(null, true);
    appendEvents(events);
  }

  const heights = createHeightIndex(estimates);
  estimates.length = 0;
  return {
    groups, rows, byEvent, byKey, heights,
    append: appendEvents && (records => {
      appendEvents(records);
      heights.append(estimates);
      estimates.length = 0;
    }),
  };
}
