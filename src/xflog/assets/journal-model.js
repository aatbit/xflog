import { groupEvents } from "./audience-groups.js";

function createHeightIndex(estimates) {
  const heights = Float64Array.from(estimates);
  const tree = new Float64Array(heights.length + 1);
  // Each Fenwick entry owns a suffix of the prefix ending at its index.
  for (let index = 1; index < tree.length; index++) {
    tree[index] += heights[index - 1];
    const parent = index + (index & -index);
    if (parent < tree.length) tree[parent] += tree[index];
  }
  let searchBit = 1;
  while (searchBit * 2 <= heights.length) searchBit *= 2;

  function prefix(end) {
    let offset = 0;
    for (let index = end; index > 0; index -= index & -index)
      offset += tree[index];
    return offset;
  }

  return {
    prefix,
    get total() { return prefix(heights.length); },
    height(index) { return heights[index]; },
    at(offset) {
      let index = 0;
      for (let bit = searchBit; bit > 0; bit >>= 1) {
        const next = index + bit;
        if (next < tree.length && tree[next] <= offset) {
          index = next;
          offset -= tree[next];
        }
      }
      return Math.min(index, heights.length - 1);
    },
    update(index, height) {
      const difference = height - heights[index];
      if (!difference) return;
      heights[index] = height;
      for (let parent = index + 1; parent < tree.length; parent += parent & -parent)
        tree[parent] += difference;
    },
  };
}

export function createJournalModel(events, {modules, lens, collapsed, day}) {
  const groups = groupEvents(events, modules, lens);
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

  function addEvents(records, group, visible) {
    const prefix = [group ? lens : "none", group?.key ?? null];
    const occurrences = new Map();
    function key(type, identity) {
      const scopedIdentity = JSON.stringify([type, identity]);
      const count = occurrences.get(scopedIdentity) ?? 0;
      occurrences.set(scopedIdentity, count + 1);
      return JSON.stringify([...prefix, type, identity, count]);
    }
    let prior = "";
    records.forEach((event, index) => {
      const text = day(event);
      if (text !== prior) {
        const first = index === 0;
        add({type:"date", key:key("date", text), text, group, first}, group && first ? 42 : 58, visible);
      }
      prior = text;
      const row = {
        type: "event", key: key("event", event.event_id), event, group,
        position: ++position, last: index === records.length - 1,
      };
      add(row, 102, visible);
      if (!byEvent.has(event.event_id)) byEvent.set(event.event_id, row);
    });
  }

  if (groups) {
    for (const group of groups) {
      group.start = rows.length;
      group.open = !collapsed.has(`${lens}:${group.key}`);
      add({type:"group", key:JSON.stringify([lens, group.key, "group"]), group}, 57);
      addEvents(group.events, group, group.open);
      add({type:"gap", key:JSON.stringify([lens, group.key, "gap"]), group}, 20);
      group.end = rows.length;
    }
  } else {
    addEvents(events, null, true);
  }

  return {groups, rows, byEvent, byKey, heights: createHeightIndex(estimates)};
}
