import { eventTone } from "./format.js";
import { createJournalModel } from "./journal-model.js";

export function createJournal({
  element,
  escape: esc,
  date,
  time,
  displayDate,
  label,
  initials,
  onOpen,
  onNearEnd = () => {},
}) {
  const collapsed = new Set();
  let track, model, events, options, selected, frame = 0;
  let savedAnchor = null, inset = 0, width = 0;
  let revealRow = null, revealScrollTop = 0;
  let measured = new Map();
  const mounted = new Map(), groups = new Map(), observed = new Map();
  const observer = new ResizeObserver(measure);

  function eventMarkup(row) {
    const event = row.event;
    const tone = eventTone(event);
    const lost = tone === "negative";
    return `<article aria-label="Event ${row.position} of ${events.length}" class="event ${row.group && row.last ? "journal-last-event " : ""}${lost ? "lost" : tone === "positive" ? "gain" : "neutral"}"><span class="event-dot" aria-hidden="true"></span><button type="button" class="event-button" data-event="${esc(event.event_id)}" aria-pressed="${selected === event.event_id}"><span class="avatar" aria-hidden="true">${esc(initials(event))}</span><span class="event-identity"><span class="event-name">${esc(event.name || event.handle || "X account")}</span><span class="event-handle">${esc(event.handle ? "@" + event.handle : "ID " + event.actor_id)}</span></span><span class="event-meta"><span class="event-kind"><span aria-hidden="true">${lost ? "↘" : tone === "neutral" ? "·" : "↗"}</span>${esc(label(event))}</span><span class="event-time">${esc(time.format(displayDate(event)))}${event.provider_at ? "" : " · received"}</span></span></button></article>`;
  }

  function mountGroup(group) {
    const node = document.createElement("details");
    node.className = `journal-group ${group.tone || ""}`;
    node.dataset.group = group.key;
    node.open = group.open;
    node.innerHTML = `<summary><span class="journal-group-name">${esc(group.label)}</span> <span class="journal-group-count">${group.events.length} ${group.events.length === 1 ? "event" : "events"}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg></summary><div class="journal-group-content"></div>`;
    groups.set(group, node);
    return node;
  }

  function mountRow(row) {
    let node;
    if (row.type === "group") {
      node = groups.get(row.group).firstElementChild;
    } else if (row.type === "date") {
      node = document.createElement("div");
      node.className = row.first && row.group ? "date-group journal-first-date" : "date-group";
      node.textContent = row.text;
    } else {
      const template = document.createElement("template");
      template.innerHTML = eventMarkup(row);
      node = template.content.firstElementChild;
    }
    node.dataset.journalRow = row.key;
    mounted.set(row, node);
    observed.set(node, row);
    observer.observe(node, {box: "border-box"});
    return node;
  }

  function unmountRow(row, node) {
    observer.unobserve(node);
    observed.delete(node);
    mounted.delete(row);
    if (row.type !== "group") node.remove();
  }

  function locate(key) {
    const node = key?.closest?.("[data-journal-row]");
    const row = model?.byKey.get(node?.dataset.journalRow);
    return row && mounted.get(row) === node ? row : null;
  }

  function anchor() {
    if (!model?.rows.length) return null;
    const offset = element.scrollTop - inset;
    let index = model.heights.at(offset);
    const row = model.rows[index];
    // If a date heading is at the edge, anchor its first event as well.
    if (row.type === "date" && model.rows[index + 1]?.type === "event") index++;
    const current = model.rows[index];
    return {
      key: current.key, identity: current.event?.event_id,
      offset: offset - model.heights.prefix(index), top: element.scrollTop,
    };
  }

  function restoreAnchor(previous) {
    if (!previous) return;
    const row = model.byKey.get(previous.key) ??
      (previous.identity === undefined ? null : model.byEvent.get(previous.identity));
    element.scrollTop = row && row.index >= 0
      ? inset + model.heights.prefix(row.index) + previous.offset
      : previous.top;
  }

  function setTop(node, top) {
    const value = `${top}px`;
    if (node.style.top !== value) node.style.top = value;
  }

  function placeMounted() {
    track.style.height = `${model.heights.total}px`;
    for (const [group, node] of groups) {
      const top = model.heights.prefix(group.start);
      setTop(node, top);
      node.style.height = `${model.heights.prefix(group.end) - top - 20}px`;
    }
    for (const [row, node] of mounted) {
      if (row.type === "group") continue;
      const base = row.group ? model.heights.prefix(row.group.start) + 1 : 0;
      setTop(node, model.heights.prefix(row.index) - base);
    }
  }

  function renderWindow(pinned = locate(document.activeElement)) {
    if (!track?.isConnected || !element.clientHeight) return;
    const overscan = Math.min(400, element.clientHeight);
    const top = element.scrollTop - inset;
    const from = model.heights.at(top - overscan);
    const to = model.heights.at(top + element.clientHeight + overscan);
    const wanted = new Set();
    const wantedGroups = new Set();
    function include(row) {
      if (!row) return;
      if (row.group && !wantedGroups.has(row.group)) {
        wantedGroups.add(row.group);
        wanted.add(model.rows[row.group.start]);
      }
      if (row.type !== "gap") wanted.add(row);
    }
    for (let index = Math.max(0, from); index <= to; index++) include(model.rows[index]);
    if (pinned?.index >= 0) include(pinned);

    for (const [row, node] of mounted)
      if (!wanted.has(row)) unmountRow(row, node);
    for (const [group, node] of groups) {
      if (!wantedGroups.has(group)) {
        node.remove();
        groups.delete(group);
      }
    }

    // Insert new rows in logical DOM order without moving already mounted focused nodes.
    const tails = new Map();
    const ordered = [...wanted].sort((a, b) => b.index - a.index);
    for (const row of ordered) {
      let groupNode;
      if (row.group) groupNode = groups.get(row.group) ?? mountGroup(row.group);
      const node = mounted.get(row) ?? mountRow(row);
      const parent = row.group && row.type !== "group" ? groupNode.lastElementChild : track;
      const child = row.type === "group" ? groupNode : node;
      if (child.parentNode !== parent) parent.insertBefore(child, tails.get(parent) ?? null);
      tails.set(parent, child);
    }
    placeMounted();
  }

  function paintJournal() {
    frame = 0;
    if (revealRow && element.scrollTop !== revealScrollTop) revealRow = null;
    renderWindow();
  }

  function queue() {
    if (track?.isConnected && !frame) frame = requestAnimationFrame(paintJournal);
  }

  function measure(entries) {
    if (!track?.isConnected) return;
    const previous = anchor();
    let changed = false;
    for (const entry of entries) {
      if (entry.target === element) {
        const nextWidth = track.clientWidth;
        if (width !== nextWidth) {
          width = nextWidth;
          // Keep last-known heights as estimates until those rows are visited again.
          measured.clear();
        }
        inset = track.offsetTop;
        queue();
        continue;
      }
      const row = observed.get(entry.target);
      if (!row || !track.contains(entry.target)) continue;
      const height = entry.borderBoxSize?.[0]?.blockSize ?? entry.target.offsetHeight;
      if (!height) continue;
      const occupied = height + (row.type === "event" ? 12 : row.type === "group" ? 1 : 0);
      measured.set(row.key, {row, height: occupied});
      if (model.heights.height(row.index) !== occupied) {
        model.heights.update(row.index, occupied);
        changed = true;
      }
    }
    if (changed) {
      const keepRevealed = revealRow && element.scrollTop === revealScrollTop;
      placeMounted();
      if (keepRevealed) alignRow(revealRow);
      else restoreAnchor(previous);
      queue();
    }
  }

  function release() {
    cancelAnimationFrame(frame);
    frame = 0;
    observer.disconnect();
    mounted.clear();
    groups.clear();
    observed.clear();
    track?.remove();
    track = model = events = options = revealRow = null;
    measured.clear();
  }

  function restoreMeasurements(previous) {
    for (const [key, {row, height}] of previous) {
      const next = model.byKey.get(key);
      if (!next || !sameHeightInputs(row, next)) continue;
      measured.set(key, {row: next, height});
      if (next.index >= 0) model.heights.update(next.index, height);
    }
  }

  function sameHeightInputs(row, next) {
    if (row.type === "event") {
      const fields = ["name", "handle", "actor_id", "kind", "received_at", "provider_at"];
      return row.event === next.event || fields.every(field => row.event[field] === next.event[field]);
    }
    if (row.type === "group")
      return row.group.label === next.group.label && row.group.events.length === next.group.events.length;
    return row.first === next.first;
  }

  function render(nextEvents, nextOptions) {
    const previous = anchor() ?? savedAnchor;
    const focused = locate(document.activeElement);
    const previousWidth = width;
    const previousHeights = measured;
    measured = new Map();
    savedAnchor = null;
    release();
    events = nextEvents;
    options = nextOptions;
    selected = options.selected;
    model = createJournalModel(events, {...options, collapsed, day: event => date.format(displayDate(event))});
    track = document.createElement("div");
    track.className = "journal-window";
    element.replaceChildren(track);
    inset = track.offsetTop;
    width = track.clientWidth;
    if (width === previousWidth) restoreMeasurements(previousHeights);
    track.style.height = `${model.heights.total}px`;
    restoreAnchor(previous);
    if (!previous) element.scrollTop = 0;
    observer.observe(element);
    const row = focused && (model.byKey.get(focused.key) ?? model.byEvent.get(focused.event?.event_id));
    renderWindow(row);
    if (focused) (control(row) ?? element).focus({preventScroll: true});
  }

  function alignRow(row) {
    const {heights} = model;
    const top = inset + heights.prefix(row.index);
    const bottom = top + heights.height(row.index);
    const sticky = row.group && row.type !== "group" ? heights.height(row.group.start) : 0;
    const visibleTop = element.scrollTop + (sticky ? inset + sticky : 0);
    const visibleBottom = element.scrollTop + element.clientHeight;
    const earliest = top - (sticky ? inset + sticky : 0);
    if (top < visibleTop) element.scrollTop = earliest;
    else if (bottom > visibleBottom)
      element.scrollTop = Math.min(earliest, bottom - element.clientHeight);
    revealScrollTop = element.scrollTop;
  }

  function scrollToRow(row) {
    revealRow = row;
    alignRow(row);
    renderWindow();
  }

  function reveal(identity) {
    let row = model?.byEvent.get(identity);
    if (!row) return;
    if (row.index < 0) {
      collapsed.delete(`${options.lens}:${row.group.key}`);
      render(events, {...options, selected});
      row = model.byEvent.get(identity);
    }
    scrollToRow(row);
  }

  function setGroupOpen(row, open) {
    const key = `${options.lens}:${row.group.key}`;
    if (open) collapsed.delete(key);
    else collapsed.add(key);
    const inGroup = model.byKey.get(anchor()?.key)?.group === row.group;
    render(events, {...options, selected});
    if (!open && inGroup) scrollToRow(model.byKey.get(row.key));
  }

  function click(event) {
    const target = event.target.closest("button[data-event], summary");
    const row = locate(target);
    if (row?.type === "event") onOpen(row.event.event_id);
    else if (row?.type === "group" && !event.defaultPrevented) {
      // Commit disclosure before a scroll frame can unmount the summary.
      event.preventDefault();
      setGroupOpen(row, !row.group.open);
    }
  }

  function toggle(event) {
    const node = event.target;
    if (!node.matches("details[data-group]")) return;
    const row = locate(node.firstElementChild);
    if (row && node.open !== row.group.open) setGroupOpen(row, node.open);
  }

  function control(row) {
    const node = mounted.get(row);
    return row?.type === "event" ? node?.querySelector("button") : node;
  }

  function keydown(event) {
    if (event.key !== "Tab" || event.altKey || event.ctrlKey || event.metaKey) return;
    const current = locate(event.target);
    if (!current) return;
    const direction = event.shiftKey ? -1 : 1;
    for (let index = current.index + direction; model.rows[index]; index += direction) {
      const row = model.rows[index];
      if (row.type !== "group" && row.type !== "event") continue;
      event.preventDefault();
      scrollToRow(row);
      control(row)?.focus({preventScroll: true});
      return;
    }
  }

  function scroll() {
    if (!track?.isConnected) return;
    queue();
    if (element.scrollTop + element.clientHeight >= element.scrollHeight - 80) onNearEnd();
  }

  const listeners = [
    ["scroll", scroll, {passive: true}],
    ["click", click],
    ["toggle", toggle, true],
    ["keydown", keydown],
    ["focusout", queue],
  ];
  listeners.forEach(([type, handler, settings]) => element.addEventListener(type, handler, settings));

  return {
    render,
    reveal,
    select(identity) {
      if (selected === identity) return;
      selected = identity;
      for (const [row, node] of mounted)
        if (row.type === "event")
          node.querySelector("button").setAttribute("aria-pressed", String(row.event.event_id === selected));
    },
    clear({remember = false} = {}) {
      savedAnchor = remember ? anchor() ?? savedAnchor : null;
      release();
    },
    destroy() {
      savedAnchor = null;
      collapsed.clear();
      release();
      listeners.forEach(([type, handler, settings]) => element.removeEventListener(type, handler, settings));
    },
  };
}
