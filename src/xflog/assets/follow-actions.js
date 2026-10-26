export const followButtonMarkup = `<div class="follow-detail"><button type="button" class="follow-button" data-follow-button disabled>Follow</button><p class="follow-feedback" data-follow-feedback role="status" hidden></p></div>`;

export function createFollowControls({ root, api, announce }) {
  const $ = (selector) => root.querySelector(selector);
  const hud = $("#signal-follow");
  let context = { enabled: false, available: false, demo: false };
  let selected = null;
  let relationship = null;
  let error = "";
  let generation = 0;
  let timer = null;
  let loading = false;
  let busy = false;
  let destroyed = false;
  let checkedAt = 0;
  let focusTarget = null;

  const person = () =>
    selected?.handle ? `@${selected.handle}` : selected?.name || "this account";
  function unavailable() {
    if (context.demo)
      return "Follow actions are unavailable in the offline demo.";
    if (!context.enabled)
      return "Enable Allow Follow/Unfollow in Profile first.";
    if (!context.available)
      return context.reason || "A user access token is required.";
    if (selected?.actor_id === context.account)
      return "This is your own account.";
    return "";
  }
  function textWidth(element) {
    const range = document.createRange();
    range.selectNodeContents(element);
    return range.getBoundingClientRect().width;
  }
  function fitHud() {
    hud.hidden = true;
    if (
      !selected ||
      $("#selected-signal").hidden ||
      root.dataset.route !== "timeline" ||
      $("#timeline-view").dataset.layout === "vertical"
    )
      return;
    const identity = $("#signal-identity");
    const name = $("#signal-name");
    const handle = $("#signal-handle");
    const personRect = identity
      .querySelector(".signal-person")
      .getBoundingClientRect();
    const badge = $("#signal-verification").getBoundingClientRect().width;
    const requiredName = Math.max(
      textWidth(name) + badge + 5,
      textWidth(handle),
    );
    const width = 112;
    if (personRect.width < requiredName + width + 16) return;
    const stage = hud.parentElement.getBoundingClientRect();
    hud.style.left = `${personRect.right - stage.left - width}px`;
    hud.style.top = `${personRect.top - stage.top + (personRect.height - 44) / 2}px`;
    hud.hidden = false;
    schedule();
  }
  function hasVisibleControl() {
    return !hud.hidden || $("#detail-dialog").open;
  }
  function checked(result) {
    if (
      !["following", "pending", "blocked"].every(
        (key) => typeof result?.[key] === "boolean",
      ) ||
      (result.following && (result.pending || result.blocked))
    )
      throw new Error(
        "The relationship could not be verified. Check again before acting.",
      );
    checkedAt = Date.now();
    return result;
  }
  function render() {
    const reason = unavailable();
    let label = "Follow";
    let description = reason;
    let disabled = Boolean(reason || !selected || loading || busy);
    if (!reason && selected) {
      if (loading) label = "Checking…";
      else if (busy) label = "Please wait…";
      else if (error) {
        label = "Retry";
        description = `${error} Retry the relationship check; no action will be repeated.`;
      } else if (!relationship) {
        label = "Checking…";
        disabled = true;
      } else if (relationship.blocked || relationship.pending) {
        label = relationship.blocked ? "Unavailable" : "Requested";
        description = relationship.blocked
          ? "This account is blocked. Manage the block on X first."
          : "A follow request is pending. Manage it on X.";
        disabled = true;
      } else if (relationship.following) label = "Following";
    }
    for (const button of root.querySelectorAll("[data-follow-button]")) {
      button.disabled = disabled;
      button.dataset.following = String(label === "Following");
      button.setAttribute("aria-busy", String(loading || busy));
      button.setAttribute("aria-description", description);
      button.setAttribute(
        "aria-label",
        error && !reason
          ? `Retry relationship check for ${person()}`
          : `${label === "Following" ? "Unfollow" : label} ${person()}`,
      );
      button.title =
        description ||
        (label === "Following" ? `Unfollow ${person()}` : `Follow ${person()}`);
      const normal = document.createElement("span");
      normal.className = "follow-normal";
      normal.textContent = label;
      const hover = document.createElement("span");
      hover.className = "follow-hover";
      hover.textContent = "Unfollow";
      hover.setAttribute("aria-hidden", "true");
      button.replaceChildren(normal, hover);
    }
    for (const feedback of root.querySelectorAll("[data-follow-feedback]")) {
      feedback.textContent = error || reason || description;
      feedback.hidden = !feedback.textContent;
    }
    fitHud();
    if (focusTarget && !disabled) {
      const target = focusTarget;
      focusTarget = null;
      const confirmation = $("#action-dialog");
      if (
        !destroyed &&
        target.isConnected &&
        ([document.body, $("#detail-dialog")].includes(
          document.activeElement,
        ) ||
          (!confirmation.open && confirmation.contains(document.activeElement)))
      )
        target.focus({ preventScroll: true });
    }
  }
  function schedule() {
    if (
      destroyed ||
      unavailable() ||
      !selected ||
      relationship ||
      error ||
      timer ||
      loading ||
      busy ||
      !hasVisibleControl()
    )
      return;
    const revision = generation;
    timer = setTimeout(async () => {
      timer = null;
      if (revision !== generation || unavailable() || !hasVisibleControl())
        return;
      loading = true;
      render();
      try {
        const result = await api("/api/follow-actions/relationship", {
          event_id: selected.event_id,
          demo: context.demo,
        });
        if (revision === generation) relationship = checked(result);
      } catch (failure) {
        if (revision === generation) error = failure.message;
      } finally {
        if (revision === generation) {
          loading = false;
          render();
        }
      }
    }, 250);
  }
  function reset() {
    generation++;
    clearTimeout(timer);
    timer = null;
    loading = false;
    relationship = null;
    error = "";
    focusTarget = null;
  }
  async function confirmUnfollow(event) {
    const modal = $("#action-dialog");
    const body = $("#dialog-body");
    body.innerHTML = `<h2 id="dialog-title"></h2><p>You can follow this account again at any time.</p><div class="follow-confirm"><button type="button" class="follow-button follow-danger" data-confirm-unfollow>Unfollow</button><button type="button" class="button" data-cancel-unfollow>Cancel</button></div>`;
    body.querySelector("h2").textContent =
      `Unfollow ${event.handle ? "@" + event.handle : event.name || "this account"}?`;
    modal.returnValue = "";
    body.querySelector("[data-confirm-unfollow]").onclick = () =>
      modal.close("unfollow");
    body.querySelector("[data-cancel-unfollow]").onclick = () =>
      modal.close("cancel");
    const answer = new Promise((resolve) =>
      modal.addEventListener(
        "close",
        () => resolve(modal.returnValue === "unfollow"),
        { once: true },
      ),
    );
    modal.showModal();
    return answer;
  }
  async function onClick(event) {
    const button = event.target.closest("[data-follow-button]");
    if (!button || button.disabled || !selected || unavailable() || busy)
      return;
    if (error) {
      const focused = document.activeElement === button;
      reset();
      if (focused) focusTarget = button;
      render();
      schedule();
      return;
    }
    if (!relationship || relationship.pending || relationship.blocked) return;
    const revision = generation;
    const target = selected;
    const following = !relationship.following;
    if (document.activeElement === button) focusTarget = button;
    busy = true;
    render();
    try {
      if (!following && !(await confirmUnfollow(target))) return;
      if (revision !== generation || unavailable() || destroyed) return;
      const result = await api("/api/follow-actions", {
        event_id: target.event_id,
        following,
        demo: context.demo,
      });
      if (revision === generation) {
        relationship = checked(result);
        announce(
          `${result.pending ? "Follow request sent to" : result.following ? "Following" : "Unfollowed"} ${person()}.`,
        );
      }
    } catch (failure) {
      if (revision === generation) {
        relationship = null;
        error = failure.message;
        announce(error);
      }
    } finally {
      busy = false;
      render();
      schedule();
    }
  }
  root.addEventListener("click", onClick);
  return {
    configure(status, demo) {
      const next = {
        ...status?.follow_actions,
        demo,
        account: status?.account?.id,
      };
      if (JSON.stringify(next) !== JSON.stringify(context)) {
        context = next;
        reset();
      }
      render();
      schedule();
    },
    select(event) {
      if (
        event?.actor_id !== selected?.actor_id ||
        (relationship && Date.now() - checkedAt > 30000)
      )
        reset();
      selected = event || null;
      render();
      schedule();
    },
    fitHud,
    destroy() {
      destroyed = true;
      reset();
      root.removeEventListener("click", onClick);
    },
  };
}
