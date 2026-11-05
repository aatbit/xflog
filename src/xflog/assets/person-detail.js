import {
  esc,
  eventTone,
  eventLabel,
  initials,
  dateFormat,
  timeFormat,
  fullFormat,
} from "./format.js";
import { followButtonMarkup } from "./follow-actions.js";
import { interactionMarkup } from "./interactions.js";

export function renderPersonDetail(root, event) {
  const safeLink =
    typeof event.profile_url === "string" &&
    /^https:\/\/x\.com\/[A-Za-z0-9_]{1,15}$/.test(event.profile_url);
  const name = esc(event.name || event.handle || "X account");
  const personName = safeLink
    ? `<a href="${esc(event.profile_url)}" target="_blank" rel="noopener noreferrer">${name}<span class="detail-name-link" aria-hidden="true">↗</span><span class="sr-only"> on X</span></a>`
    : name;
  const detailTime = (value) =>
    value
      ? `<time datetime="${esc(value)}" title="${esc(fullFormat.format(new Date(value)))}">${esc(dateFormat.format(new Date(value)))} · ${esc(timeFormat.format(new Date(value)))}</time>`
      : '<span title="Not supplied by X">—</span>';
  const detail = `<h2>Event details</h2><div class="detail-person"><span class="avatar" aria-hidden="true">${esc(initials(event))}</span><div class="detail-identity"><h3>${personName}</h3><p>${esc(event.handle ? "@" + event.handle : "ID " + event.actor_id)}</p></div></div><div class="detail-kind ${eventTone(event) === "negative" ? "lost" : eventTone(event)}"><span aria-hidden="true">${eventTone(event) === "neutral" ? "·" : eventTone(event) === "positive" ? "↗" : "↘"}</span>${eventLabel(event)}</div><dl class="detail-data"><div><dt>Event time</dt><dd>${detailTime(event.provider_at)}</dd></div><div><dt>Received</dt><dd>${detailTime(event.received_at)}</dd></div><div><dt>Account ID</dt><dd>${esc(event.actor_id)}</dd></div></dl>`;
  const panel = root.querySelector("#mobile-detail");
  panel.innerHTML = detail;
  panel
    .querySelector(".detail-person")
    .insertAdjacentHTML("beforeend", followButtonMarkup);
  panel.insertAdjacentHTML("beforeend", interactionMarkup);
}
