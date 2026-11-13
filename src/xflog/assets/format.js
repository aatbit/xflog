export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[char],
  );
export const postLink = (id) =>
  /^[0-9]{1,19}$/.test(id) ? `https://x.com/i/status/${id}` : "";
export const dateFormat = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
});
export const timeFormat = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
});
export const fullFormat = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
  timeZoneName: "short",
});
export const gained = (event) =>
  ["follow.follow", "subscriptions.subscribe"].includes(event.kind);
export const eventTone = (event) => gained(event) ? "positive" :
  ["follow.unfollow", "subscriptions.unsubscribe"].includes(event.kind) ? "negative" : "neutral";
const interactions = {
  replies: "Replied to you", mentions: "Mentioned you", quotes: "Quoted your post",
  reposts: "Reposted your post", likes_received: "Liked your post",
  likes_given: "You liked their post", your_posts: "Your post or reply",
};
export const eventLabel = (event) =>
  event.kind.startsWith("interaction.") ? interactions[event.kind.slice(12)] || "Interaction" :
  event.kind.startsWith("subscriptions.")
    ? gained(event)
      ? "Subscribed"
      : "Expired"
    : gained(event)
      ? "Followed you"
      : "Unfollowed";
export const displayDate = (event) =>
  new Date(event.provider_at || event.received_at);
export function compareEvents(a, b) {
  if (a.received_at && b.received_at && a.received_at !== b.received_at)
    return a.received_at < b.received_at ? 1 : -1;
  return Number(b.sequence > 0) - Number(a.sequence > 0) ||
    Math.abs(Number(b.sequence)) - Math.abs(Number(a.sequence));
}
export const initials = (event) =>
  (event.name || event.handle || "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
