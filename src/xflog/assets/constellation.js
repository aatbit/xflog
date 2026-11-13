import { activityIcon } from "./activity-icon.js";
import { postPreview } from "./post-preview.js";
import {
  clamp,
  flowStep,
  wheelDistance,
  normalizeMotionSpeed,
  prepareConstellation,
  visibleLabels,
  seed,
} from "./constellation-layout.js";
import { createViewportIndex, overscan } from "./constellation-viewport.js";
import { createShootingStar } from "./shooting-star.js";
import { verificationBadge } from "./verification-badge.js";
import { groupKey, groupDescription } from "./constellation-colors.js";
import { historyCount } from "./audience-groups.js";

export function createConstellation({
  element,
  root,
  escape: esc,
  label,
  initials,
  onSelect,
  onPreview = onSelect,
  onOpen,
  onGroup,
  hasOlder = () => false,
  onOlder = () => {},
}) {
  const $ = (selector) => root.querySelector(selector);
  const zoomValue = $("#zoom-value"), zoomControl = $("#scene-zoom"),
    zoomIn = $("#zoom-in"), zoomOut = $("#zoom-out"),
    history = $("#memory-scrubber"), peopleCount = $("#scene-people-count"),
    next = $("#memory-next"), previous = $("#memory-previous"),
    key = $("#constellation-key"), context = $(".scene-context"), signal = $("#selected-signal");
  const shootingStar = createShootingStar();
  let events = [],
    selected = null,
    modules = [],
    lens = "none",
    aggregate = null,
    geometry = null,
    layoutAtZoom = null;
  let selectionByEvent = null, selection = null, bindingsByEvent = null;
  let viewportIndex = null, viewportLabels = [], activeSparks = [],
    positionedLabels = new Set(), labelsByNode = null;
  let sceneVersion = 0;
  let restoringFocus = false;
  // History is deduplicated by event ID before grouping, so only data changes alter membership.
  let personCount = 0, countDirty = true;
  let zoom = 0.8,
    wheelZoom = null,
    frame = 0,
    last = 0,
    clock = 0,
    target = null,
    seeking = false,
    drag = null,
    scrollPosition = 0;
  let stars = [],
    labels = [],
    sparks = [],
    actorButtons = [],
    sky = null, meteor = null, meteorTail = null,
    canvas = null, linkLayer = null, groupLayer = null,
    groupButtons = null, connections = null,
    sceneWidth = 0, sceneHeight = 0,
    keyScope = null;
  let labelInset = null, labelsDirty = true, viewportLeft = null,
    animationDirty = true, lastMotion = null, browseLeft = null;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const active = () =>
    geometry &&
    root.isConnected && element.isConnected &&
    element.classList.contains("horizontal") &&
    root.dataset.route === "timeline" &&
    !document.hidden;
  const moving = () => !reduced.matches && root.dataset.motion !== "off";
  const maximum = () => Math.max(0, element.scrollWidth - element.clientWidth);
  const singletonCanLoad = () => Boolean(geometry?.people.length === 1 && hasOlder());
  const position = () => selection?.person;
  const selectedProfileIndex = () => selection?.index ?? -1;
  function personLabel(person, event = person.event) {
    return `<button type="button" class="star-identity"><strong>${esc(event.name || event.handle || "X account")}${verificationBadge(event, modules)}</strong><span class="star-handle">${esc(event.handle ? "@" + event.handle : "ID " + event.actor_id)}</span>${activityIcon(event)}</button>${postPreview(event, 140, "star-post")}`;
  }

  function stop() {
    cancelAnimationFrame(frame);
    frame = 0;
    last = 0;
    root.dataset.animating = "false";
  }
  function releaseScene() {
    if (drag && element.hasPointerCapture(drag.id)) element.releasePointerCapture(drag.id);
    drag = null;
    target = null;
    seeking = false;
    delete element.dataset.panning;
    delete element.dataset.userScrolling;
    stars = [];
    labels = [];
    sparks = [];
    actorButtons = [];
    sky = meteor = meteorTail = canvas = linkLayer = groupLayer = null;
    groupButtons = connections = layoutAtZoom = null;
    selectionByEvent = selection = keyScope = bindingsByEvent = labelsByNode = null;
    viewportIndex = null;
    viewportLabels = activeSparks = [];
    positionedLabels.clear();
    viewportLeft = browseLeft = labelInset = null;
    labelsDirty = animationDirty = true;
    lastMotion = null;
  }
  function queue() {
    if (!frame && active()) frame = requestAnimationFrame(paint);
  }
  function zoomControls() {
    zoomValue.textContent = `${Math.round(zoom * 100)}%`;
    zoomControl.value = zoom;
    zoomControl.setAttribute(
      "aria-valuetext",
      geometry.overview
        ? "Audience groups overview"
        : `${Math.round(zoom * 100)} percent`,
    );
    for (const control of [zoomControl, zoomIn, zoomOut])
      control.disabled = geometry.people.length < 2;
    zoomOut.disabled ||= zoom === 0;
    zoomIn.disabled ||= zoom === 2;
    history.disabled = !geometry.canPan;
  }
  function scrubber() {
    const max = maximum();
    const value = max ? Math.round((1 - element.scrollLeft / max) * 1000) : 500;
    if (Number(history.value) !== value) history.value = value;
  }
  function groupHint() {
    const group = geometry.grouped && !geometry.overview
      ? geometry.groups.find(item => item.key === position()?.group)
      : null;
    const scope = geometry.overview ? "overview" : group;
    if (keyScope === scope) return;
    keyScope = scope;
    key.innerHTML = geometry.grouped
      ? geometry.overview ? '<span class="constellation-key-item">All constellations</span>'
        : groupKey(group ? [group] : [], esc)
      : "";
    key.setAttribute("aria-label", geometry.overview ? "Constellation groups" : "Current constellation");
    labelInset = null;
    labelsDirty = true;
  }
  function selectVisibleProfile(notify = onSelect, duringPaint = false) {
    const center = element.scrollLeft + element.clientWidth / 2;
    // Pannable group overviews retain their existing browsing behavior.
    const closest = viewportIndex.nearest(center);
    if (closest && closest !== position()) {
      applySelection(closest.event.event_id);
      if (!duringPaint) queue();
      notify(closest.event.event_id);
    }
  }
  function travelControls() {
    const index = selectedProfileIndex();
    const canPan = geometry?.canPan && index >= 0;
    for (const [button, available] of [
      [
        next,
        (canPan && (index < geometry.people.length - 1 || hasOlder())) ||
          singletonCanLoad(),
      ],
      [previous, canPan && index > 0],
    ]) {
      button.disabled = !available;
      button.classList.toggle("is-unavailable", !available);
      button.setAttribute("aria-hidden", String(!available));
      button.setAttribute("aria-label", geometry?.grouped
        ? button === next ? "Previous event" : "Next event"
        : button === next ? "Older memory" : "Newer memory");
    }
  }
  function applySelection(identity, initial = false) {
    if (!initial && identity === selected) return false;
    const previous = position();
    selected = identity;
    selection = selectionByEvent.get(identity);
    const chosenPerson = position();
    const updateBinding = (item, index) => {
      const {button, personElement, person} = actorButtons[index];
      const chosen = button.dataset.event === chosenPerson?.event.event_id;
      const event = chosen ? selection.event : person.event;
      button.setAttribute("aria-pressed", String(chosen));
      button.setAttribute(
        "aria-label",
        `${event.name || event.handle || "X account"}, ${label(event)}, recorded event`,
      );
      personElement.classList.toggle("is-selected", chosen);
      const chosenLabel = item.person === chosenPerson;
      const labelEvent = chosenLabel ? selection.event : item.person.event;
      item.label.setAttribute("aria-label", `${chosenLabel ? "Open recorded event for" : "Select"} ${labelEvent.name || labelEvent.handle || "X account"}`);
      if (initial) {
        item.label.innerHTML = personLabel(item.person, labelEvent);
        item.controls = item.label.querySelectorAll("button,a");
        item.preview = item.label.querySelector(".star-post");
        showLabel(item, false);
      }
      item.width = undefined;
    };
    if (initial) labels.forEach(updateBinding);
    else {
      for (const id of new Set([previous?.event.event_id, chosenPerson?.event.event_id]))
        for (const index of bindingsByEvent.get(id) ?? []) updateBinding(labels[index], index);
    }
    if (initial || previous?.group !== chosenPerson?.group) groupHint();
    travelControls();
    labelsDirty = true;
    return true;
  }
  function select(identity) {
    if (geometry && root.isConnected && element.isConnected && applySelection(identity))
      queue();
  }
  function showLabel(item, visible) {
    if (item.visible === visible) return;
    item.visible = visible;
    item.label.style.visibility = visible ? "visible" : "hidden";
    item.label.setAttribute("aria-hidden", String(!visible));
    item.label.tabIndex = -1;
    item.controls?.forEach(control => { control.tabIndex = visible ? 0 : -1; });
  }
  function resetViewport() {
    viewportIndex = createViewportIndex(labels, geometry.overview ? [] : sparks);
    viewportLeft = null;
  }
  function updateViewport(left) {
    const range = viewportIndex.range(left - overscan, left + element.clientWidth + overscan);
    viewportLabels = range.labels;
    const next = range.connections;
    if (next.length === activeSparks.length && next.every((spark, index) => spark === activeSparks[index]))
      return false;
    const retained = new Set(next);
    for (const spark of activeSparks) {
      if (!retained.has(spark)) {
        spark.element.setAttribute("display", "none");
        spark.trail.setAttribute("display", "none");
        spark.hidden = true;
      }
    }
    activeSparks = next;
    return true;
  }
  function layoutLabels(left, focusedControl = document.activeElement) {
    const chosenPerson = position();
    const chosenLabel = labels[selectedProfileIndex()];
    const focusedLabel = labelsByNode.get(focusedControl?.closest("[data-label]"));
    const relevant = new Set(viewportLabels);
    if (chosenLabel) relevant.add(chosenLabel);
    if (focusedLabel) relevant.add(focusedLabel);
    const viewportWidth = element.clientWidth;
    const bottom = geometry.lower + 25;
    // The signal can grow with the selected event; reserve its actual space only for a pinned label.
    const focusBottom = focusedLabel && focusedLabel !== chosenLabel
      ? Math.min(element.clientHeight - 80, (signal?.offsetHeight ? signal.offsetTop - element.offsetTop - 8 : Infinity))
      : 0;
    labelInset ??= (context?.offsetHeight || 0) + 28;
    // Read invalidated sizes together before positioning any label.
    for (const item of relevant) {
      const previewShown = item.preview &&
        (item === chosenLabel || item.preview === focusedControl);
      if (item.width === undefined || item.previewShown !== previewShown) {
        item.previewShown = previewShown;
        const box = item.label.getBoundingClientRect();
        item.width = box.width;
        item.height = box.height;
        item.previewHeight = previewShown ? item.preview.offsetHeight : 0;
      }
    }
    const candidates = [];
    for (const item of [...relevant].sort((a, b) => a.index - b.index)) {
      const chosen = item.person === chosenPerson;
      const x = item.person.x - left;
      const width = item.width,
        height = item.height;
      let top = item.person.y + 27;
      const previewHeight = item.previewHeight;
      if (top + height + (previewHeight ? previewHeight + 8 : 0) > bottom)
        top = item.person.y - height - (previewHeight ? 40 : 25);
      top = clamp(top, labelInset, Math.max(labelInset, bottom - height));
      const pinnedFocus = item === focusedLabel && !chosen;
      const previewTop = pinnedFocus
        ? top + height + 8
        : Math.max(item.person.y + 40, top < item.person.y ? 0 : top + height + 8);
      if (item.previewShown) item.preview.style.top = `${previewTop - top}px`;
      const previewBottom = item.previewShown ? previewTop + previewHeight : top + height;
      const blockHeight = Math.max(height, previewBottom - top);
      const limit = pinnedFocus ? Math.max(labelInset, focusBottom - blockHeight) : top;
      top = Math.min(top, limit);
      const center = clamp(
        x, width / 2 + 16, viewportWidth - width / 2 - 16,
      );
      item.label.style.left = `${center + left}px`;
      item.label.style.top = `${top}px`;
      if (
        (chosen || item === focusedLabel || (x >= 12 && x <= viewportWidth - 12)) &&
        center - width / 2 >= 12 &&
        center + width / 2 <= viewportWidth - 12
      ) {
        const candidate = {
          id: item.person,
          left: center - width / 2,
          right: center + width / 2,
          top,
          bottom: top + blockHeight,
          minTop: labelInset,
          maxBottom: pinnedFocus ? focusBottom : Math.max(bottom, previewBottom),
          distance: pinnedFocus ? -1 : Math.abs(center - viewportWidth / 2),
        };
        const alternateTop = clamp(
          top < item.person.y ? item.person.y + 27 : item.person.y - height - 25,
          labelInset,
          Math.max(labelInset, pinnedFocus ? candidate.maxBottom - blockHeight : bottom - height),
        );
        if (!chosen) {
          const extent = pinnedFocus ? blockHeight : height;
          candidate.alternates = [{ ...candidate, top: alternateTop, bottom: alternateTop + extent }];
          if (pinnedFocus) {
            // A pinned label can also use the opposite edge because it no longer follows its star.
            const otherLeft = center > viewportWidth / 2 ? 16 : viewportWidth - width - 16;
            const edge = Math.max(labelInset, candidate.maxBottom - extent);
            for (const left of [candidate.left, otherLeft]) {
              for (const alternate of [labelInset, edge]) {
                candidate.alternates.push({
                  ...candidate, left, right: left + width, top: alternate, bottom: alternate + extent,
                });
              }
            }
          }
        }
        candidates.push(candidate);
      }
    }
    const shown = visibleLabels(candidates, chosenPerson);
    for (const item of positionedLabels) {
      if (relevant.has(item)) continue;
      showLabel(item, false);
      // Old positions can otherwise extend the scroll area after zooming out.
      item.label.style.left = "";
    }
    for (const item of relevant) {
      const placement = shown.get(item.person);
      if (placement) {
        item.label.style.top = `${placement.top}px`;
        if (item === focusedLabel && item !== chosenLabel)
          item.label.style.left = `${left + (placement.left + placement.right) / 2}px`;
      }
      showLabel(item, Boolean(placement) || item === focusedLabel);
    }
    positionedLabels = relevant;
  }
  function animate(motion) {
    const shot = motion ? shootingStar(clock, sceneWidth, sceneHeight) : null;
    meteor.style.opacity = String(shot?.opacity || 0);
    meteor.dataset.active = String(Boolean(shot && shot.opacity > 0));
    if (shot)
      for (const key of ["x1", "y1", "x2", "y2"]) {
        meteor.setAttribute(key, shot[key].toFixed(2));
        meteorTail.setAttribute(key, shot[key].toFixed(2));
      }
    stars.forEach((star, index) => {
      star.style.opacity = String(
        motion
          ? 0.1 + 0.12 * (1 + Math.sin(clock / 1900 + index * 2.4))
          : 0.22,
      );
    });
  }
  function animateConnections() {
    for (const connection of activeSparks) {
      const {element: spark, trail, a, b, phase} = connection;
      const part = (clock / 10000 + phase) % 1;
      const tail = Math.max(0, part - 0.06);
      spark.setAttribute("cx", (a.x + (b.x - a.x) * part).toFixed(2));
      spark.setAttribute("cy", (a.y + (b.y - a.y) * part).toFixed(2));
      trail.setAttribute("x1", (a.x + (b.x - a.x) * tail).toFixed(2));
      trail.setAttribute("y1", (a.y + (b.y - a.y) * tail).toFixed(2));
      trail.setAttribute("x2", (a.x + (b.x - a.x) * part).toFixed(2));
      trail.setAttribute("y2", (a.y + (b.y - a.y) * part).toFixed(2));
      if (connection.hidden) {
        spark.removeAttribute("display");
        trail.removeAttribute("display");
        connection.hidden = false;
      }
    }
  }
  function paint(now) {
    frame = 0;
    if (!active()) {
      last = 0;
      return;
    }
    const elapsed = last ? clamp(now - last, 0, 64) : 0;
    last = now;
    const motion = moving();
    if (motion)
      clock += elapsed * normalizeMotionSpeed(root.dataset.motionSpeed || 1);
    if (target !== null) {
      const previous = element.scrollLeft;
      const next = motion
        ? flowStep(element.scrollLeft, target, elapsed || 16)
        : target;
      element.scrollLeft = next;
      // Browsers can round away the final eased step; finish instead of stalling.
      if (Math.abs(target - element.scrollLeft) < 2 || element.scrollLeft === previous) {
        element.scrollLeft = target;
        target = null;
        seeking = false;
      }
    }
    const left = element.scrollLeft;
    const scrolled = left !== viewportLeft;
    const browsing = geometry.canPan && !seeking && element.dataset.userScrolling === "true";
    // A scroll event can mark browsing after paint has already laid out this offset.
    if (browsing && left !== browseLeft) {
      browseLeft = left;
      selectVisibleProfile(onPreview, true);
    }
    if (!browsing) browseLeft = null;
    if (scrolled) sky.style.transform = `translateX(${left}px)`;
    const connectionsChanged = scrolled && !geometry.overview && updateViewport(left);
    if (scrolled || labelsDirty) {
      if (!geometry.overview) layoutLabels(left);
      scrubber();
      viewportLeft = left;
      labelsDirty = false;
    }
    const animating = String(motion);
    if (motion || animationDirty || lastMotion !== motion) animate(motion);
    if (!geometry.overview && (motion || animationDirty || connectionsChanged))
      animateConnections();
    animationDirty = false;
    lastMotion = motion;
    if (browsing && target === null && !drag) {
      browseLeft = null;
      delete element.dataset.userScrolling;
      onSelect(selected);
    }
    if (root.dataset.animating !== animating) root.dataset.animating = animating;
    if (motion || target !== null) queue();
    else last = 0;
  }
  function render(nextEvents, identity) {
    const renderedVersion = ++sceneVersion;
    stop();
    wheelZoom = null;
    events = nextEvents;
    sceneWidth = element.clientWidth;
    sceneHeight = element.clientHeight;
    layoutAtZoom = prepareConstellation({
      events,
      width: sceneWidth,
      height: sceneHeight,
      modules,
      lens,
      aggregate,
    });
    geometry = layoutAtZoom(zoom);
    if (countDirty) {
      personCount = new Set(geometry.people.map(person => person.event.actor_id)).size;
      countDirty = false;
    }
    element.dataset.canPan = String(geometry.canPan);
    element.classList.toggle("is-grouped", geometry.grouped);
    // A fresh DOM scene has no valid measurements or last-painted viewport.
    viewportLeft = browseLeft = labelInset = null;
    labelsDirty = animationDirty = true;
    keyScope = undefined;
    key.hidden = !geometry.grouped;
    history.max = 1000;
    zoomControls();
    const countText = aggregate
      ? historyCount(events.length, personCount, aggregate)
      : `${personCount} ${personCount === 1 ? "person" : "people"} in loaded history`;
    if (peopleCount.textContent !== countText) peopleCount.textContent = countText;
    const background = Array.from(
      { length: 76 },
      (_, index) =>
        `<circle class="sky-star" cx="${seed("x" + index) * element.clientWidth}" cy="${seed("y" + index) * element.clientHeight * 0.74}" r="${index % 9 ? 0.8 : 1.5}"/>`,
    ).join("");
    element.innerHTML = `<svg class="constellation-sky" viewBox="0 0 ${element.clientWidth} ${element.clientHeight}" aria-hidden="true">${background}<defs><linearGradient id="xf-shooting-tail" class="shooting-tail" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="currentColor" stop-opacity="0"/><stop offset="1" stop-color="currentColor"/></linearGradient></defs><line class="shooting-star" data-active="false" stroke="url(#xf-shooting-tail)" opacity="0"/></svg><div class="constellation-canvas" style="width:${geometry.width}px"><svg class="constellation-links${geometry.grouped ? " is-grouped" : ""}" viewBox="0 0 ${geometry.width} ${element.clientHeight}" aria-hidden="true"></svg>${geometry.people.map((person) => `<article class="constellation-person" data-person="${esc(person.id)}" style="--group-color:${person.color || "var(--muted)"}"><button class="constellation-star ${esc(person.tone)}" type="button" style="left:${person.x}px;top:${person.y}px" data-actor="${esc(person.event.actor_id)}" data-event="${esc(person.event.event_id)}" aria-label="${esc(person.event.name || person.event.handle || "X account")}, ${esc(label(person.event))}, recorded event"><span class="star-core" aria-hidden="true"></span><span class="star-initials" aria-hidden="true">${esc(initials(person.event))}</span></button><div class="star-label" data-label="${esc(person.event.event_id)}" aria-label="Open recorded event for ${esc(person.event.name || person.event.handle || "X account")}">${personLabel(person)}</div></article>`).join("")}<div class="constellation-groups" hidden></div></div>`;
    sky = element.querySelector(".constellation-sky");
    meteor = element.querySelector(".shooting-star");
    meteorTail = element.querySelector(".shooting-tail");
    const firstEvents = new Map();
    for (const event of events)
      if (!firstEvents.has(event.event_id)) firstEvents.set(event.event_id, event);
    selectionByEvent = new Map();
    selection = null;
    let index = 0;
    for (const person of geometry.people) {
      for (const event of person.events)
        if (!selectionByEvent.has(event.event_id))
          selectionByEvent.set(event.event_id, {person, index, event: firstEvents.get(event.event_id)});
      index++;
    }
    actorButtons = [...element.querySelectorAll("[data-actor]")].map(button => ({
      button, personElement: button.closest(".constellation-person"),
      person: selectionByEvent.get(button.dataset.event)?.person,
    }));
    stars = [...element.querySelectorAll(".sky-star")];
    const labelNodes = element.querySelectorAll("[data-label]");
    labels = geometry.people.map((person, index) => ({person, index, label: labelNodes[index]}));
    labelsByNode = new WeakMap(labels.map(item => [item.label, item]));
    bindingsByEvent = new Map();
    actorButtons.forEach(({button}, index) => {
      const id = button.dataset.event;
      if (!bindingsByEvent.has(id)) bindingsByEvent.set(id, []);
      bindingsByEvent.get(id).push(index);
    });
    viewportLabels = activeSparks = [];
    positionedLabels.clear();
    canvas = element.querySelector(".constellation-canvas");
    linkLayer = element.querySelector(".constellation-links");
    groupLayer = element.querySelector(".constellation-groups");
    groupButtons = connections = null;
    sparks = [];
    actorButtons.forEach(({button, person}) =>
      button.addEventListener("click", () => {
        if (!ownsScene(renderedVersion, button) || geometry.overview ||
            !person || person.event.event_id !== button.dataset.event) return;
        clickPerson(person);
      }),
    );
    labels.forEach(({person, label: button}) => {
      const first = selectionByEvent.get(person.event.event_id)?.person;
      button.addEventListener("click", event => {
        if (ownsScene(renderedVersion, button) && !geometry.overview &&
            !event?.target?.closest?.("a")) clickPerson(first);
      });
    });
    applySelection(identity, true);
    updateMode();
    resetViewport();
    anchor();
    scrubber();
    queue();
  }
  function ownsScene(version, node) {
    return version === sceneVersion && geometry && root.isConnected &&
      element.isConnected && element.contains(node);
  }
  function prepareConnections() {
    const links = [];
    if (geometry.groups.length === 1) {
      const group = geometry.groups[0];
      let previous = null;
      for (const person of geometry.people) {
        if (person.group !== group.key) continue;
        if (previous) links.push({ a: person, b: previous, color: group.color, dash: group.dash });
        previous = person;
      }
    } else if (geometry.groups.length > 1) {
      const peopleByGroup = new Map(geometry.groups.map(group => [group.key, []]));
      // Map matches NaN keys, but the previous strict group comparison did not.
      for (const person of geometry.people)
        if (!Number.isNaN(person.group)) peopleByGroup.get(person.group)?.push(person);
      for (const group of geometry.groups) {
        const people = peopleByGroup.get(group.key);
        for (let index = 1; index < people.length; index++)
          links.push({ a: people[index], b: people[index - 1], color: group.color, dash: group.dash });
      }
    }
    linkLayer.innerHTML = links.map(({ a, b, color, dash }) => `<g data-link-group="${esc(a.group)}" style="${color ? `color:${color}` : ""}"><path d="M${a.x},${a.y}L${b.x},${b.y}" stroke-dasharray="${dash || ""}"/><line class="sequence-trail" display="none"/><circle class="sequence-spark" r="2" display="none"/></g>`).join("");
    connections = linkLayer.querySelectorAll("path");
    const trails = linkLayer.querySelectorAll(".sequence-trail");
    sparks = [...linkLayer.querySelectorAll(".sequence-spark")].map(
      (spark, index) => ({element: spark, trail: trails[index], ...links[index], phase: seed(index), hidden: true}),
    );
  }
  function prepareGroupButtons() {
    const renderedVersion = sceneVersion;
    const canDrillDown = group =>
      !group.people.length && onGroup && lens === "activity" && group.key !== "unknown";
    groupLayer.innerHTML = geometry.overviewGroups.map((group) => {
      const loaded = group.people.length > 0;
      const description = esc(groupDescription(group));
      const attributes = `class="constellation-group ${esc(group.tone)}" style="--group-color:${group.color};left:${group.x}px;top:${group.y}px" data-group="${esc(group.key)}" title="${description}"`;
      const count = `<span class="cluster-count">${group.eventCount ?? group.people.length}</span><strong>${esc(group.label)}</strong>`;
      return loaded || canDrillDown(group)
        ? `<button type="button" ${attributes} aria-label="Explore ${esc(group.label)}, ${description}">${count}</button>`
        : `<div ${attributes}>${count}<small>0 loaded</small></div>`;
    }).join("");
    groupButtons = [...groupLayer.querySelectorAll("[data-group]")];
    groupButtons.forEach((button, index) => {
      const group = geometry.overviewGroups[index];
      if (!group.people.length && !canDrillDown(group)) return;
      button.addEventListener("click", () => {
        if (!ownsScene(renderedVersion, button) || !geometry.overview) return;
        if (!group.people.length) {
          onGroup(group.key);
          return;
        }
        const identity = group.people[0].event.event_id;
        select(identity);
        setZoom(1);
        seek(events.findIndex(item => item.event_id === identity), "instant");
      });
    });
  }
  function updateMode() {
    const overview = geometry.overview;
    const focused = document.activeElement;
    if (focused && (overview
      ? element.contains(focused) && focused.closest(".constellation-person")
      : groupLayer.contains(focused))) {
      (zoomControl.disabled ? element : zoomControl).focus({preventScroll: true});
    }
    element.classList.toggle("is-group-overview", overview);
    groupLayer.hidden = !overview;
    linkLayer.style.visibility = overview ? "hidden" : "";
    if (overview && !groupButtons) prepareGroupButtons();
    if (!overview && !connections) prepareConnections();
    for (const {button} of actorButtons) {
      button.tabIndex = overview ? -1 : 0;
      button.setAttribute("aria-hidden", String(overview));
    }
    if (overview) {
      for (const item of positionedLabels) showLabel(item, false);
      viewportLabels = [];
    }
  }
  function anchor() {
    const point = position();
    element.scrollLeft = geometry.canPan && point
      ? clamp(point.x - element.clientWidth / 2, 0, maximum())
      : 0;
    target = null;
    seeking = false;
    scrollPosition = element.scrollLeft;
    delete element.dataset.userScrolling;
    if (drag) {
      drag.x = drag.lastX;
      drag.scroll = scrollPosition;
    }
  }
  function clickPerson(person) {
    target = null;
    seeking = false;
    delete element.dataset.userScrolling;
    scrollPosition = element.scrollLeft;
    if (position() === person) onOpen(selected);
    else {
      seek(events.findIndex(event => event.event_id === person.event.event_id));
    }
  }
  function seek(index, behavior = "smooth") {
    if (!events.length || !geometry) return;
    delete element.dataset.userScrolling;
    const event = events[clamp(index, 0, events.length - 1)];
    select(event.event_id);
    if (geometry.overview) setZoom(0.8);
    const destination = position();
    if (destination && geometry.canPan) {
      target = clamp(destination.x - element.clientWidth / 2, 0, maximum());
      seeking = true;
      if (behavior === "instant" || !moving()) {
        element.scrollLeft = target;
        target = null;
        seeking = false;
      }
    }
    scrubber();
    onSelect(selected);
    queue();
  }
  function setZoom(value) {
    const nextZoom = clamp(Math.round(value * 20) / 20, 0, 2);
    if (nextZoom === zoom || !Number.isFinite(nextZoom)) return;
    if (!geometry) {
      zoom = nextZoom;
      return;
    }
    if (!ownsScene(sceneVersion, canvas)) return;
    wheelZoom = null;
    const wasOverview = geometry.overview;
    const coordinatesChanged = zoom > 0.25 || nextZoom > 0.25;
    zoom = nextZoom;
    layoutAtZoom(zoom);
    element.dataset.canPan = String(geometry.canPan);
    canvas.style.width = `${geometry.width}px`;
    linkLayer.setAttribute("viewBox", `0 0 ${geometry.width} ${sceneHeight}`);
    geometry.people.forEach((point, index) => {
      const {button} = actorButtons[index];
      button.style.left = `${point.x}px`;
      button.style.top = `${point.y}px`;
    });
    if (wasOverview !== geometry.overview) {
      updateMode();
      groupHint();
    }
    if (geometry.overview) {
      geometry.overviewGroups.forEach((group, index) => {
        groupButtons[index].style.left = `${group.x}px`;
        groupButtons[index].style.top = `${group.y}px`;
      });
    } else {
      connections.forEach((path, index) => {
        const {a, b} = sparks[index];
        path.setAttribute("d", `M${a.x},${a.y}L${b.x},${b.y}`);
      });
    }
    if (coordinatesChanged) resetViewport();
    anchor();
    zoomControls();
    travelControls();
    scrubber();
    labelsDirty = !geometry.overview;
    animationDirty = true;
    queue();
  }
  function scrub(progress) {
    if (!geometry?.canPan) return;
    target = null;
    seeking = false;
    element.scrollLeft = (1 - clamp(progress, 0, 1)) * maximum();
    delete element.dataset.userScrolling;
    selectVisibleProfile();
    scrubber();
    queue();
  }
  function travel(delta) {
    if (!geometry?.canPan) {
      if (delta > 0 && singletonCanLoad()) onOlder();
      return;
    }
    const index = selectedProfileIndex();
    if (index < 0) return;
    const next = geometry.people[index + Math.sign(delta)];
    if (next)
      seek(events.findIndex((event) => event.event_id === next.event.event_id));
    else if (delta > 0 && hasOlder()) onOlder();
  }
  function onWheel(event) {
    if (!(event.buttons & 4) || event.ctrlKey || event.metaKey) wheelZoom = null;
    if (!active() || event.ctrlKey || event.metaKey) return;
    const delta = wheelDistance(event, element.clientWidth);
    if (!delta) return;
    if ((event.buttons & 4) && geometry.people.length > 1) {
      event.preventDefault();
      const next = clamp((wheelZoom ?? zoom) - delta / 600, 0, 2);
      if (Math.round(next * 20) / 20 !== zoom) setZoom(next);
      wheelZoom = next;
      return;
    }
    if (!geometry.canPan) return;
    if (delta < 0 && element.scrollLeft <= 2 && hasOlder()) {
      event.preventDefault();
      selectVisibleProfile();
      onOlder();
    }
    const next = clamp((target ?? element.scrollLeft) + delta, 0, maximum());
    if (next === (target ?? element.scrollLeft)) return;
    event.preventDefault();
    target = next;
    seeking = false;
    element.dataset.userScrolling = "true";
    queue();
  }
  function middleButton(event) {
    if (event.button === 1 && active() && !event.target.closest("a,input"))
      event.preventDefault();
  }
  function down(event) {
    if (geometry?.canPan && event.pointerType !== "mouse") {
      target = null;
      seeking = false;
    }
    if (
      !geometry?.canPan ||
      event.pointerType !== "mouse" ||
      event.button !== 0 ||
      event.target.closest("button,input,a")
    )
      return;
    target = null;
    seeking = false;
    drag = {
      id: event.pointerId,
      x: event.clientX,
      lastX: event.clientX,
      scroll: element.scrollLeft,
    };
    element.setPointerCapture(event.pointerId);
    element.dataset.panning = "true";
  }
  function move(event) {
    if (!drag || drag.id !== event.pointerId) return;
    drag.lastX = event.clientX;
    target = clamp(drag.scroll + drag.x - event.clientX, 0, maximum());
    element.dataset.userScrolling = "true";
    queue();
  }
  function up(event) {
    if (!drag || drag.id !== event.pointerId) return;
    if (element.hasPointerCapture(event.pointerId))
      element.releasePointerCapture(event.pointerId);
    drag = null;
    delete element.dataset.panning;
    queue();
  }
  function onKey(event) {
    if (
      !geometry ||
      event.altKey ||
      event.ctrlKey ||
      event.metaKey ||
      event.target.closest("button,input,select")
    )
      return;
    const keys = {
      Home: events.findIndex(
        (event) => event.event_id === geometry.people.at(-1)?.event.event_id,
      ),
      End: events.findIndex(
        (event) => event.event_id === geometry.people[0]?.event.event_id,
      ),
    };
    if (
      ["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"].includes(event.key)
    ) {
      event.preventDefault();
      travel(["ArrowLeft", "ArrowUp"].includes(event.key) ? 1 : -1);
    }
    if (Object.hasOwn(keys, event.key)) {
      event.preventDefault();
      seek(keys[event.key]);
    }
    if (["+", "=", "-", "0"].includes(event.key)) {
      event.preventDefault();
      setZoom(
        event.key === "0" ? 0 : zoom + (event.key === "-" ? -0.25 : 0.25),
      );
    }
  }
  const refresh = () => {
    stop();
    queue();
  };
  const observer = new MutationObserver(refresh);
  observer.observe(root, {
    attributes: true,
    attributeFilter: ["data-route", "data-motion", "data-motion-speed"],
  });
  const invalidateLabelSizes = () => {
    if (!geometry) return;
    for (const item of labels) item.width = undefined;
    labelInset = null;
    labelsDirty = true;
    queue();
  };
  const resize = new ResizeObserver((entries = []) => {
    if (geometry && element.clientWidth && element.clientHeight &&
        (element.clientWidth !== sceneWidth || element.clientHeight !== sceneHeight)) {
      render(events, selected);
    } else if (geometry && entries.some(entry => entry.target === context)) {
      labelInset = null;
      labelsDirty = true;
      queue();
    }
  });
  resize.observe(element);
  if (context) resize.observe(context);
  const scroll = () => {
    if (!seeking && target === null && element.scrollLeft !== scrollPosition)
      element.dataset.userScrolling = "true";
    scrollPosition = element.scrollLeft;
    queue();
  };
  const labelFocus = (event) => {
    if (!event.target.closest("[data-label]")) return;
    labelsDirty = true;
    queue();
  };
  const focus = (event) => {
    labelFocus(event);
    const button = event.target.closest("[data-actor]");
    if (!restoringFocus && button?.matches(":focus-visible"))
      seek(events.findIndex((item) => item.event_id === button.dataset.event));
  };
  const listeners = [
    [element, "scroll", scroll, { passive: true }],
    [element, "wheel", onWheel, { passive: false }],
    [element, "mousedown", middleButton],
    [element, "auxclick", middleButton],
    [element, "keydown", onKey],
    [element, "focusin", focus],
    [element, "focusout", labelFocus],
    [element, "pointerdown", down],
    [element, "pointermove", move],
    [element, "pointerup", up],
    [element, "pointercancel", up],
    [document, "visibilitychange", refresh],
    [zoomIn, "click", () => setZoom(zoom + 0.25)],
    [zoomOut, "click", () => setZoom(zoom - 0.25)],
    [zoomControl, "input", (event) => setZoom(Number(event.target.value))],
  ];
  if (document.fonts) {
    listeners.push([document.fonts, "loadingdone", invalidateLabelSizes]);
    listeners.push([document.fonts, "loadingerror", invalidateLabelSizes]);
  }
  if (document.defaultView) listeners.push([document.defaultView, "resize", invalidateLabelSizes]);
  listeners.forEach(([target, type, listener, options]) =>
    target.addEventListener(type, listener, options),
  );
  const preference = () => {
    refresh();
    $("#motion-toggle").disabled = reduced.matches;
    $("#motion-toggle").textContent = reduced.matches
      ? "Reduced motion"
      : root.dataset.motion === "on"
        ? "Ambient motion on"
        : "Ambient motion paused";
  };
  reduced.addEventListener("change", preference);
  preference();
  return {
    render(nextEvents, identity, nextAggregate = null) {
      aggregate = nextAggregate;
      countDirty = true;
      render(nextEvents, identity);
    },
    update(nextEvents, identity, nextAggregate = null) {
      const activeElement = document.activeElement;
      const focused = activeElement && element.contains(activeElement) ? activeElement : null;
      const star = focused?.closest("[data-actor]");
      const label = labelsByNode?.get(focused?.closest("[data-label]"));
      const group = focused?.closest("[data-group]");
      const left = element.scrollLeft, right = left + element.clientWidth;
      const chosen = position();
      const point = !geometry?.overview && chosen?.x >= left && chosen.x <= right
        ? chosen : viewportIndex?.nearest((left + right) / 2);
      const offset = point ? point.x - left : null;
      aggregate = nextAggregate;
      countDirty = true;
      render(nextEvents, identity);
      const anchor = point && selectionByEvent.get(point.event.event_id)?.person;
      if (anchor) element.scrollLeft = clamp(anchor.x - offset, 0, maximum());
      scrollPosition = element.scrollLeft;
      scrubber();
      if (group || (geometry.overview && (star || label))) {
        const button = geometry.overview && groupButtons.find(item =>
          item.dataset.group === group?.dataset.group && item.matches("button"));
        (button || element).focus({preventScroll: true});
      } else if (star || label) {
        const replacement = selectionByEvent.get(star?.dataset.event ?? label.person.event.event_id);
        const index = replacement?.index;
        const nextLabel = labels[index];
        const wasPreview = label?.preview === focused;
        const control = star ? actorButtons[index]?.button
          : wasPreview && nextLabel === labels[selectedProfileIndex()] && nextLabel?.preview
            ? nextLabel.preview : nextLabel?.controls[0];
        if (!star && control) {
          // Position the control before restoring focus; the next frame pins it if needed.
          updateViewport(element.scrollLeft);
          layoutLabels(element.scrollLeft, control);
        }
        restoringFocus = true;
        try {
          (control ?? element).focus({preventScroll: true});
        } finally {
          restoringFocus = false;
        }
      }
    },
    select,
    seek,
    scrub,
    setZoom,
    travel,
    configure: (nextModules, nextLens) => {
      if (lens !== nextLens) aggregate = null;
      modules = nextModules;
      lens = nextLens;
      if (geometry) render(events, selected);
    },
    clear: () => {
      stop();
      geometry = null;
      aggregate = null;
      events = [];
      releaseScene();
      personCount = 0;
      countDirty = true;
      key.hidden = true;
      history.disabled = true;
      travelControls();
      for (const control of [zoomControl, zoomIn, zoomOut])
        control.disabled = true;
    },
    destroy: () => {
      stop();
      geometry = null;
      aggregate = null;
      events = [];
      releaseScene();
      observer.disconnect();
      resize.disconnect();
      reduced.removeEventListener("change", preference);
      listeners.forEach(([target, type, listener, options]) =>
        target.removeEventListener(type, listener, options),
      );
    },
  };
}
