const TAU = Math.PI * 2;

export function normalizeTwistSpeed(value) {
  const speed = Number(value);
  return Number.isFinite(speed) ? Math.max(0.25, Math.min(2, speed)) : 1;
}

export function visibleMemoryLabels(candidates, selected, previous = new Set()) {
  const shown = [];
  const priority = (candidate) =>
    candidate.index === selected ? 0 : previous.has(candidate.index) ? 1 : 2;
  [...candidates]
    .sort((a, b) => priority(a) - priority(b) || a.distance - b.distance)
    .forEach((candidate) => {
      const overlaps = shown.some(
        (other) =>
          candidate.left < other.right + 12 &&
          candidate.right > other.left - 12 &&
          candidate.top < other.bottom + 12 &&
          candidate.bottom > other.top - 12,
      );
      if (!overlaps) shown.push(candidate);
    });
  return new Set(shown.map((candidate) => candidate.index));
}

export function projectHelixPoint(x, geometry, phase, turn = 0) {
  const angle = geometry.spacing
    ? ((x - geometry.padding) / geometry.spacing) * Math.PI + turn
    : 0;
  const radius = geometry.spacing ? geometry.amplitude : 0;
  const y = -radius * Math.cos(angle);
  const z = radius * Math.sin(angle);
  const depth = y * Math.sin(phase) + z * Math.cos(phase);
  return {
    x: x + depth * 0.18,
    y: geometry.center + y * Math.cos(phase) - z * Math.sin(phase),
    depth,
    scale: 1,
  };
}

