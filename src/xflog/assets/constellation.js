import { activityIcon } from "./activity-icon.js";
import { postPreview } from "./post-preview.js";
import {
  clamp,
  flowStep,
  wheelDistance,
  normalizeMotionSpeed,
  constellationLayout,
  visibleLabels,
  seed,
} from "./constellation-layout.js";
import { createShootingStar } from "./shooting-star.js";
import { verificationBadge } from "./verification-badge.js";
import { groupKey, groupDescription } from "./constellation-colors.js";

export function createConstellation({
  element,
  root,
  escape: esc,
  label,
  initials,
  onSelect,
  onPreview = onSelect,
  onOpen,
  hasOlder = () => false,
  onOlder = () => {},
}) {
  const $ = (selector) => root.querySelector(selector);
  const zoomValue = $("#zoom-value"), zoomControl = $("#scene-zoom"),
    zoomIn = $("#zoom-in"), zoomOut = $("#zoom-out"),
    history = $("#memory-scrubber"), peopleCount = $("#scene-people-count"),
    next = $("#memory-next"), previous = $("#memory-previous"),
    key = $("#constellation-key"), context = $(".scene-context");
  const shootingStar = createShootingStar();
  let events = [],
    selected = null,
    modules = [],
    lens = "none",
    geometry = null;
  let sceneVersion = 0;
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
    labelInset = 16,
    keyScope = null;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const active = () =>
    geometry &&
    root.isConnected && element.isConnected &&
    element.classList.contains("horizontal") &&
    root.dataset.route === "timeline" &&
    !document.hidden;
  const moving = () => !reduced.matches && root.dataset.motion !== "off";
  const current = () => events.find((event) => event.event_id === selected);
  const maximum = () => Math.max(0, element.scrollWidth - element.clientWidth);
  const position = () =>
    geometry?.people.find((person) => person.events.some(event => event.event_id === selected));
  const selectedProfileIndex = () =>
    geometry?.people.indexOf(position()) ??
    -1;
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
    sky = meteor = meteorTail = null;
  }
  function queue() {
    if (!frame && active()) frame = requestAnimationFrame(paint);
  }
  function navigator() {
    if (!geometry) return;
    travelControls();
    groupHint();
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
    history.max = 1000;
    history.disabled = !geometry.canPan;
    history.value = maximum()
      ? Math.round((1 - element.scrollLeft / maximum()) * 1000)
      : 500;
    peopleCount.textContent =
      `${personCount} ${personCount === 1 ? "person" : "people"} in ${geometry.grouped ? "saved" : "loaded"} history`;
  }
  function groupHint() {
    key.hidden = !geometry.grouped;
    const group = geometry.groups.find(item => item.key === position()?.group);
    const scope = geometry.overview ? "overview" : group?.key;
    if (keyScope === scope) return;
    keyScope = scope;
    key.innerHTML = geometry.grouped
      ? geometry.overview ? '<span class="constellation-key-item">All constellations</span>'
        : groupKey(group ? [group] : [], esc)
      : "";
    key.setAttribute("aria-label", geometry.overview ? "Constellation groups" : "Current constellation");
    labelInset = (context?.offsetHeight || 0) + 28;
  }
  function selectVisibleProfile(notify = onSelect) {
    const center = element.scrollLeft + element.clientWidth / 2;
    const closest = geometry.people.reduce(
      (best, person) =>
        Math.abs(person.x - center) < Math.abs(best.x - center) ? person : best,
      geometry.people[0],
    );
    if (closest && closest !== position()) {
      select(closest.event.event_id);
      notify(closest.event.event_id);
    }
  }
  function travelControls() {
    const index = selectedProfileIndex();
    const canPan = geometry?.canPan && index >= 0;
    for (const [button, available] of [
      [
        next,
        canPan && (index < geometry.people.length - 1 || hasOlder()),
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
  function select(identity) {
    if (!root.isConnected || !element.isConnected) return;
    selected = identity;
    const chosenPerson = position();
    actorButtons.forEach(({button, personElement, person}) => {
      const chosen = button.dataset.event === chosenPerson?.event.event_id;
      const event = chosen ? current() : person.event;
      button.setAttribute("aria-pressed", String(chosen));
      button.setAttribute(
        "aria-label",
        `${event.name || event.handle || "X account"}, ${label(event)}, recorded event`,
      );
      personElement.classList.toggle("is-selected", chosen);
    });
    for (const item of labels) {
      const event = item.person === chosenPerson ? current() : item.person.event;
      item.label.setAttribute("aria-label", `${item.person === chosenPerson ? "Open recorded event for" : "Select"} ${event.name || event.handle || "X account"}`);
      if (item.identity !== event.event_id) {
        item.label.innerHTML = personLabel(item.person, event);
        item.identity = event.event_id;
        item.controls = item.label.querySelectorAll?.("button,a") || [];
        item.preview = item.label.querySelector?.(".star-post");
      }
      const box = item.label.getBoundingClientRect();
      item.width = box.width;
      item.height = box.height;
    }
    navigator();
    queue();
  }
  function paint(now) {
    frame = 0;
    if (!active()) {
      last = 0;
      return;
    }
    const elapsed = last ? clamp(now - last, 0, 64) : 0;
    last = now;
    if (moving())
      clock += elapsed * normalizeMotionSpeed(root.dataset.motionSpeed || 1);
    if (target !== null) {
      const previous = element.scrollLeft;
      const next = moving()
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
    const browsing = geometry.canPan && !seeking && element.dataset.userScrolling === "true";
    if (browsing) selectVisibleProfile(onPreview);
    const left = element.scrollLeft,
      chosenPerson = position();
    sky.style.transform = `translateX(${left}px)`;
    const shot = moving()
      ? shootingStar(clock, element.clientWidth, element.clientHeight)
      : null;
    meteor.style.opacity = String(shot?.opacity || 0);
    meteor.dataset.active = String(Boolean(shot && shot.opacity > 0));
    if (shot)
      for (const key of ["x1", "y1", "x2", "y2"]) {
        meteor.setAttribute(key, shot[key].toFixed(2));
        meteorTail.setAttribute(key, shot[key].toFixed(2));
      }
    const candidates = [];
    for (const item of labels) {
      const chosen = item.person === chosenPerson;
      const x = item.person.x - left;
      const width = item.width,
        height = item.height;
      const bottom = geometry.lower + 25;
      let top = item.person.y + 27;
      const previewHeight = chosen && item.preview ? item.preview.offsetHeight : 0;
      if (top + height + (previewHeight ? previewHeight + 8 : 0) > bottom)
        top = item.person.y - height - (previewHeight ? 40 : 25);
      top = clamp(top, labelInset, Math.max(labelInset, bottom - height));
      const previewTop = Math.max(item.person.y + 40, top < item.person.y ? 0 : top + height + 8);
      if (chosen && item.preview) item.preview.style.top = `${previewTop - top}px`;
      const previewBottom = chosen && item.preview ? previewTop + item.preview.offsetHeight : top + height;
      const center = clamp(
        x, width / 2 + 16, element.clientWidth - width / 2 - 16,
      );
      item.label.style.left = `${center + left}px`;
      item.label.style.top = `${top}px`;
      if (
        !geometry.overview &&
        (chosen || (x >= 12 && x <= element.clientWidth - 12)) &&
        center - width / 2 >= 12 &&
        center + width / 2 <= element.clientWidth - 12
      ) {
        const candidate = {
          id: item.person.event.event_id,
          left: center - width / 2,
          right: center + width / 2,
          top,
          bottom: Math.max(top + height, previewBottom),
          minTop: labelInset,
          maxBottom: Math.max(bottom, previewBottom),
          distance: Math.abs(center - element.clientWidth / 2),
        };
        const alternateTop = clamp(
          top < item.person.y ? item.person.y + 27 : item.person.y - height - 25,
          labelInset,
          Math.max(labelInset, bottom - height),
        );
        if (!chosen)
          candidate.alternates = [
            { ...candidate, top: alternateTop, bottom: alternateTop + height },
          ];
        candidates.push(candidate);
      }
    }
    const shown = visibleLabels(candidates, chosenPerson?.event.event_id);
    labels.forEach((item) => {
      const placement = shown.get(item.person.event.event_id);
      const visible = Boolean(placement);
      if (placement) item.label.style.top = `${placement.top}px`;
      item.label.style.visibility = visible ? "visible" : "hidden";
      item.label.setAttribute("aria-hidden", String(!visible));
      item.label.tabIndex = -1;
      item.controls.forEach(control => { control.tabIndex = visible ? 0 : -1; });
    });
    stars.forEach((star, index) => {
      star.style.opacity = String(
        moving()
          ? 0.1 + 0.12 * (1 + Math.sin(clock / 1900 + index * 2.4))
          : 0.22,
      );
    });
    sparks.forEach(({ element: spark, trail, a, b }, index) => {
      const part = (clock / 10000 + seed(index)) % 1;
      const tail = Math.max(0, part - 0.06);
      spark.setAttribute("cx", (a.x + (b.x - a.x) * part).toFixed(2));
      spark.setAttribute("cy", (a.y + (b.y - a.y) * part).toFixed(2));
      trail.setAttribute("x1", (a.x + (b.x - a.x) * tail).toFixed(2));
      trail.setAttribute("y1", (a.y + (b.y - a.y) * tail).toFixed(2));
      trail.setAttribute("x2", (a.x + (b.x - a.x) * part).toFixed(2));
      trail.setAttribute("y2", (a.y + (b.y - a.y) * part).toFixed(2));
    });
    if (browsing && target === null && !drag) {
      delete element.dataset.userScrolling;
      onSelect(selected);
    }
    navigator();
    root.dataset.animating = moving() ? "true" : "false";
    if (moving() || target !== null) queue();
    else last = 0;
  }
  function render(nextEvents, identity) {
    const renderedVersion = ++sceneVersion;
    stop();
    wheelZoom = null;
    events = nextEvents;
    selected = identity;
    geometry = constellationLayout({
      events,
      width: element.clientWidth,
      height: element.clientHeight,
      zoom,
      modules,
      lens,
    });
    if (countDirty) {
      personCount = new Set(geometry.people.map(person => person.event.actor_id)).size;
      countDirty = false;
    }
    element.dataset.canPan = String(geometry.canPan);
    element.classList.toggle("is-group-overview", geometry.overview);
    element.classList.toggle("is-grouped", geometry.grouped);
    keyScope = null;
    groupHint();
    const background = Array.from(
      { length: 76 },
      (_, index) =>
        `<circle class="sky-star" cx="${seed("x" + index) * element.clientWidth}" cy="${seed("y" + index) * element.clientHeight * 0.74}" r="${index % 9 ? 0.8 : 1.5}"/>`,
    ).join("");
    const peopleByGroup = new Map(geometry.groups.map(group => [group.key, []]));
    // Map matches NaN keys, but the previous strict group comparison did not.
    for (const person of geometry.people)
      if (!Number.isNaN(person.group)) peopleByGroup.get(person.group)?.push(person);
    const links = [];
    for (const group of geometry.groups) {
      const people = peopleByGroup.get(group.key);
      for (let index = 1; index < people.length; index++)
        links.push({ a: people[index], b: people[index - 1], color: group.color, dash: group.dash });
    }
    element.innerHTML = `<svg class="constellation-sky" viewBox="0 0 ${element.clientWidth} ${element.clientHeight}" aria-hidden="true">${background}<defs><linearGradient id="xf-shooting-tail" class="shooting-tail" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="currentColor" stop-opacity="0"/><stop offset="1" stop-color="currentColor"/></linearGradient></defs><line class="shooting-star" data-active="false" stroke="url(#xf-shooting-tail)" opacity="0"/></svg><div class="constellation-canvas" style="width:${geometry.width}px"><svg class="constellation-links${geometry.grouped ? " is-grouped" : ""}" viewBox="0 0 ${geometry.width} ${element.clientHeight}" aria-hidden="true">${geometry.overview ? "" : links.map(({ a, b, color, dash }) => `<g data-link-group="${esc(a.group)}" style="${color ? `color:${color}` : ""}"><path d="M${a.x},${a.y}L${b.x},${b.y}" stroke-dasharray="${dash || ""}"/><line class="sequence-trail"/><circle class="sequence-spark" r="2"/></g>`).join("")}</svg>${geometry.people.map((person) => `<article class="constellation-person" data-person="${esc(person.id)}" style="--group-color:${person.color || "var(--muted)"}"><button class="constellation-star ${esc(person.tone)}" type="button" style="left:${person.x}px;top:${person.y}px" data-actor="${esc(person.event.actor_id)}" data-event="${esc(person.event.event_id)}" aria-label="${esc(person.event.name || person.event.handle || "X account")}, ${esc(label(person.event))}, recorded event"><span class="star-core" aria-hidden="true"></span><span class="star-initials" aria-hidden="true">${esc(initials(person.event))}</span></button><div class="star-label" data-label="${esc(person.event.event_id)}" aria-label="Open recorded event for ${esc(person.event.name || person.event.handle || "X account")}">${personLabel(person)}</div></article>`).join("")}${geometry.overview ? geometry.groups.map((group) => `<button type="button" class="constellation-group ${esc(group.tone)}" style="--group-color:${group.color};left:${group.x}px;top:${group.y}px" data-group="${esc(group.key)}" title="${esc(groupDescription(group))}" aria-label="Explore ${esc(group.label)}, ${esc(groupDescription(group))}"><span class="cluster-count">${group.people.length}</span><strong title="${esc(group.label)}">${esc(group.label)}</strong></button>`).join("") : ""}</div>`;
    sky = element.querySelector(".constellation-sky");
    meteor = element.querySelector(".shooting-star");
    meteorTail = element.querySelector(".shooting-tail");
    const peopleByEvent = new Map();
    for (const person of geometry.people)
      if (!peopleByEvent.has(person.event.event_id))
        peopleByEvent.set(person.event.event_id, person);
    actorButtons = [...element.querySelectorAll("[data-actor]")].map(button => ({
      button, personElement: button.closest(".constellation-person"),
      person: peopleByEvent.get(button.dataset.event),
    }));
    stars = [...element.querySelectorAll(".sky-star")];
    const labelNodes = new Map(
      [...element.querySelectorAll("[data-label]")].map((item) => [
        item.dataset.label,
        item,
      ]),
    );
    labels = geometry.people.map((person) => ({
      person,
      label: labelNodes.get(person.event.event_id),
    }));
    const trails = element.querySelectorAll(".sequence-trail");
    sparks = [...element.querySelectorAll(".sequence-spark")].map(
      (spark, index) => ({
        element: spark,
        trail: trails[index],
        ...links[index],
      }),
    );
    actorButtons.forEach(({button, person}) =>
      button.addEventListener("click", () => {
        if (renderedVersion !== sceneVersion || !geometry || !root.isConnected ||
            !element.isConnected || !element.contains(button) ||
            !person || person.event.event_id !== button.dataset.event) return;
        clickPerson(person);
      }),
    );
    actorButtons.forEach(({button}) => {
      button.tabIndex = geometry.overview ? -1 : 0;
      button.setAttribute("aria-hidden", String(geometry.overview));
    });
    labels.forEach(({ person, label: button }) =>
      button.addEventListener("click", (event) => { if (!event?.target?.closest?.("a")) clickPerson(person); }),
    );
    element.querySelectorAll("[data-group]").forEach((button) =>
      button.addEventListener("click", () => {
        const group = geometry.groups.find(
          (item) => item.key === button.dataset.group,
        );
        zoom = 1;
        render(events, group.people[0].event.event_id);
        seek(
          events.findIndex(
            (item) => item.event_id === group.people[0].event.event_id,
          ),
          "instant",
        );
      }),
    );
    const point = position();
    element.scrollLeft =
      geometry.canPan && point
        ? clamp(point.x - element.clientWidth / 2, 0, maximum())
        : 0;
    target = null;
    seeking = false;
    scrollPosition = element.scrollLeft;
    delete element.dataset.userScrolling;
    select(identity);
    queue();
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
    selected = event.event_id;
    if (geometry.overview) {
      zoom = 0.8;
      render(events, selected);
    }
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
    select(selected);
    onSelect(selected);
    queue();
  }
  function setZoom(value) {
    if (!geometry || !events.length) return;
    zoom = clamp(Math.round(value * 20) / 20, 0, 2);
    render(events, selected);
  }
  function scrub(progress) {
    if (!geometry?.canPan) return;
    target = null;
    seeking = false;
    element.scrollLeft = (1 - clamp(progress, 0, 1)) * maximum();
    delete element.dataset.userScrolling;
    selectVisibleProfile();
    navigator();
    queue();
  }
  function travel(delta) {
    if (!geometry?.canPan) return;
    const index = selectedProfileIndex();
    if (index < 0) return;
    const next = geometry.people[index + Math.sign(delta)];
    if (next)
      seek(events.findIndex((event) => event.event_id === next.event.event_id));
    else if (delta > 0) onOlder();
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
      scroll: element.scrollLeft,
    };
    element.setPointerCapture(event.pointerId);
    element.dataset.panning = "true";
  }
  function move(event) {
    if (!drag || drag.id !== event.pointerId) return;
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
    if (active()) queue();
  };
  const observer = new MutationObserver(refresh);
  observer.observe(root, {
    attributes: true,
    attributeFilter: ["data-route", "data-motion", "data-motion-speed"],
  });
  const resize = new ResizeObserver(() => {
    if (geometry && element.clientWidth && element.clientHeight)
      render(events, selected);
  });
  resize.observe(element);
  const scroll = () => {
    if (!seeking && target === null && element.scrollLeft !== scrollPosition)
      element.dataset.userScrolling = "true";
    scrollPosition = element.scrollLeft;
    queue();
  };
  const focus = (event) => {
    const button = event.target.closest("[data-actor]");
    if (button?.matches(":focus-visible"))
      seek(events.findIndex((item) => item.event_id === button.dataset.event));
  };
  const listeners = [
    [element, "scroll", scroll, { passive: true }],
    [element, "wheel", onWheel, { passive: false }],
    [element, "mousedown", middleButton],
    [element, "auxclick", middleButton],
    [element, "keydown", onKey],
    [element, "focusin", focus],
    [element, "pointerdown", down],
    [element, "pointermove", move],
    [element, "pointerup", up],
    [element, "pointercancel", up],
    [document, "visibilitychange", refresh],
    [zoomIn, "click", () => setZoom(zoom + 0.25)],
    [zoomOut, "click", () => setZoom(zoom - 0.25)],
    [zoomControl, "input", (event) => setZoom(Number(event.target.value))],
  ];
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
    render(nextEvents, identity) {
      countDirty = true;
      render(nextEvents, identity);
    },
    update(nextEvents, identity) {
      const offset = position() ? position().x - element.scrollLeft : null;
      countDirty = true;
      render(nextEvents, identity);
      if (offset !== null && position())
        element.scrollLeft = clamp(position().x - offset, 0, maximum());
      scrollPosition = element.scrollLeft;
    },
    select,
    seek,
    scrub,
    setZoom,
    travel,
    configure: (nextModules, nextLens) => {
      modules = nextModules;
      lens = nextLens;
      if (geometry) render(events, selected);
    },
    clear: () => {
      stop();
      geometry = null;
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
