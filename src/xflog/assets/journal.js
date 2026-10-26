import { groupEvents } from "./audience-groups.js";

export function createJournal({
  element,
  escape: esc,
  date,
  time,
  displayDate,
  gained,
  label,
  initials,
  onOpen,
}) {
  const collapsed = new Set();
  let lens = "none";

  function rows(events, selected) {
    let prior = "";
    return events
      .map((event) => {
        const day = date.format(displayDate(event));
        const heading =
          day !== prior ? `<div class="date-group">${esc(day)}</div>` : "";
        prior = day;
        const lost = !gained(event);
        return `${heading}<article class="event ${lost ? "lost" : "gain"}"><span class="event-dot" aria-hidden="true"></span><button type="button" class="event-button" data-event="${esc(event.event_id)}" aria-pressed="${selected === event.event_id}"><span class="avatar" aria-hidden="true">${esc(initials(event))}</span><span class="event-identity"><span class="event-name">${esc(event.name || event.handle || "X account")}</span><span class="event-handle">${esc(event.handle ? "@" + event.handle : "ID " + event.actor_id)}</span></span><span class="event-meta"><span class="event-kind"><span aria-hidden="true">${lost ? "↘" : "↗"}</span>${esc(label(event))}</span><span class="event-time">${esc(time.format(displayDate(event)))}${event.provider_at ? "" : " · received"}</span></span></button></article>`;
      })
      .join("");
  }

  return {
    render(events, options) {
      lens = options.lens;
      const groups = groupEvents(events, options.modules, lens);
      element.innerHTML = groups
        ? groups
            .map(
              (group) =>
                `<details class="journal-group ${esc(group.tone)}" data-group="${esc(group.key)}" ${collapsed.has(`${lens}:${group.key}`) ? "" : "open"}><summary><span class="journal-group-name">${esc(group.label)}</span> <span class="journal-group-count">${group.events.length} ${group.events.length === 1 ? "event" : "events"}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg></summary><div class="journal-group-content">${rows(group.events, options.selected)}</div></details>`,
            )
            .join("")
        : rows(events, options.selected);
      element.querySelectorAll("details[data-group]").forEach((group) => {
        const key = `${lens}:${group.dataset.group}`;
        group.addEventListener("toggle", () => {
          if (group.open) collapsed.delete(key);
          else collapsed.add(key);
        });
      });
      element
        .querySelectorAll("[data-event]")
        .forEach((button) =>
          button.addEventListener("click", () => onOpen(button.dataset.event)),
        );
    },
    reveal(identity) {
      const button = [...element.querySelectorAll("[data-event]")].find(
        (item) => item.dataset.event === identity,
      );
      if (!button) return;
      const group = button.closest("details[data-group]");
      if (group) {
        collapsed.delete(`${lens}:${group.dataset.group}`);
        group.open = true;
      }
      button.scrollIntoView({ block: "nearest" });
    },
  };
}
