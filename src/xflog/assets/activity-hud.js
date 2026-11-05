import { bindPopover } from "./popover.js";

const labels = {
  followers: [
    "Follows",
    "Unfollows",
    "Follows / h",
    "Unfollows / h",
    "Growth ratio",
  ],
  subscriptions: [
    "Subscribers",
    "Expired",
    "New / h",
    "Expired / h",
    "Growth ratio",
  ],
};
const keys = ["gained", "lost", "gain_rate", "loss_rate", "ratio"];
const decimal = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const counts = new Intl.NumberFormat(undefined, {
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatReading(value) {
  if (value === null || value === undefined) return "—";
  const text =
    value >= 10000
      ? counts.format(value)
      : value > 0 && value < 0.01
        ? "<0.01"
        : decimal.format(value);
  return text;
}

export function formatChange(key, metric) {
  const percent = metric?.change_percent;
  const newValue = metric?.comparison === "new";
  if (!newValue && !Number.isFinite(percent))
    return { text: "—", tone: "neutral" };
  const up = newValue || percent > 0;
  const good = key === "lost" || key === "loss_rate" ? !up : up;
  const magnitude = Math.abs(percent);
  const amount = newValue
    ? "New"
    : magnitude > 0 && magnitude < 0.1
      ? "<0.1%"
      : `${decimal.format(magnitude)}%`;
  return {
    text: `${up ? "↑" : percent < 0 ? "↓" : "→"} ${amount}`,
    tone: !newValue && percent === 0 ? "neutral" : good ? "good" : "bad",
  };
}

export function createActivityHud({ root, api, context }) {
  const $ = (selector) => root.querySelector(selector);
  const hud = $("#activity-hud");
  const trigger = $("#activity-period-trigger");
  const picker = $("#activity-periods");
  const menu = bindPopover(trigger, picker, "above");
  let period = "24h",
    generation = 0,
    signature = "",
    destroyed = false;
  const cells = keys.map((key) => {
    const cell = document.createElement("div");
    cell.className = `hud-metric hud-${key}`;
    const term = document.createElement("dt");
    const label = document.createElement("span");
    label.tabIndex = 0;
    const tip = document.createElement("span");
    tip.id = `activity-tip-${key}`;
    tip.className = "hud-tip";
    tip.setAttribute("role", "tooltip");
    label.setAttribute("aria-describedby", tip.id);
    term.append(label, tip);
    for (const event of ["pointerenter", "focusin"])
      term.addEventListener(event, () => {
        tip.hidden = false;
      });
    term.addEventListener("keydown", (event) => {
      if (event.key === "Escape") tip.hidden = true;
    });
    const value = document.createElement("dd");
    value.className = "hud-value";
    const change = document.createElement("dd");
    change.className = "hud-change";
    cell.append(term, value, change);
    $("#activity-readings").append(cell);
    return { label, tip, value, change };
  });
  function clear(subject) {
    cells.forEach((cell, index) => {
      cell.label.textContent = labels[subject][index];
      const definition =
        index < 2
          ? "Events received in this period, across the full local log."
          : index < 4
            ? "Recorded events divided by the period’s hours, not a percentage of your audience."
            : subject === "subscriptions"
              ? "New subscriptions divided by expirations. — means no expirations."
              : "Follows divided by unfollows. — means no unfollows.";
      cell.tip.textContent = `${definition} Compared with the previous ${period}. Green means more gains or fewer losses; New means the previous value was zero.`;
      cell.value.textContent = "—";
      cell.value.removeAttribute("title");
      cell.change.textContent = "—";
      cell.change.removeAttribute("title");
      cell.change.dataset.tone = "neutral";
    });
  }
  function markPeriod() {
    for (const button of picker.querySelectorAll("button"))
      button.setAttribute(
        "aria-checked",
        String(button.dataset.period === period),
      );
  }
  function renderPeriods(periods) {
    if (picker.dataset.periods === periods.join()) return;
    picker.dataset.periods = periods.join();
    picker.replaceChildren();
    for (const option of periods) {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "menuitemradio");
      button.dataset.period = option;
      button.textContent = option;
      button.tabIndex = -1;
      button.addEventListener("click", () => {
        period = option;
        menu.close();
        refresh();
      });
      picker.append(button);
    }
  }
  async function refresh() {
    if (destroyed) return;
    const ticket = ++generation;
    const { demo, subject } = context();
    const nextSignature = `${period}/${subject}/${demo}`;
    if (signature !== nextSignature) {
      clear(subject);
      trigger.title = "Choose activity period";
    }
    signature = nextSignature;
    hud.setAttribute("aria-busy", "true");
    $("#activity-period-value").textContent = period;
    trigger.setAttribute("aria-label", `Activity period: ${period}`);
    markPeriod();
    try {
      const result = await api(
        `/api/activity-summary?${new URLSearchParams({ period, subject, demo })}`,
      );
      if (ticket !== generation || destroyed) return;
      renderPeriods(result.periods);
      markPeriod();
      cells.forEach((cell, index) => {
        const key = keys[index],
          metric = result.metrics[key];
        cell.value.textContent = formatReading(metric.value);
        const change = formatChange(key, metric);
        cell.change.textContent = change.text;
        cell.change.dataset.tone = change.tone;
        cell.value.title = `${labels[subject][index]}: ${metric.value === null ? "no unfollows or expirations to divide by" : metric.value.toLocaleString(undefined, { maximumFractionDigits: 8 })}. Previous ${period}: ${metric.previous === null ? "—" : metric.previous.toLocaleString(undefined, { maximumFractionDigits: 8 })}.`;
        cell.change.title = `Compared with the preceding ${period}`;
      });
      trigger.title = `${demo ? "Demo log · " : ""}${new Date(result.start).toLocaleString()} – ${new Date(result.end).toLocaleString()}`;
      $("#activity-error").hidden = true;
    } catch {
      if (ticket !== generation || destroyed) return;
      clear(subject);
      $("#activity-error").hidden = false;
    } finally {
      if (ticket === generation) hud.setAttribute("aria-busy", "false");
    }
  }
  clear("followers");
  return {
    refresh,
    destroy() {
      destroyed = true;
      generation++;
      menu.destroy();
    },
  };
}
