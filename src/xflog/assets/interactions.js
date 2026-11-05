export const interactionMarkup = `<section data-interaction-panel><button type="button" class="interaction-launch" data-open-interactions aria-haspopup="dialog">Interaction history <span aria-hidden="true">→</span></button></section>`;

export function groupInteractions(rows) {
  const groups = new Map();
  for (const row of rows) {
    const key = row.conversation_id
      ? `c${row.conversation_id}`
      : `p${row.post_id}`;
    if (!groups.has(key)) groups.set(key, { key, rows: [] });
    groups.get(key).rows.push(row);
  }
  return [...groups.values()];
}

export function recordedPosts(rows) {
  const posts = new Map();
  for (const row of rows) {
    if (!posts.has(row.post_id))
      posts.set(row.post_id, {
        id: row.post_id,
        author_id: row.author_id,
        text: row.text,
        recorded_at: row.provider_at,
      });
  }
  return [...posts.values()].sort(
    (a, b) => a.id.length - b.id.length || a.id.localeCompare(b.id),
  );
}

export function createInteractionControls({ root, api, esc, onReturn = () => {} }) {
  const dialog = root.querySelector("#interaction-dialog");
  const content = dialog.querySelector("[data-interaction-content]");
  const personDialog = root.querySelector("#detail-dialog");
  let selected = null,
    context = {},
    revision = 0,
    opened = false,
    returnToPerson = false;
  let rows = [],
    next = null,
    loaded = false,
    busy = false,
    refreshPending = false,
    error = "",
    destroyed = false;
  const threads = new Map();
  const date = (value) => new Date(value).toLocaleString();
  const postLink = (id) =>
    /^[0-9]{1,19}$/.test(id) ? `https://x.com/i/status/${id}` : "";
  const names = {
    replies: ["reply", "replies"],
    mentions: ["mention", "mentions"],
    quotes: ["quote", "quotes"],
    reposts: ["repost", "reposts"],
    likes_received: ["like received", "likes received"],
    likes_given: ["like sent", "likes sent"],
    your_posts: ["post from you", "posts from you"],
  };
  function activity(group) {
    const counts = new Map();
    for (const row of group.rows)
      counts.set(row.kind, (counts.get(row.kind) || 0) + 1);
    return [...counts]
      .map(
        ([kind, count]) =>
          `${count} ${(names[kind] || ["interaction", "interactions"])[count === 1 ? 0 : 1]}`,
      )
      .join(" · ");
  }
  function postMarkup(post) {
    const author =
      post.author_id === context.account
        ? "You"
        : post.author_id === selected?.actor_id
          ? selected.name || selected.handle || "This person"
          : "Other participant";
    const initials =
      author === "Other participant"
        ? "·"
        : author
            .split(/\s+/)
            .slice(0, 2)
            .map((word) => word[0])
            .join("");
    const moment = post.created_at || post.recorded_at;
    const stamp = moment
      ? new Date(moment).toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        })
      : "Post";
    return `<li class="conversation-post"><span class="post-avatar" aria-hidden="true">${esc(initials)}</span><div class="post-content"><header><strong>${esc(author)}</strong><a href="${postLink(post.id)}" target="_blank" rel="noopener noreferrer" aria-label="Open post by ${esc(author)} on X" title="${esc(moment ? `${post.created_at ? "Posted" : "Recorded"} ${date(moment)} · Open on X` : "Open post on X")}">${esc(stamp)} <span aria-hidden="true">↗</span></a></header><p>${esc(post.text || "Post text not supplied.")}</p></div></li>`;
  }
  function conversationMarkup(group) {
    const thread = threads.get(group.key);
    const data = thread?.data;
    const expanded = Boolean(thread?.expanded);
    const status = data
      ? `${data.total} saved posts`
      : group.rows.some((item) => item.thread_saved)
        ? "Open saved thread"
        : "Load thread · X reads";
    const posts = expanded && data ? data.posts : recordedPosts(group.rows);
    return `<section class="conversation" data-conversation="${group.key}"><header class="conversation-header"><button type="button" class="conversation-toggle" data-thread-action="open" data-group="${group.key}" aria-expanded="${expanded}" aria-disabled="${busy || Boolean(thread?.busy)}"><span><strong>${esc(activity(group))}</strong><small>${esc(status)}</small></span><span aria-hidden="true">${expanded ? "−" : "+"}</span></button></header>${thread?.busy ? '<p class="interaction-caption" role="status">Loading conversation…</p>' : ""}${thread?.error ? `<p class="interaction-error" role="status">${esc(thread.error)}</p>` : ""}${expanded && data ? `<div class="conversation-meta"><span>Snapshot · X checked ${esc(date(data.checked_at))}</span><button type="button" class="text-button" data-thread-action="refresh" data-group="${group.key}" aria-disabled="${busy || Boolean(thread?.busy)}">Refresh · X reads</button></div>` : ""}<ol class="conversation-posts">${posts.map(postMarkup).join("")}</ol>${expanded && data ? `<footer class="thread-actions">${data.more_saved ? `<button type="button" class="text-button" data-thread-action="cached" data-group="${group.key}">More saved</button>` : ""}${data.more_available ? `<button type="button" class="text-button" data-thread-action="more" data-group="${group.key}">Load more · X reads</button>` : ""}</footer>` : ""}</section>`;
  }
  function render() {
    if (!opened) return;
    const active = content.ownerDocument?.activeElement;
    let restore = null;
    if (
      active &&
      content.contains(active) &&
      active.matches("[data-thread-action]")
    ) {
      restore = `[data-thread-action="${active.dataset.threadAction}"][data-group="${active.dataset.group}"]`;
    }
    if (
      active &&
      content.contains(active) &&
      active.matches("[data-more-interactions]")
    )
      restore = "[data-more-interactions]";
    dialog.querySelector("#interaction-person").textContent = selected
      ? `${selected.name || selected.handle || "X account"}${selected.handle ? ` · @${selected.handle}` : ""}`
      : "";
    content.innerHTML = `${error ? `<p class="interaction-error" role="status">${esc(error)}</p>` : ""}${busy ? '<p class="interaction-caption" role="status">Loading saved activity…</p>' : ""}${loaded && !rows.length ? '<p class="interaction-empty">No recorded interactions.</p>' : ""}${groupInteractions(rows).map(conversationMarkup).join("")}${next ? '<button type="button" class="text-button" data-more-interactions>Older interactions</button>' : ""}`;
    for (const button of content.querySelectorAll("[data-thread-action]"))
      button.setAttribute(
        "aria-disabled",
        String(busy || Boolean(threads.get(button.dataset.group)?.busy)),
      );
    if (restore)
      (
        content.querySelector(restore) ||
        dialog.querySelector("#interaction-title")
      )?.focus({ preventScroll: true });
  }
  async function loadHistory(append = false) {
    if (!selected || busy || destroyed) return;
    const generation = revision;
    busy = true;
    error = "";
    render();
    try {
      const result = await api(
        `/api/interactions?event_id=${encodeURIComponent(selected.event_id)}&demo=${context.demo ? "true" : "false"}&before=${append ? next || 0 : 0}`,
      );
      if (generation !== revision || destroyed) return;
      rows = append ? [...rows, ...result.interactions] : result.interactions;
      next = result.next;
      loaded = true;
      if (!append) {
        for (const group of groupInteractions(rows)) {
          const thread = threads.get(group.key);
          if (!thread?.data || thread.busy) continue;
          const saved = await api("/api/interactions/thread", {
            event_id: selected.event_id,
            sequence: group.rows[0].sequence,
            action: "cached",
            demo: context.demo,
            accepted_costs: false,
          });
          if (generation !== revision || destroyed) return;
          thread.data = saved;
          thread.nextOffset = saved.offset + saved.posts.length;
        }
      }
    } catch (failure) {
      if (generation === revision) error = failure.message;
    } finally {
      if (generation === revision && !destroyed) {
        busy = false;
        render();
        if (refreshPending && opened) {
          refreshPending = false;
          void loadHistory();
        }
      }
    }
  }
  function closeForChange() {
    refreshPending = false;
    returnToPerson = false;
    opened = false;
    if (dialog.open) dialog.close();
  }
  function onClose() {
    if (dialog.open) return;
    opened = false;
    if (returnToPerson && !destroyed && root.dataset.route === "timeline") {
      returnToPerson = false;
      if (!personDialog.open) personDialog.showModal();
      onReturn();
      personDialog
        .querySelector("[data-open-interactions]")
        ?.focus({ preventScroll: true });
    }
  }
  async function onClick(event) {
    if (event.target.closest("[data-open-interactions]")) {
      if (!selected || destroyed || dialog.open) return;
      returnToPerson = personDialog.open;
      if (personDialog.open) personDialog.close();
      opened = true;
      render();
      dialog.showModal();
      dialog.querySelector("#interaction-title").focus();
      await loadHistory();
      return;
    }
    if (event.target.closest("[data-more-interactions]")) {
      await loadHistory(true);
      return;
    }
    const button = event.target.closest("[data-thread-action]");
    if (!button || busy || !opened || !selected) return;
    const group = groupInteractions(rows).find(
      (item) => item.key === button.dataset.group,
    );
    if (!group) return;
    const thread = threads.get(group.key) || {};
    if (thread.busy) return;
    const action = button.dataset.threadAction;
    threads.set(group.key, thread);
    if (action === "open" && thread.data) {
      thread.expanded = !thread.expanded;
      render();
      return;
    }
    const generation = revision;
    thread.busy = true;
    thread.expanded = true;
    thread.error = "";
    render();
    try {
      const result = await api("/api/interactions/thread", {
        event_id: selected.event_id,
        sequence: group.rows[0].sequence,
        action,
        demo: context.demo,
        checked_at: thread.data?.checked_at || null,
        offset: action === "cached" ? thread.nextOffset : 0,
        accepted_costs:
          action !== "cached" &&
          (action !== "open" || !group.rows.some((row) => row.thread_saved)),
      });
      if (generation !== revision || destroyed) return;
      thread.data =
        action === "cached"
          ? {
              ...result,
              posts: [
                ...new Map(
                  [...thread.data.posts, ...result.posts].map((post) => [
                    post.id,
                    post,
                  ]),
                ).values(),
              ],
            }
          : result;
      thread.nextOffset = result.offset + result.posts.length;
      const groupPosts = new Set(group.rows.map((item) => item.post_id));
      for (const row of rows)
        if (groupPosts.has(row.post_id))
          row.conversation_id = result.conversation_id;
      const canonical = result.conversation_id
        ? `c${result.conversation_id}`
        : group.key;
      threads.delete(group.key);
      threads.set(canonical, thread);
    } catch (failure) {
      if (generation === revision) thread.error = failure.message;
    } finally {
      if (generation === revision && !destroyed) {
        thread.busy = false;
        render();
      }
    }
  }
  root.addEventListener("click", onClick);
  dialog.addEventListener("close", onClose);
  return {
    configure(status, demo) {
      if (context.account !== status.account?.id || context.demo !== demo) {
        revision++;
        closeForChange();
        loaded = false;
        busy = false;
        rows = [];
        next = null;
        error = "";
        threads.clear();
      }
      context = {
        account: status.account?.id,
        demo,
        types: status.interaction_types,
      };
    },
    select(event) {
      if (selected?.actor_id !== event?.actor_id) {
        revision++;
        closeForChange();
        loaded = false;
        busy = false;
        rows = [];
        next = null;
        error = "";
        threads.clear();
      }
      selected = event;
      render();
    },
    refresh() {
      if (opened) {
        if (busy) refreshPending = true;
        else return loadHistory();
      }
    },
    fillProfile(status) {
      const host = root.querySelector("#interaction-options");
      const saved = status.selection.interactions || {};
      host.innerHTML = (status.interaction_types || [])
        .map(
          (item) =>
            `<label class="switch-row"><span><strong>${esc(item.label)}</strong><small>${esc(item.cost)}</small></span><input type="checkbox" role="switch" data-interaction-kind="${item.key}" ${saved[item.key] ? "checked" : ""} ${!status.follow_actions.available && !saved[item.key] ? "disabled" : ""}></label>`,
        )
        .join("");
    },
    preferences() {
      return Object.fromEntries(
        [...root.querySelectorAll("[data-interaction-kind]")].map((input) => [
          input.dataset.interactionKind,
          input.checked,
        ]),
      );
    },
    destroy() {
      destroyed = true;
      revision++;
      closeForChange();
      root.removeEventListener("click", onClick);
      dialog.removeEventListener("close", onClose);
    },
  };
}
