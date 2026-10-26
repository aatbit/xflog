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
  let identity = null;
  button.addEventListener("click", () => {
    if (identity) onOpen(identity);
  });
  return {
    render(event) {
      identity = event?.event_id || null;
      button.hidden = !event;
      if (!event) return;
      const name = event.name || event.handle || "X account";
      const received = new Date(event.received_at);
      $("#signal-name").textContent = name;
      $("#signal-name").title = name;
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
    },
  };
}
