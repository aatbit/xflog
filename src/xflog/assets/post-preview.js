import { esc, postLink } from "./format.js";

export function postPreview(event, limit, className) {
  const link = event.kind.startsWith("interaction.") ? postLink(event.post_id) : "";
  const characters = Array.from(typeof event.post_text === "string" ? event.post_text.trim() : "");
  const excerpt = characters.length > limit
    ? characters.slice(0, limit - 1).join("") + "…" : characters.join("");
  return link && excerpt
    ? `<a class="${className}" href="${esc(link)}" target="_blank" rel="noopener noreferrer"><span>${esc(excerpt)}</span><span aria-hidden="true">↗</span><span class="sr-only">Open post on X</span></a>` : "";
}
