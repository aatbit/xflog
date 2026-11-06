import { esc, eventLabel, eventTone } from "./format.js";

const paths = {
  "follow.follow": '<circle cx="9" cy="7" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2m4-13v8m-4-4h8"/>',
  "follow.unfollow": '<circle cx="9" cy="7" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2m0-9h8"/>',
  "subscriptions.subscribe": '<path d="m12 3 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1Z"/>',
  "subscriptions.unsubscribe": '<path d="M4 4l16 16M10 6l2-3 3 6 7 1-5 5m-1 4-4-2-6 3 1-7-5-3 4-1"/>',
  "interaction.replies": '<path d="M9 5 3 11l6 6m-6-6h11a6 6 0 0 1 6 6v2"/>',
  "interaction.mentions": '<circle cx="12" cy="12" r="4"/><path d="M16 8v6a2 2 0 0 0 4 0v-2a8 8 0 1 0-3 6"/>',
  "interaction.quotes": '<path d="M4 6h6v7H4V6Zm10 0h6v7h-6V6ZM10 13c0 4-2 5-5 5m15-5c0 4-2 5-5 5"/>',
  "interaction.reposts": '<path d="m4 8 4-4 4 4M8 4v12h6m6 0-4 4-4-4m4 4V8h-6"/>',
  "interaction.likes_received": '<path d="M12 21 3 12a5 5 0 0 1 9-7 5 5 0 0 1 9 7Z"/>',
  "interaction.likes_given": '<path d="M12 21 3 12a5 5 0 0 1 9-7 5 5 0 0 1 9 7ZM9 11h6m-3-3 3 3-3 3"/>',
  "interaction.your_posts": '<path d="M4 5h10M4 10h7M4 15h5m4 5 7-7-3-3-7 7-1 4Z"/>',
};
export function activityIcon(event) {
  const label = esc(eventLabel(event));
  return `<span class="star-kind ${eventTone(event)}" title="${label}"><svg viewBox="0 0 24 24" aria-hidden="true">${paths[event.kind] || '<circle cx="12" cy="12" r="7"/>'}</svg><span class="sr-only">${label}</span></span>`;
}
