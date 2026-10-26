import { groupEvents } from "./audience-groups.js";
import { verificationBadge } from "./verification-badge.js";

const profileSignals = ["verification", "account-size", "account-age"];

export function createSelectedSignal({
  root,
  label,
  gained,
  date,
  time,
  fullDate,
  onOpen,
}) {
  const $ = (selector) => root.querySelector(selector);
  const button = $("#selected-signal");
  const identityColumn = $("#signal-identity");
  const profile = $("#signal-profile");
  function fitProfile() {
    const nameRoom = 120;
    let room =
      identityColumn.clientWidth -
      nameRoom -
      parseFloat(getComputedStyle(identityColumn).gap);
    const gap = parseFloat(getComputedStyle(profile).gap);
    const facts = [...profile.children];
    profile.hidden = false;
    for (const fact of facts) fact.hidden = false;
    const widths = facts.map((fact) => fact.getBoundingClientRect().width);
    let visible = 0;
    for (const [index, fact] of facts.entries()) {
      const width = widths[index];
      fact.hidden = room < width;
      if (!fact.hidden) {
        room -= width + gap;
        visible++;
      }
    }
    profile.hidden = visible === 0;
  }
  // Gradio strips container queries; measure this column without changing its CSS pipeline.
  const resize = new ResizeObserver(fitProfile);
  resize.observe(identityColumn);
  let identity = null;
  button.addEventListener("click", () => {
    if (identity) onOpen(identity);
  });
  return {
    render(event, modules = []) {
      identity = event?.event_id || null;
      button.hidden = !event;
      profile.replaceChildren();
      profile.hidden = true;
      if (!event) return;
      for (const key of profileSignals) {
        const module = modules.find((item) => item.key === key && item.enabled);
        if (!module) continue;
        const bucket = groupEvents([event], [module], key)[0];
        const fact = document.createElement("span");
        fact.className = "signal-fact";
        fact.hidden = true;
        fact.dataset.signal = key;
        fact.title = `${module.label}: ${bucket.label}. ${module.description}`;
        const caption = document.createElement("small");
        caption.textContent = module.label;
        const value = document.createElement("span");
        value.textContent = bucket.label;
        fact.append(caption, value);
        profile.append(fact);
      }
      const name = event.name || event.handle || "X account";
      const received = new Date(event.received_at);
      $("#signal-name").textContent = name;
      $("#signal-name").title = name;
      $("#signal-verification").innerHTML = verificationBadge(event, modules);
      $("#signal-handle").textContent = event.handle
        ? `@${event.handle}`
        : `ID ${event.actor_id}`;
      $("#signal-activity").textContent = label(event);
      button.dataset.tone = gained(event) ? "gained" : "lost";
      const timestamp = $("#signal-received");
      timestamp.dateTime = event.received_at;
      timestamp.textContent = `${date.format(received)} · ${time.format(received)}`;
      timestamp.title = `Received by XFlog: ${fullDate.format(received)}`;
      button.setAttribute(
        "aria-label",
        `Open selected signal details for ${name}`,
      );
      fitProfile();
    },
    destroy() {
      resize.disconnect();
    },
  };
}