export function createStrandLife({ element, root, noMotion }) {
  let geometry = null,
    memories = [],
    nodes = [],
    near = [],
    far = [],
    rungs = null,
    phase = 0,
    frame = 0,
    previous = 0,
    sizes = [],
    measuredSelection = -1,
    shown = new Set();

  function measureLabels(selected) {
    sizes = memories.map((memory) => ({
      width: memory.offsetWidth,
      height: memory.offsetHeight,
      date: memory.querySelector(".memory-time").offsetHeight,
    }));
    measuredSelection = selected;
  }

  function paint() {
    if (!geometry) return;
    const selected = memories.findIndex((memory) =>
      memory.classList.contains("is-selected"),
    );
    if (selected !== measuredSelection) measureLabels(selected);
    const pose = {
      ...geometry,
      amplitude: geometry.amplitude * (1 + 0.015 * Math.sin(phase * 3)),
    };
    const left = Math.max(0, element.scrollLeft - 240);
    const right = Math.min(
      geometry.width,
      element.scrollLeft + element.clientWidth + 240,
    );
    const step = Math.max(1, Math.min(12, geometry.spacing / 12));
    const samples = Math.min(1600, Math.ceil((right - left) / step));
    const paths = [
      [[], []],
      [[], []],
    ];
    for (const [lane, turn] of [0, Math.PI].entries()) {
      let last = projectHelixPoint(left, pose, phase, turn);
      for (let index = 1; index <= samples; index++) {
        const point = projectHelixPoint(
          left + ((right - left) * index) / samples,
          pose,
          phase,
          turn,
        );
        paths[lane][(point.depth + last.depth) / 2 >= 0 ? 1 : 0].push(
          `M${last.x.toFixed(1)},${last.y.toFixed(1)}L${point.x.toFixed(1)},${point.y.toFixed(1)}`,
        );
        last = point;
      }
    }
    paths.forEach((sections, lane) => {
      const frontPath = sections[1].join(" ");
      const rearPath = sections[0].join(" ");
      near[lane].forEach((path) => path.setAttribute("d", frontPath));
      far[lane].forEach((path) => path.setAttribute("d", rearPath));
    });
    const bridges = [
      [[], []],
      [[], []],
    ];
    const rungStep = Math.max(
      8,
      geometry.spacing / 9,
      element.clientWidth / 80,
    );
    for (
      let x = Math.ceil(left / rungStep) * rungStep;
      x < right;
      x += rungStep
    ) {
      const a = projectHelixPoint(x, pose, phase);
      const b = projectHelixPoint(x, pose, phase, Math.PI);
      const middleX = (a.x + b.x) / 2;
      const middleY = (a.y + b.y) / 2;
      const pair = Math.round(x / rungStep) % 2;
      bridges[pair][0].push(
        `M${a.x.toFixed(1)},${a.y.toFixed(1)}L${middleX.toFixed(1)},${middleY.toFixed(1)}`,
      );
      bridges[pair][1].push(
        `M${middleX.toFixed(1)},${middleY.toFixed(1)}L${b.x.toFixed(1)},${b.y.toFixed(1)}`,
      );
    }
    bridges.forEach((pair, index) =>
      pair.forEach((side, sideIndex) =>
        rungs[index][sideIndex].setAttribute("d", side.join(" ")),
      ),
    );
    const candidates = [];
    geometry.points.forEach((base, index) => {
      if (base.x < left || base.x > right) return;
      const point = projectHelixPoint(base.x, pose, phase);
      const memory = memories[index];
      const size = sizes[index];
      const originTop = Number.parseFloat(memory.style.top);
      const compact = geometry.compact && index !== selected;
      const baseTop = compact
        ? base.y + (base.above ? -size.height - 22 : 22)
        : originTop;
      const labelY = baseTop + size.height / 2 - geometry.center;
      const offsetY = labelY * (Math.cos(phase) - 1);
      let offsetX = labelY * Math.sin(phase) * 0.18;
      const height = size.height + (size.date ? size.date + 8 : 0);
      const top = Math.max(
        16,
        Math.min(element.clientHeight - height - 16, baseTop + offsetY),
      );
      let labelX = base.x + offsetX - element.scrollLeft;
      if (index === selected) {
        labelX = Math.max(
          size.width / 2 + 16,
          Math.min(element.clientWidth - size.width / 2 - 16, labelX),
        );
        offsetX = labelX + element.scrollLeft - base.x;
      }
      memory.style.setProperty("--orbit-x", `${offsetX.toFixed(2)}px`);
      memory.style.setProperty("--orbit-y", `${(top - originTop).toFixed(2)}px`);
      memory.style.setProperty("--depth-scale", "1");
      const room = Math.min(
        labelX - size.width / 2,
        element.clientWidth - labelX - size.width / 2,
      );
      if (room >= 16)
        candidates.push({
          index,
          left: labelX - size.width / 2,
          right: labelX + size.width / 2,
          top,
          bottom: top + height,
          distance: Math.abs(labelX - element.clientWidth / 2),
        });
      memory.style.setProperty(
        "--edge-opacity",
        String(index === selected ? 1 : Math.max(0, Math.min(1, (room - 16) / 32))),
      );
      nodes[index].setAttribute("cx", point.x.toFixed(2));
      nodes[index].setAttribute("cy", point.y.toFixed(2));
      nodes[index].setAttribute(
        "r",
        ((geometry.compact ? 3 : 6.5) * point.scale).toFixed(2),
      );
      nodes[index].style.opacity = (0.8 + point.depth / 400).toFixed(3);
    });
    shown = visibleMemoryLabels(candidates, selected, shown);
    memories.forEach((memory, index) => {
      const visible = shown.has(index);
      if (!visible) memory.style.setProperty("--edge-opacity", "0");
      if (memory.dataset.labelVisible !== String(visible)) {
        memory.style.visibility = visible ? "visible" : "hidden";
        memory.dataset.labelVisible = String(visible);
        memory.setAttribute("aria-hidden", String(!visible));
        memory.querySelector(".memory-button").tabIndex = visible ? 0 : -1;
      }
    });
  }
  function stop() {
    cancelAnimationFrame(frame);
    frame = 0;
    previous = 0;
    element.dataset.living = "paused";
  }
  function tick(now) {
    if (!root.isConnected) {
      stop();
      return;
    }
    // Cap resumed frames so background-tab time never becomes an orbital jump.
    if (previous)
      phase =
        (phase +
          (Math.min(now - previous, 64) / 12000) *
            TAU *
            normalizeTwistSpeed(root.dataset.twistSpeed ?? 1)) %
        TAU;
    previous = now;
    paint();
    frame = requestAnimationFrame(tick);
  }
  function refresh() {
    const paused =
      !geometry ||
      !root.isConnected ||
      noMotion() ||
      document.hidden ||
      root.dataset.route !== "timeline";
    if (paused) stop();
    else if (!frame) {
      element.dataset.living = "running";
      frame = requestAnimationFrame(tick);
    }
  }
  const mutation = new MutationObserver(refresh);
  mutation.observe(root, {
    attributes: true,
    subtree: true,
    attributeFilter: ["data-motion", "data-route"],
  });
  const listeners = [[document, "visibilitychange", refresh]];
  listeners.forEach(([target, type, listener]) =>
    target.addEventListener(type, listener),
  );
  return {
    mount(nextGeometry) {
      stop();
      geometry = nextGeometry;
      memories = [...element.querySelectorAll(".memory")];
      measureLabels(
        memories.findIndex((memory) => memory.classList.contains("is-selected")),
      );
      shown = new Set();
      nodes = [...element.querySelectorAll("[data-node]")];
      near = [0, 1].map((lane) => [
        ...element.querySelectorAll(`.thread-near[data-lane="${lane}"]`),
      ]);
      far = [0, 1].map((lane) => [
        ...element.querySelectorAll(`.thread-far[data-lane="${lane}"]`),
      ]);
      rungs = [0, 1].map((pair) =>
        [0, 1].map((side) =>
          element.querySelector(
            `.rungs[data-pair="${pair}"][data-side="${side}"]`,
          ),
        ),
      );
      paint();
      refresh();
    },
    paint,
    refresh,
    clear() {
      stop();
      geometry = null;
      memories = [];
      nodes = [];
    },
    destroy() {
      stop();
      mutation.disconnect();
      listeners.forEach(([target, type, listener]) =>
        target.removeEventListener(type, listener),
      );
    },
  };
}
