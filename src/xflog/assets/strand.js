import { createStrandLife } from "./strand-life.js";

const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

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

export function reverseIndex(index, count) {
  return Math.max(0, count - 1 - index);
}

export function strandGeometry(count, viewport, height, zoom = 1) {
  zoom = clamp(zoom, 0, 2);
  const base = viewport < 680 ? 300 : 360;
  const inset = Math.min(48, viewport * 0.1);
  const fit = count > 1 ? (viewport - 2 * inset) / (count - 1) : 0;
  const spacing = fit + (Math.max(base, fit * 1.2) - fit) * zoom;
  const padding = zoom === 0 && count > 1 ? inset : viewport / 2;
  const width =
    zoom === 0 ? viewport : viewport + Math.max(0, count - 1) * spacing;
  // Leave room for orbiting names and dates above the bottom control tray.
  const center = height * 0.32;
  const amplitude = Math.min(112, height * 0.17) * (zoom === 0 ? 0.82 : 1);
  const wave = (x) =>
    spacing ? amplitude * Math.cos(((x - padding) / spacing) * Math.PI) : 0;
  const points = Array.from({ length: count }, (_, index) => ({
    x: padding + reverseIndex(index, count) * spacing,
    y: center - wave(padding + reverseIndex(index, count) * spacing),
    above: reverseIndex(index, count) % 2 === 0,
  }));
  const path = (direction) => {
    const samples = Math.ceil(width / Math.max(1, spacing / 18));
    return Array.from({ length: samples + 1 }, (_, index) => {
      const x = (index / samples) * width;
      return `${index ? "L" : "M"}${x.toFixed(2)},${(center + direction * wave(x)).toFixed(2)}`;
    }).join(" ");
  };
  const rungs = [];
  for (let x = 0; x <= width; x += Math.max(4, spacing / 10))
    rungs.push({ x, y1: center - wave(x), y2: center + wave(x) });
  return {
    width,
    spacing,
    center,
    amplitude,
    padding,
    points,
    rungs,
    front: path(-1),
    back: path(1),
    compact: count > 1 && spacing < 168,
    canPan: width > viewport + 0.5,
  };
}

