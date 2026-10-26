import {
  clamp,
  flowStep,
  wheelDistance,
  normalizeMotionSpeed,
  constellationLayout,
  visibleLabels,
  seed,
} from "./constellation-layout.js";

export function createConstellation({
  element,
  root,
  escape: esc,
  label,
  initials,
  date,
  time,
  gained,
  onSelect,
  onOpen,
}) {
  const $ = (selector) => root.querySelector(selector);
  let events = [],
    selected = null,
    modules = [],
    lens = "none",
    geometry = null;
  let zoom = 0.55,
    frame = 0,
    last = 0,
    clock = 0,
    target = null,
    seeking = false,
    drag = null;
  let stars = [],
    labels = [],
    sparks = [];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const active = () =>
    geometry &&
    element.classList.contains("horizontal") &&
    root.dataset.route === "timeline" &&
    !document.hidden;
  const moving = () => !reduced.matches && root.dataset.motion !== "off";
  const current = () => events.find((event) => event.event_id === selected);
  const indexOf = () =>
    Math.max(
      0,
      events.findIndex((event) => event.event_id === selected),
    );
  const maximum = () => Math.max(0, element.scrollWidth - element.clientWidth);
  const position = () =>
    geometry?.people.find((person) => person.id === current()?.actor_id);
  const eventDate = (event) => new Date(event.provider_at || event.received_at);

  function personLabel(person, event = person.event) {
    return `<strong>${esc(event.name || event.handle || "X account")}</strong><span class="star-handle">${esc(event.handle ? "@" + event.handle : "ID " + person.id)}</span><span class="star-kind ${gained(event) ? "positive" : "negative"}">${esc(label(event))}</span><time>${esc(date.format(eventDate(event)))}<span>${esc(time.format(eventDate(event)))}${event.provider_at ? "" : " · received"}</span></time><span class="star-records">${person.events.length} recorded ${person.events.length === 1 ? "event" : "events"}</span>`;
  }

  function stop() {
    cancelAnimationFrame(frame);
    frame = 0;
    last = 0;
    root.dataset.animating = "false";
  }
  function queue() {
    if (!frame && active()) frame = requestAnimationFrame(paint);
  }
  function navigator() {
    if (!geometry) return;
    travelControls();
    $("#zoom-value").textContent =
      zoom === 0
        ? geometry.overview
          ? "Groups"
          : "Fit"
        : `${Math.round(zoom * 100)}%`;
    $("#scene-zoom").value = zoom;
    $("#scene-zoom").setAttribute(
      "aria-valuetext",
      geometry.overview
        ? "Audience groups overview"
        : `${Math.round(zoom * 100)} percent`,
    );
    $("#zoom-fit").setAttribute("aria-pressed", String(zoom === 0));
    for (const id of ["#scene-zoom", "#zoom-fit", "#zoom-in", "#zoom-out"])
      $(id).disabled = geometry.people.length < 2;
    $("#zoom-out").disabled ||= zoom === 0;
    $("#zoom-in").disabled ||= zoom === 2;
    const fraction = Math.min(1, element.clientWidth / geometry.width);
    $("#navigator-window").style.setProperty(
      "--window-width",
      `${fraction * 100}%`,
    );
    $("#navigator-window").style.setProperty(
      "--window-start",
      `${(element.scrollLeft / geometry.width) * 100}%`,
    );
    $("#navigator-cursor").style.left =
      `${events.length > 1 ? (1 - indexOf() / (events.length - 1)) * 100 : 50}%`;
    $("#scene-people-count").textContent =
      `${geometry.people.length} ${geometry.people.length === 1 ? "person" : "people"} in loaded history`;
  }
  function travelControls() {
    const canPan = geometry?.canPan;
    for (const [id, available] of [
      ["#memory-next", canPan && element.scrollLeft > 2],
      ["#memory-previous", canPan && element.scrollLeft < maximum() - 2],
    ]) {
      const button = $(id);
      button.disabled = !available;
      button.classList.toggle("is-unavailable", !available);
      button.setAttribute("aria-hidden", String(!available));
    }
  }
  function select(identity) {
    selected = identity;
    const actor = current()?.actor_id;
    element.querySelectorAll("[data-actor]").forEach((button) => {
      const chosen = button.dataset.actor === actor;
      const person = geometry.people.find(
        (item) => item.id === button.dataset.actor,
      );
      const event = chosen ? current() : person.event;
      button.setAttribute("aria-pressed", String(chosen));
      button.setAttribute(
        "aria-label",
        `${event.name || event.handle || "X account"}, ${label(event)}, ${person.events.length} recorded events`,
      );
      button
        .closest(".constellation-person")
        .classList.toggle("is-selected", chosen);
    });
    for (const item of labels) {
      const event = item.person.id === actor ? current() : item.person.event;
      if (item.identity !== event.event_id) {
        item.label.innerHTML = personLabel(item.person, event);
        item.identity = event.event_id;
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
      const next = moving()
        ? flowStep(element.scrollLeft, target, elapsed || 16)
        : target;
      element.scrollLeft = next;
      if (Math.abs(target - element.scrollLeft) < 2) {
        element.scrollLeft = target;
        target = null;
        seeking = false;
      }
    }
    const left = element.scrollLeft,
      actor = current()?.actor_id;
    element.querySelector(".constellation-sky").style.transform =
      `translateX(${left}px)`;
    const candidates = [];
    for (const item of labels) {
      const chosen = item.person.id === actor;
      const x = item.person.x - left;
      const width = item.width,
        height = item.height;
      const bottom = geometry.lower + 25;
      let top = item.person.y + 27;
      if (top + height > bottom) top = item.person.y - height - 25;
      top = clamp(top, 16, Math.max(16, bottom - height));
      const center = chosen
        ? clamp(x, width / 2 + 16, element.clientWidth - width / 2 - 16)
        : x;
      item.label.style.left = `${center + left}px`;
      item.label.style.top = `${top}px`;
      if (
        !geometry.overview &&
        center - width / 2 >= 12 &&
        center + width / 2 <= element.clientWidth - 12
      )
        candidates.push({
          id: item.person.id,
          left: center - width / 2,
          right: center + width / 2,
          top,
          bottom: top + height,
          distance: Math.abs(center - element.clientWidth / 2),
        });
    }
    const shown = visibleLabels(candidates, actor);
    labels.forEach((item) => {
      const visible = shown.has(item.person.id);
      item.label.style.visibility = visible ? "visible" : "hidden";
      item.label.setAttribute("aria-hidden", String(!visible));
      item.label.tabIndex = visible ? 0 : -1;
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
    if (geometry.canPan && !seeking && !drag) {
      const closest = geometry.people.reduce(
        (best, person) =>
          Math.abs(person.x - left - element.clientWidth / 2) <
          Math.abs(best.x - left - element.clientWidth / 2)
            ? person
            : best,
        geometry.people[0],
      );
      if (
        closest &&
        closest.id !== actor &&
        target === null &&
        element.dataset.userScrolling === "true"
      ) {
        select(closest.event.event_id);
        onSelect(closest.event.event_id);
      }
    }
    navigator();
    root.dataset.animating = moving() ? "true" : "false";
    if (moving() || target !== null) queue();
    else last = 0;
  }
  function render(nextEvents, identity) {
    stop();
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
    element.dataset.canPan = String(geometry.canPan);
    element.classList.toggle("is-group-overview", geometry.overview);
    const background = Array.from(
      { length: 76 },
      (_, index) =>
        `<circle class="sky-star" cx="${seed("x" + index) * element.clientWidth}" cy="${seed("y" + index) * element.clientHeight * 0.74}" r="${index % 9 ? 0.8 : 1.5}"/>`,
    ).join("");
    const links = geometry.groups.flatMap((group) => {
      const people = geometry.people.filter(
        (person) => person.group === group.key,
      );
      return people
        .slice(1)
        .map((person, index) => ({ a: person, b: people[index] }));
    });
    element.innerHTML = `<svg class="constellation-sky" viewBox="0 0 ${element.clientWidth} ${element.clientHeight}" aria-hidden="true">${background}</svg><div class="constellation-canvas" style="width:${geometry.width}px"><svg class="constellation-links" viewBox="0 0 ${geometry.width} ${element.clientHeight}" aria-hidden="true">${geometry.overview ? "" : links.map(({ a, b }) => `<path d="M${a.x},${a.y}L${b.x},${b.y}"/><line class="sequence-trail"/><circle class="sequence-spark" r="2"/>`).join("")}</svg>${geometry.people.map((person) => `<article class="constellation-person" data-person="${esc(person.id)}"><button class="constellation-star ${esc(person.tone)}" type="button" style="left:${person.x}px;top:${person.y}px" data-actor="${esc(person.id)}" data-event="${esc(person.event.event_id)}" aria-label="${esc(person.event.name || person.event.handle || "X account")}, ${esc(label(person.event))}, ${person.events.length} recorded events"><span class="star-core" aria-hidden="true"></span><span class="star-initials" aria-hidden="true">${esc(initials(person.event))}</span></button><button type="button" class="star-label" data-label="${esc(person.id)}" aria-label="Open recorded event for ${esc(person.event.name || person.event.handle || "X account")}">${personLabel(person)}</button></article>`).join("")}${geometry.overview ? geometry.groups.map((group) => `<button type="button" class="constellation-group ${esc(group.tone)}" style="left:${group.x}px;top:${group.y}px" data-group="${esc(group.key)}" aria-label="Explore ${esc(group.label)}, ${group.people.length} ${group.people.length === 1 ? "person" : "people"}"><span class="cluster-count">${group.people.length}</span><strong title="${esc(group.label)}">${esc(group.label)}</strong><span>${group.people.length === 1 ? "person" : "people"}</span></button>`).join("") : ""}</div>`;
    stars = [...element.querySelectorAll(".sky-star")];
    const labelNodes = new Map(
      [...element.querySelectorAll("[data-label]")].map((item) => [
        item.dataset.label,
        item,
      ]),
    );
    labels = geometry.people.map((person) => ({
      person,
      label: labelNodes.get(person.id),
    }));
    sparks = [...element.querySelectorAll(".sequence-spark")].map(
      (spark, index) => ({
        element: spark,
        trail: element.querySelectorAll(".sequence-trail")[index],
        ...links[index],
      }),
    );
    element.querySelectorAll("[data-actor]").forEach((button) =>
      button.addEventListener("click", () => {
        const identity = button.dataset.event;
        if (current()?.actor_id === button.dataset.actor) onOpen(selected);
        else {
          select(identity);
          onSelect(identity);
        }
      }),
    );
    element.querySelectorAll("[data-actor]").forEach((button) => {
      button.tabIndex = geometry.overview ? -1 : 0;
      button.setAttribute("aria-hidden", String(geometry.overview));
    });
    labels.forEach(({ person, label: button }) =>
      button.addEventListener("click", () =>
        onOpen(
          current()?.actor_id === person.id ? selected : person.event.event_id,
        ),
      ),
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
    $("#navigator-marks").innerHTML = events
      .map(
        (_, index) =>
          `<i style="left:${events.length > 1 ? (1 - index / (events.length - 1)) * 100 : 50}%"></i>`,
      )
      .join("");
    const point = position();
    element.scrollLeft =
      geometry.canPan && point
        ? clamp(point.x - element.clientWidth / 2, 0, maximum())
        : 0;
    target = null;
    seeking = false;
    delete element.dataset.userScrolling;
    select(identity);
    queue();
  }
  function seek(index, behavior = "smooth") {
    if (!events.length || !geometry) return;
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
  function travel(delta) {
    if (!geometry?.canPan) return;
    const center = element.scrollLeft + element.clientWidth / 2;
    const candidates = geometry.people.filter((person) =>
      delta > 0 ? person.x < center - 2 : person.x > center + 2,
    );
    const next = candidates.sort(
      (a, b) => Math.abs(a.x - center) - Math.abs(b.x - center),
    )[0];
    if (next)
      seek(events.findIndex((event) => event.event_id === next.event.event_id));
  }
  function onWheel(event) {
    if (!geometry || !geometry.canPan || event.ctrlKey || event.metaKey) return;
    const delta = wheelDistance(event, element.clientWidth);
    if (!delta) return;
    const next = clamp((target ?? element.scrollLeft) + delta, 0, maximum());
    if (next === (target ?? element.scrollLeft)) return;
    event.preventDefault();
    target = next;
    seeking = false;
    element.dataset.userScrolling = "true";
    queue();
  }
  function down(event) {
    if (
      !geometry?.canPan ||
      event.pointerType !== "mouse" ||
      event.button !== 0 ||
      event.target.closest("button,input,a")
    )
      return;
    target = null;
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
      End: 0,
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
    if (!seeking && target === null) element.dataset.userScrolling = "true";
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
    [element, "keydown", onKey],
    [element, "focusin", focus],
    [element, "pointerdown", down],
    [element, "pointermove", move],
    [element, "pointerup", up],
    [element, "pointercancel", up],
    [document, "visibilitychange", refresh],
    [$("#zoom-in"), "click", () => setZoom(zoom + 0.25)],
    [$("#zoom-out"), "click", () => setZoom(zoom - 0.25)],
    [$("#zoom-fit"), "click", () => setZoom(0)],
    [$("#scene-zoom"), "input", (event) => setZoom(Number(event.target.value))],
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
    render,
    select,
    seek,
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
      travelControls();
      for (const id of ["#scene-zoom", "#zoom-fit", "#zoom-in", "#zoom-out"])
        $(id).disabled = true;
    },
    destroy: () => {
      stop();
      observer.disconnect();
      resize.disconnect();
      reduced.removeEventListener("change", preference);
      listeners.forEach(([target, type, listener, options]) =>
        target.removeEventListener(type, listener, options),
      );
    },
  };
}