export function createStrand(options) {
  const {
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
  } = options;
  const $ = (selector) => root.querySelector(selector);
  let events = [],
    selected = null,
    geometry = null,
    frame = 0,
    flowFrame = 0,
    lastFlow = 0,
    target = 0,
    zoom = 1,
    drag = null,
    resizing = false;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const isStrand = () =>
    element.classList.contains("horizontal") && Boolean(geometry);
  const indexOf = () =>
    Math.max(
      0,
      events.findIndex((event) => event.event_id === selected),
    );
  const eventDate = (event) => new Date(event.provider_at || event.received_at);
  const maximum = () => Math.max(0, element.scrollWidth - element.clientWidth);
  const noMotion = () => reduced.matches || root.dataset.motion === "off";
  const life = createStrandLife({ element, root, noMotion });

  function stopFlow() {
    cancelAnimationFrame(flowFrame);
    flowFrame = 0;
    lastFlow = 0;
    target = element.scrollLeft;
  }
  function navigateFrame(now) {
    const next = flowStep(
      element.scrollLeft,
      target,
      lastFlow ? now - lastFlow : 16,
    );
    lastFlow = now;
    element.scrollLeft = next;
    queueFocus();
    if (Math.abs(target - element.scrollLeft) > 2)
      flowFrame = requestAnimationFrame(navigateFrame);
    else {
      element.scrollLeft = target;
      flowFrame = 0;
      lastFlow = 0;
      queueFocus();
    }
  }
  function travel(left, instant = false) {
    target = clamp(left, 0, maximum());
    if (instant || noMotion()) {
      stopFlow();
      element.scrollLeft = clamp(left, 0, maximum());
      queueFocus();
      return;
    }
    if (!flowFrame) flowFrame = requestAnimationFrame(navigateFrame);
  }
  function navigator() {
    if (!geometry) return;
    const fraction = geometry.canPan
      ? Math.min(1, element.clientWidth / geometry.width)
      : 1;
    const start = geometry.canPan ? element.scrollLeft / geometry.width : 0;
    $("#navigator-window").style.setProperty(
      "--window-start",
      `${start * 100}%`,
    );
    $("#navigator-window").style.setProperty(
      "--window-width",
      `${fraction * 100}%`,
    );
    $("#navigator-cursor").style.left =
      `${events.length > 1 ? (reverseIndex(indexOf(), events.length) / (events.length - 1)) * 100 : 50}%`;
    $("#zoom-value").textContent =
      zoom === 0 ? "Fit · pan off" : `${Math.round(zoom * 100)}%`;
    $("#strand-zoom").value = zoom;
    $("#strand-zoom").setAttribute(
      "aria-valuetext",
      zoom === 0
        ? "Entire loaded strand, horizontal panning off"
        : `${Math.round(zoom * 100)} percent, horizontal panning on`,
    );
    $("#zoom-out").disabled = events.length < 2 || zoom === 0;
    $("#zoom-in").disabled = events.length < 2 || zoom === 2;
    $("#zoom-fit").disabled = events.length < 2;
    $("#zoom-fit").setAttribute("aria-pressed", String(zoom === 0));
    $("#strand-zoom").disabled = events.length < 2;
  }
  function select(identity) {
    selected = identity;
    element.querySelectorAll("[data-event]").forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.event === identity),
      );
      button
        .closest(".memory")
        ?.classList.toggle("is-selected", button.dataset.event === identity);
    });
    element
      .querySelectorAll("[data-node]")
      .forEach((node) =>
        node.classList.toggle("is-selected", node.dataset.node === identity),
      );
    navigator();
  }
  function updateFocus() {
    frame = 0;
    if (!isStrand()) return;
    const center = element.scrollLeft + element.clientWidth / 2;
    element.querySelectorAll(".memory").forEach((memory, index) => {
      const focus = geometry.compact
        ? events[index].event_id === selected
          ? 1
          : 0
        : clamp(
            1 -
              Math.abs(geometry.points[index].x - center) /
                (element.clientWidth * 0.65),
            0,
            1,
          );
      memory.style.setProperty("--focus", focus.toFixed(3));
    });
    if (geometry.canPan) {
      const nearest = reverseIndex(
        clamp(
          Math.round(element.scrollLeft / geometry.spacing),
          0,
          events.length - 1,
        ),
        events.length,
      );
      if (events[nearest] && events[nearest].event_id !== selected) {
        select(events[nearest].event_id);
        onSelect(selected);
      }
    }
    navigator();
    life.paint();
  }
  function queueFocus() {
    if (!frame) frame = requestAnimationFrame(updateFocus);
  }
  function seek(index, behavior = "smooth") {
    if (!events.length || !isStrand()) return;
    index = clamp(index, 0, events.length - 1);
    if (geometry.canPan)
      travel(
        reverseIndex(index, events.length) * geometry.spacing,
        behavior === "instant",
      );
    select(events[index].event_id);
    onSelect(selected);
    queueFocus();
  }
  function render(nextEvents, identity) {
    stopFlow();
    const arriving = nextEvents !== events;
    events = nextEvents;
    selected = identity;
    geometry = strandGeometry(
      events.length,
      element.clientWidth,
      element.clientHeight,
      zoom,
    );
    element.classList.toggle("is-overview", geometry.compact);
    element.dataset.canPan = String(geometry.canPan);
    const rails = (depth) =>
      ["cool", "warm"]
        .map(
          (tone, lane) =>
            `<path class="thread thread-${depth} thread-body strand-${tone}" data-lane="${lane}"/><path class="thread thread-${depth} thread-light strand-${tone}" data-lane="${lane}"/>`,
        )
        .join("");
    element.innerHTML = `<div class="strand-canvas${arriving ? " is-arriving" : ""}" style="width:${geometry.width}px"><svg class="strand-art" viewBox="0 0 ${geometry.width} ${element.clientHeight}" aria-hidden="true">${rails("far")}${[0, 1].map((pair) => [0, 1].map((side) => `<path class="rungs" data-pair="${pair}" data-side="${side}"/>`).join("")).join("")}${rails("near")}${geometry.points.map((point, index) => `<circle class="node ${gained(events[index]) ? "gain" : "lost"}" data-node="${esc(events[index].event_id)}" cx="${point.x}" cy="${point.y}" r="${geometry.compact ? 3 : 6.5}"/>`).join("")}</svg>${events
      .map((event, index) => {
        const point = geometry.points[index];
        const top = point.above
          ? Math.max(18, point.y - 154)
          : Math.min(element.clientHeight - 152, point.y + 38);
        const x = point.x;
        return `<article data-label-visible="false" aria-hidden="true" class="memory ${point.above ? "is-above" : "is-below"} ${gained(event) ? "gain" : "lost"}" style="left:${x}px;top:${top}px"><div class="memory-time">${esc(date.format(eventDate(event)))}<span>${esc(time.format(eventDate(event)))}${event.provider_at ? "" : " · received"}</span></div><button type="button" tabindex="-1" class="memory-button" data-event="${esc(event.event_id)}" aria-pressed="${event.event_id === identity}"><span class="memory-avatar" aria-hidden="true">${esc(initials(event))}</span><span class="memory-name">${esc(event.name || event.handle || "X account")}</span><span class="memory-handle">${esc(event.handle ? "@" + event.handle : "ID " + event.actor_id)}</span><span class="memory-kind"><span aria-hidden="true">${gained(event) ? "↗" : "↘"}</span>${esc(label(event))}</span></button></article>`;
      })
      .join("")}</div>`;
    element.querySelectorAll("[data-event]").forEach((button) =>
      button.addEventListener("click", () => {
        seek(
          events.findIndex((event) => event.event_id === button.dataset.event),
          "instant",
        );
        onOpen(button.dataset.event);
      }),
    );
    $("#navigator-marks").innerHTML = events
      .map(
        (_, index) =>
          `<i style="left:${events.length > 1 ? (index / (events.length - 1)) * 100 : 50}%"></i>`,
      )
      .join("");
    element.scrollLeft = geometry.canPan
      ? reverseIndex(indexOf(), events.length) * geometry.spacing
      : 0;
    target = element.scrollLeft;
    select(identity);
    life.mount(geometry);
    queueFocus();
  }
  function setZoom(value) {
    if (!isStrand() || events.length < 2) return;
    zoom = clamp(Math.round(value * 20) / 20, 0, 2);
    render(events, selected);
  }
  function onWheel(event) {
    if (!isStrand() || !geometry.canPan || event.ctrlKey || event.metaKey)
      return;
    if (!flowFrame) target = element.scrollLeft;
    const delta = wheelDistance(event, element.clientWidth);
    if (
      !delta ||
      (target <= 0 && delta < 0) ||
      (target >= maximum() && delta > 0)
    )
      return;
    event.preventDefault();
    const lead = element.clientWidth;
    travel(
      clamp(
        target + delta,
        element.scrollLeft - lead,
        element.scrollLeft + lead,
      ),
    );
  }
  function onPointerDown(event) {
    if (
      !isStrand() ||
      !geometry.canPan ||
      event.pointerType !== "mouse" ||
      event.button !== 0 ||
      event.target.closest("button,input,a")
    )
      return;
    stopFlow();
    drag = {
      id: event.pointerId,
      x: event.clientX,
      scroll: element.scrollLeft,
      lastX: event.clientX,
      lastTime: event.timeStamp,
      velocity: 0,
    };
    element.setPointerCapture(event.pointerId);
    element.dataset.panning = "true";
  }
  function onPointerMove(event) {
    if (!drag || drag.id !== event.pointerId) return;
    const elapsed = event.timeStamp - drag.lastTime;
    if (elapsed > 0) drag.velocity = (drag.lastX - event.clientX) / elapsed;
    element.scrollLeft = clamp(
      drag.scroll + drag.x - event.clientX,
      0,
      maximum(),
    );
    drag.lastX = event.clientX;
    drag.lastTime = event.timeStamp;
    queueFocus();
  }
  function onPointerEnd(event) {
    if (!drag || drag.id !== event.pointerId) return;
    const velocity = event.type === "pointercancel" ? 0 : drag.velocity;
    if (element.hasPointerCapture(event.pointerId))
      element.releasePointerCapture(event.pointerId);
    drag = null;
    delete element.dataset.panning;
    travel(
      element.scrollLeft +
        clamp(
          velocity * 180,
          -element.clientWidth * 0.8,
          element.clientWidth * 0.8,
        ),
    );
  }
  function onKey(event) {
    if (!isStrand() || event.altKey || event.ctrlKey || event.metaKey) return;
    const keys = {
      ArrowLeft: indexOf() + 1,
      ArrowRight: indexOf() - 1,
      ArrowUp: indexOf() + 1,
      ArrowDown: indexOf() - 1,
      Home: events.length - 1,
      End: 0,
    };
    if (Object.hasOwn(keys, event.key)) {
      event.preventDefault();
      seek(keys[event.key]);
    }
    if (["+", "=", "-", "0"].includes(event.key)) {
      event.preventDefault();
      setZoom(
        event.key === "0" ? 0 : zoom + (event.key === "-" ? -0.25 : 0.25),
      );
      element.focus({ preventScroll: true });
    }
  }
  const resize = new ResizeObserver(() => {
    if (
      !isStrand() ||
      resizing ||
      !element.clientWidth ||
      !element.clientHeight
    )
      return;
    resizing = true;
    requestAnimationFrame(() => {
      resizing = false;
      if (isStrand()) render(events, selected);
    });
  });
  resize.observe(element);
  const visibility = () => {
    root.dataset.suspended = String(document.hidden);
    if (document.hidden) stopFlow();
  };
  const preference = () => {
    if (reduced.matches) stopFlow();
    life.refresh();
    $("#motion-toggle").disabled = reduced.matches;
    $("#motion-toggle").setAttribute(
      "aria-pressed",
      String(!reduced.matches && root.dataset.motion === "on"),
    );
    $("#motion-toggle").textContent = reduced.matches
      ? "Reduced motion"
      : root.dataset.motion === "on"
        ? "Ambient motion on"
        : "Ambient motion paused";
  };
  const zoomIn = () => setZoom(zoom + 0.25),
    zoomOut = () => setZoom(zoom - 0.25),
    zoomFit = () => setZoom(0),
    zoomInput = (event) => setZoom(Number(event.target.value));
  const motionChange = () =>
    requestAnimationFrame(() => {
      if (noMotion()) stopFlow();
    });
  const listeners = [
    [element, "scroll", queueFocus, { passive: true }],
    [element, "keydown", onKey],
    [element, "wheel", onWheel, { passive: false }],
    [element, "pointerdown", onPointerDown],
    [element, "pointermove", onPointerMove],
    [element, "pointerup", onPointerEnd],
    [element, "pointercancel", onPointerEnd],
    [document, "visibilitychange", visibility],
    [$("#zoom-in"), "click", zoomIn],
    [$("#zoom-out"), "click", zoomOut],
    [$("#zoom-fit"), "click", zoomFit],
    [$("#strand-zoom"), "input", zoomInput],
    [$("#motion-toggle"), "click", motionChange],
  ];
  listeners.forEach(([target, type, listener, options]) =>
    target.addEventListener(type, listener, options),
  );
  reduced.addEventListener("change", preference);
  preference();
  return {
    render,
    select,
    seek,
    setZoom,
    move: (delta) => seek(indexOf() + delta),
    clear: () => {
      stopFlow();
      life.clear();
      geometry = null;
      $("#navigator-marks").replaceChildren();
      $("#navigator-window").style.setProperty("--window-width", "0%");
      $("#navigator-cursor").style.left = "0%";
      ["#zoom-in", "#zoom-out", "#zoom-fit", "#strand-zoom"].forEach(
        (id) => ($(id).disabled = true),
      );
    },
    destroy: () => {
      stopFlow();
      life.destroy();
      cancelAnimationFrame(frame);
      resize.disconnect();
      listeners.forEach(([target, type, listener, options]) =>
        target.removeEventListener(type, listener, options),
      );
      reduced.removeEventListener("change", preference);
    },
  };
}
