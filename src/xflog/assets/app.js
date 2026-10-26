(async () => {
  const root = element.querySelector("#xf");
  const $ = (selector) => root.querySelector(selector);
  const $$ = (selector) => [...root.querySelectorAll(selector)];
  const state = {
    demo: false,
    subject: "followers",
    filter: "all",
    layout: "horizontal",
    events: [],
    next: null,
    selected: null,
    status: null,
    csrf: "",
    generation: 0,
    groups: [],
    lens: "none",
    groupSignature: "",
  };
  const pendingActions = new WeakSet();
  const esc = (value) =>
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
  const dateFormat = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const timeFormat = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  const fullFormat = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
  const gained = (event) =>
    ["follow.follow", "subscriptions.subscribe"].includes(event.kind);
  const eventLabel = (event) =>
    event.kind.startsWith("subscriptions.")
      ? gained(event)
        ? "Subscribed"
        : "Expired"
      : gained(event)
        ? "Followed you"
        : "Unfollowed";
  const displayDate = (event) =>
    new Date(event.provider_at || event.received_at);
  const initials = (event) =>
    (event.name || event.handle || "?")
      .split(/\s+/)
      .slice(0, 2)
      .map((word) => word[0])
      .join("")
      .toUpperCase();
  const { createConstellation } = await import("/static/xf/constellation.js");
  const { normalizeMotionSpeed } = await import(
    "/static/xf/constellation-layout.js"
  );
  const {
    requestBrowserNotifications,
    notifyActivity,
    clearActivityNotification,
    activityDelta,
  } = await import("/static/xf/notifications.js");
  window.addEventListener("pagehide", clearActivityNotification);
  function setMotionSpeed(value) {
    const speed = normalizeMotionSpeed(value);
    root.dataset.motionSpeed = String(speed);
    $("#motion-speed").value = speed;
    $("#motion-speed-value").textContent = `${speed}×`;
    $("#motion-speed").setAttribute(
      "aria-valuetext",
      `${speed} times ambient motion speed`,
    );
  }
  try {
    setMotionSpeed(
      localStorage.getItem("xflog.motion-speed") ??
        localStorage.getItem("xflog.twist-speed") ??
        1,
    );
  } catch {
    setMotionSpeed(1);
  }
  $("#motion-speed").addEventListener("input", (event) => {
    setMotionSpeed(event.currentTarget.value);
    try {
      localStorage.setItem("xflog.motion-speed", root.dataset.motionSpeed);
    } catch {
      // Restricted browser storage must not prevent changing the current speed.
    }
  });
  const { createAudienceControls, resolveLens } = await import(
    "/static/xf/audience-ui.js"
  );
  const scene = createConstellation({
    element: $("#history"),
    root,
    escape: esc,
    label: eventLabel,
    initials,
    date: dateFormat,
    time: timeFormat,
    gained,
    onSelect: (identity) => selectEvent(identity),
    onOpen: (identity) => selectEvent(identity, true),
    hasOlder: () => Boolean(state.next),
    onOlder: () => requestOlder(),
  });
  const { createJournal } = await import("/static/xf/journal.js");
  const journal = createJournal({
    element: $("#history"),
    escape: esc,
    date: dateFormat,
    time: timeFormat,
    displayDate,
    gained,
    label: eventLabel,
    initials,
    onOpen: (identity) => selectEvent(identity, true),
  });
  const { createActivityHud } = await import("/static/xf/activity-hud.js");
  const activityHud = createActivityHud({
    root,
    api,
    context: () => ({ demo: state.demo, subject: state.subject }),
  });
  const announce = (text) => {
    $("#announcer").textContent = text;
  };
  function notice(message) {
    $("#notice").textContent = message;
    $("#notice").hidden = !message;
    announce(message);
  }
  async function api(path, body) {
    const response = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      ...(body !== undefined
        ? {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-XFlog-CSRF": state.csrf,
            },
            body: JSON.stringify(body),
          }
        : {}),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "The request failed. Reload XFlog and retry.",
      );
    return result;
  }
  async function action(button, callback) {
    if (pendingActions.has(button)) return;
    pendingActions.add(button);
    button.disabled = true;
    try {
      await callback();
    } catch (error) {
      const message = error.message || "Something went wrong. Please retry.";
      if ($("#action-dialog").open) {
        let errorLine = $("#dialog-error");
        if (!errorLine) {
          errorLine = document.createElement("p");
          errorLine.id = "dialog-error";
          errorLine.setAttribute("role", "alert");
          $("#dialog-body").append(errorLine);
        }
        errorLine.textContent = message;
      } else notice(message);
    } finally {
      pendingActions.delete(button);
      button.disabled = button.id === "tracking-button" && state.demo;
    }
  }
  function view(name) {
    for (const page of ["timeline", "profile", "about"])
      $(`#${page}-view`).hidden = page !== name;
    $$("[data-nav]").forEach((button) => {
      button.classList.toggle("active", button.dataset.nav === name);
      if (button.dataset.nav === name)
        button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    $("#page-crumb").textContent = {
      timeline: "Timeline",
      profile: "Profile & settings",
      about: "About XFlog",
    }[name];
    if (name === "profile") fillProfile();
    $("#mobile-profile").textContent =
      name === "profile" ? "Timeline" : "Profile";
    history.replaceState(null, "", `#${name}`);
    root.dataset.route = name;
    if (name === "timeline") activityHud.refresh();
    $(".back-button").hidden = name === "timeline";
    if ($("#explore-dialog").open) $("#explore-dialog").close();
    if (document.activeElement !== document.body)
      $("#main").focus({ preventScroll: true });
  }
  function renderStatus(status) {
    const previous = state.status;
    state.status = status;
    state.csrf = status.csrf;
    const active = ["tracking", "connecting", "reconnecting"].includes(
      status.state,
    );
    $("#connection-label").textContent = state.demo
      ? "Demo workspace"
      : {
          stopped: status.connected ? "Ready · paused" : "Setup missing",
          tracking: "Tracking",
          connecting: "Connecting…",
          reconnecting: "Reconnecting…",
          reconnect: "Credentials needed",
          error: "Storage error",
        }[status.state] || status.state;
    $("#connection-label").classList.toggle(
      "is-tracking",
      !state.demo && status.state === "tracking",
    );
    $("#tracking-button").textContent = active
      ? "Pause tracking"
      : "Start tracking →";
    $("#tracking-button").disabled =
      state.demo || pendingActions.has($("#tracking-button"));
    const account = status.account;
    $("#scope-name").textContent = state.demo
      ? "Mira Studio"
      : account?.name ||
        account?.username ||
        (account?.id ? `Account ${account.id}` : "Your workspace");
    $("#scope-handle").textContent = state.demo
      ? "@mirastudio · demo"
      : account?.username
        ? `@${account.username}`
        : "Private history";
    $(".workspace-avatar").textContent = (
      state.demo ? "M" : (account?.name || account?.username || "X")[0]
    ).toUpperCase();
    if ($("#notice").textContent === "Failed to fetch") notice("");
    if (status.cleanup_warning) notice(status.cleanup_warning);
    else if (["reconnecting", "reconnect", "error"].includes(status.state))
      notice(status.message);
    else if (status.preference_warning) notice(status.preference_warning);
    else if (
      previous?.preference_warning &&
      $("#notice").textContent === previous.preference_warning
    )
      notice("");
    const newActivity = state.demo ? 0 : activityDelta(previous, status);
    if (newActivity) {
      notice(
        "New activity arrived. Refresh local history to see the latest events.",
      );
      notifyActivity(newActivity);
    }
    if (state.demo || !status.selection.notifications)
      clearActivityNotification();
    if (
      previous &&
      !previous.connected &&
      !status.connected &&
      status.message !== previous.message
    )
      notice(status.message);
    if (!$("#profile-view").hidden) fillProfileStatus(status);
    renderAudienceGroups(status.audience_groups || []);
  }
  const groupControls = createAudienceControls({
    root,
    onToggle: (group, toggle) =>
      action(toggle, async () => {
        try {
          const result = await api("/api/audience-groups", {
            enabled: { [group.key]: toggle.checked },
          });
          renderAudienceGroups(result.audience_groups);
          await load();
          announce("Audience groups saved. No extra X requests are made.");
        } catch (error) {
          toggle.checked = group.enabled;
          throw error;
        }
      }),
    onLens: (lens) => {
      state.lens = lens;
      groupControls.render(state.groups, lens);
      scene.configure(state.groups, lens);
      if (state.layout === "vertical") renderEvents();
    },
  });
  function renderAudienceGroups(groups) {
    const signature = JSON.stringify(groups);
    if (signature === state.groupSignature) return;
    state.groupSignature = signature;
    state.lens = resolveLens(groups, state.lens);
    state.groups = groups;
    groupControls.render(groups, state.lens);
    scene.configure(groups, state.lens);
    if (state.layout === "vertical") renderEvents();
  }
  function renderEvents() {
    const list = $("#history");
    $(".scene-context").hidden = !state.events.length;
    $("#timeline-view").dataset.layout = state.layout;
    list.className = `history ${state.layout}`;
    list.setAttribute(
      "aria-label",
      `${state.subject === "followers" ? "Follower" : "Paid subscription"} event timeline`,
    );
    if (!state.events.length) {
      const isSubs = state.subject === "subscriptions";
      let title = "Your next chapter starts here.";
      let copy =
        "Configure the instance, then start tracking to record follower changes.";
      scene.clear();
      $("#scene-people-count").textContent = "";
      if (state.filter !== "all") {
        title = "No matching events yet.";
        copy = "Try All events, or return after more activity is received.";
      } else if (
        isSubs &&
        !state.status?.selection.subscriptions &&
        !state.demo
      ) {
        title = "Subscriber history is optional.";
        copy =
          "Enable paid subscription events in Profile, then start tracking.";
      } else if (state.status?.connected) {
        title = "Ready when you are.";
        copy =
          "History begins when tracking starts. Activity before that is not reconstructed.";
      }
      list.innerHTML = `<div class="empty-state"><img src="/static/xf/mark.svg" width="48" height="48" alt=""><h2>${title}</h2><p>${copy}</p>${!state.demo ? '<button type="button" class="button" data-empty-demo>Explore the demo →</button>' : ""}</div>`;
      list
        .querySelector("[data-empty-demo]")
        ?.addEventListener("click", () => setDemo(true));
    } else if (state.layout === "horizontal") {
      scene.render(state.events, state.selected);
    } else {
      scene.clear();
      journal.render(state.events, {
        selected: state.selected,
        modules: state.groups,
        lens: state.lens,
      });
      $("#scene-people-count").textContent =
        `${state.events.length} ${state.events.length === 1 ? "event" : "events"} in loaded history`;
    }
    if (state.layout === "vertical") {
      $("#memory-scrubber").max = Math.max(0, state.events.length - 1);
      $("#memory-scrubber").disabled = !state.events.length;
      $("#memory-scrubber").value = Math.max(
        0,
        state.events.findIndex((event) => event.event_id === state.selected),
      );
    }
    if (!state.events.length) {
      $("#journey-position").textContent = "No memories in this view";
      $("#memory-scrubber").value = 0;
    }
    $("#history-end").textContent = state.demo
      ? "Synthetic examples · Stored separately from your history"
      : state.subject === "subscriptions"
        ? "Expired means access ended, not the date a subscriber canceled."
        : "Only activity received while tracking appears here.";
  }
  function selectEvent(identity, openMobile = false) {
    const event = state.events.find((event) => event.event_id === identity);
    if (!event) return;
    state.selected = identity;
    $$("[data-event]").forEach((button) =>
      button.setAttribute("aria-pressed", button.dataset.event === identity),
    );
    const safeLink =
      typeof event.profile_url === "string" &&
      /^https:\/\/x\.com\/[A-Za-z0-9_]{1,15}$/.test(event.profile_url);
    const detail = `<h2>Event details</h2><div class="detail-person"><span class="avatar" aria-hidden="true">${esc(initials(event))}</span><h3>${esc(event.name || event.handle || "X account")}</h3><p>${esc(event.handle ? "@" + event.handle : "ID " + event.actor_id)}</p></div><div class="detail-kind ${gained(event) ? "" : "lost"}"><span aria-hidden="true">${gained(event) ? "↗" : "↘"}</span>${eventLabel(event)}</div><dl class="detail-data"><dt>Provider event time</dt><dd>${event.provider_at ? esc(fullFormat.format(new Date(event.provider_at))) : "Not supplied by X"}</dd><dt>Received on this device</dt><dd>${esc(fullFormat.format(new Date(event.received_at)))}</dd><dt>Account ID</dt><dd>${esc(event.actor_id)}</dd></dl>${safeLink ? `<a class="detail-profile" href="${esc(event.profile_url)}" target="_blank" rel="noopener noreferrer">View profile on X <span aria-hidden="true">↗</span></a>` : ""}<p class="detail-small">${event.kind === "subscriptions.unsubscribe" ? "This event records subscription expiry, not cancellation." : "Provider time is shown only when X supplies it. Received time is when XFlog captured the event."}${state.demo ? " Synthetic demo event." : ""}</p>`;
    $("#detail-panel").innerHTML = detail;
    $("#mobile-detail").innerHTML = detail;
    if (state.layout === "horizontal") scene.select(identity);
    const index = state.events.findIndex((item) => item.event_id === identity);
    $("#journey-position").textContent =
      `Memory ${index + 1} of ${state.events.length} loaded`;
    if (state.layout === "vertical") $("#memory-scrubber").value = index;
    $("#memory-scrubber").setAttribute(
      "aria-valuetext",
      `${event.name || event.handle || "X account"}, ${eventLabel(event)}, ${dateFormat.format(displayDate(event))}`,
    );
    if (openMobile && !$("#detail-dialog").open)
      $("#detail-dialog").showModal();
  }
  function requestOlder() {
    if (
      !state.next ||
      root.dataset.route !== "timeline" ||
      $("#history").getAttribute("aria-busy") === "true"
    )
      return;
    load(true);
  }
  async function load(append = false) {
    const generation = ++state.generation;
    const params = new URLSearchParams({
      kind: state.filter,
      subject: state.subject,
      before: String(append ? state.next || 0 : 0),
    });
    const demo = state.demo;
    if (!append && !state.events.length)
      $("#history").innerHTML =
        '<div class="loading-state"><span class="loading-dot" aria-hidden="true"></span>Loading local history…</div>';
    $("#history").setAttribute("aria-busy", "true");
    try {
      const result = await api(`/api/${demo ? "demo" : "events"}?${params}`);
      if (generation !== state.generation) return;
      state.events = append
        ? [...state.events, ...result.events]
        : result.events;
      state.next = result.next;
      if (!state.events.some((event) => event.event_id === state.selected))
        state.selected =
          state.events[Math.min(2, state.events.length - 1)]?.event_id || null;
      renderEvents();
      if (state.selected) selectEvent(state.selected);
      else
        $("#detail-panel").innerHTML =
          '<div class="detail-placeholder"><h2>A closer look</h2><p>Select an event to see the account and its recorded timestamps.</p><div class="detail-illustration" aria-hidden="true"><span>↗</span><span class="path-dot"></span><span>↘</span></div></div>';
      announce(
        `${result.events.length} ${state.subject} events ${append ? "added" : "loaded"}.`,
      );
    } catch (error) {
      if (generation !== state.generation) return;
      notice(error.message);
      if (!state.events.length) {
        $("#history").innerHTML =
          '<div class="empty-state"><h2>History couldn’t be loaded.</h2><p>Check your local database and connection, then refresh to retry.</p><button class="button" type="button" data-retry>Retry</button></div>';
        $("#history [data-retry]").addEventListener("click", () => load());
      }
    } finally {
      if (generation === state.generation)
        $("#history").setAttribute("aria-busy", "false");
    }
  }
  async function setDemo(enabled) {
    const address = new URL(location.href);
    if (enabled) address.searchParams.set("demo", "1");
    else address.searchParams.delete("demo");
    history.replaceState(null, "", address);
    state.demo = enabled;
    state.events = [];
    state.selected = null;
    state.next = null;
    $("#demo-toggle").textContent = enabled
      ? "Leave demo ↗"
      : "Explore demo ↗";
    notice("");
    if (state.status) renderStatus(state.status);
    view("timeline");
    await load();
  }
  function dialog(html) {
    if ($("#explore-dialog").open) $("#explore-dialog").close();
    $("#dialog-body").innerHTML = html;
    $("#action-dialog").showModal();
  }
  function fillProfileStatus(status) {
    $("#profile-account").textContent = status.account
      ? `${status.account.name || status.account.username || "X account"} · ${status.account.username ? "@" + status.account.username : status.account.id}`
      : "No account configured.";
    const missing = status.missing_settings || [];
    $("#profile-state").textContent =
      !missing.length && status.connected ? "Configured" : "Setup missing";
    $("#profile-message").textContent = missing.length
      ? "Add the missing settings to your server configuration, then restart XFlog."
      : status.preference_warning || status.message;
    const list = $("#profile-missing-settings");
    list.replaceChildren();
    list.hidden = !missing.length;
    for (const key of missing) {
      const item = document.createElement("li");
      const name = document.createElement("code");
      name.textContent = key;
      item.append(name, document.createTextNode(" — not set"));
      list.append(item);
    }
    const environment = $("#profile-environment");
    environment.hidden = !missing.length;
    environment.replaceChildren();
    if (status.environment_file) {
      const path = document.createElement("code");
      path.textContent = status.environment_file;
      environment.append(document.createTextNode("Configuration file: "), path);
    } else {
      environment.textContent =
        "Configuration source: server environment (.env path not provided).";
    }
  }
  function fillProfile() {
    const status = state.status;
    if (!status) return;
    fillProfileStatus(status);
    for (const key of ["followers", "subscriptions", "notifications"])
      $(`#preferences-form [name="${key}"]`).checked = Boolean(
        status.selection[key],
      );
  }
  function startDialog() {
    if (state.demo) return;
    if (
      ["tracking", "connecting", "reconnecting"].includes(state.status?.state)
    ) {
      action($("#tracking-button"), async () => {
        await api("/api/stop", {});
        renderStatus(await api("/api/status"));
        notice("Tracking paused. Local history is kept.");
      });
      return;
    }
    if (!state.status?.connected || state.status?.missing_settings?.length) {
      notice(
        state.status?.setup_message ||
          state.status?.message ||
          "Configure all required X credentials and restart.",
      );
      return;
    }
    dialog(
      '<h2 id="dialog-title">Start tracking</h2><p>X charges for API usage. Check the current Activity prices in your X Developer Console and add enough credits before starting.</p><p>Set a spending limit and check whether automatic credit top-ups are enabled. XFlog does not set or enforce your X spending limit.</p><p>Tracking resumes after a restart until you pause it. Activity while offline may be missed.</p><label><input type="checkbox" id="accept-costs"><span>I checked X pricing, credits and my spending limit.</span></label><button type="button" class="button primary" id="confirm-start" disabled>Start tracking →</button>',
    );
    $("#accept-costs").addEventListener("change", () => {
      $("#confirm-start").disabled = !$("#accept-costs").checked;
    });
    $("#confirm-start").addEventListener("click", (event) =>
      action(event.currentTarget, async () => {
        await api("/api/start", { accepted_costs: $("#accept-costs").checked });
        $("#action-dialog").close();
        renderStatus(await api("/api/status"));
      }),
    );
  }
  $$("[data-nav]").forEach((button) =>
    button.addEventListener("click", () => view(button.dataset.nav)),
  );
  $("#mobile-profile").addEventListener("click", () => {
    const profile = $("#profile-view").hidden;
    view(profile ? "profile" : "timeline");
    $("#mobile-profile").textContent = profile ? "Timeline" : "Profile";
  });
  $$("[data-filter]").forEach((button) =>
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      $$("[data-filter]").forEach((item) =>
        item.setAttribute("aria-pressed", item === button),
      );
      state.events = [];
      state.selected = null;
      load();
    }),
  );
  $$("[data-subject]").forEach((button) =>
    button.addEventListener("click", () => {
      state.subject = button.dataset.subject;
      $$("[data-subject]").forEach((item) =>
        item.setAttribute("aria-pressed", item === button),
      );
      state.events = [];
      state.selected = null;
      activityHud.refresh();
      load();
    }),
  );
  $$("[data-layout]").forEach((button) =>
    button.addEventListener("click", () => {
      state.layout = button.dataset.layout;
      $$("[data-layout]").forEach((item) =>
        item.setAttribute("aria-pressed", item === button),
      );
      renderEvents();
      announce(`${state.layout} timeline selected.`);
    }),
  );
  $("#demo-toggle").addEventListener("click", () => setDemo(!state.demo));
  $("#exit-demo").addEventListener("click", () => setDemo(false));
  $("#empty-demo").addEventListener("click", () => setDemo(true));
  $("#refresh-button").addEventListener("click", (event) =>
    action(event.currentTarget, async () => {
      renderStatus(await api("/api/status"));
      await load();
    }),
  );
  $("#tracking-button").addEventListener("click", startDialog);
  $("#preferences-form").addEventListener("submit", (event) => {
    event.preventDefault();
    action($('#preferences-form button[type="submit"]'), async () => {
      const form = event.currentTarget;
      const selection = {
        followers: form.elements.followers.checked,
        subscriptions: form.elements.subscriptions.checked,
        notifications: form.elements.notifications.checked,
      };
      const permission = selection.notifications
        ? requestBrowserNotifications()
        : Promise.resolve(null);
      const result = await api("/api/preferences", selection);
      renderStatus(await api("/api/status"));
      if (!result.saved) fillProfile();
      notice(result.message);
      permission.then((value) => {
        if (
          result.saved &&
          value &&
          value !== "granted" &&
          state.status?.selection.notifications
        )
          notice(
            result.message +
              " Browser alerts are blocked or unavailable; in-app notifications still work.",
          );
      });
    });
  });
  $("#view-gaps").addEventListener("click", () => {
    const gaps = state.demo
      ? [
          {
            started_at: "2026-10-24T14:10:00Z",
            ended_at: "2026-10-24T14:24:00Z",
            reason: "Synthetic offline example",
          },
        ]
      : state.status?.gaps || [];
    dialog(
      `<h2 id="dialog-title">Connection history</h2><p>Events during a gap may be missing. XFlog does not promise replay or recovery.</p>${gaps.length ? gaps.map((gap) => `<div class="gap-row">${esc(fullFormat.format(new Date(gap.started_at)))}<span>To ${gap.ended_at ? esc(fullFormat.format(new Date(gap.ended_at))) : "now · gap still open"}</span><span>${esc(gap.reason)}</span></div>`).join("") : "<p>No connection gaps have been recorded.</p>"}`,
    );
  });
  $("#explore-button").addEventListener("click", () => {
    view("timeline");
    $("#explore-dialog").showModal();
    $("#explore-dialog .panel-body").scrollTop = 0;
  });
  $("#memory-previous").addEventListener("click", () => scene.travel(-1));
  $("#memory-next").addEventListener("click", () => scene.travel(1));
  $("#memory-scrubber").addEventListener("input", (event) => {
    const index = Number(event.target.value);
    if (state.layout === "horizontal") scene.scrub(index / 1000);
    else if (state.events[index]) {
      selectEvent(state.events[index].event_id);
      journal.reveal(state.events[index].event_id);
    }
  });
  $("#memory-scrubber").addEventListener("change", (event) => {
    const end = state.layout === "horizontal" ? 1000 : state.events.length - 1;
    if (Number(event.target.value) >= end) requestOlder();
  });
  $("#history").addEventListener("scroll", () => {
    const history = $("#history");
    if (
      state.layout === "vertical" &&
      history.scrollTop + history.clientHeight >= history.scrollHeight - 80
    )
      requestOlder();
  });

  $("#motion-toggle").addEventListener("click", (event) => {
    const enabled = root.dataset.motion !== "on";
    root.dataset.motion = enabled ? "on" : "off";
    event.currentTarget.setAttribute("aria-pressed", enabled);
    event.currentTarget.textContent = enabled
      ? "Ambient motion on"
      : "Ambient motion paused";
  });
  async function poll() {
    if (!root.isConnected) {
      scene.destroy();
      groupControls.destroy();
      activityHud.destroy();
      return;
    }
    if (!document.hidden || state.status?.selection.notifications) {
      try {
        renderStatus(await api("/api/status"));
        if (root.dataset.route === "timeline") activityHud.refresh();
      } catch (error) {
        notice(error.message);
      }
    }
    setTimeout(poll, 10000);
  }
  try {
    renderStatus(await api("/api/status"));
    if (new URLSearchParams(location.search).get("demo") === "1")
      await setDemo(true);
    else {
      activityHud.refresh();
      await load();
    }
    const hash = location.hash.slice(1);
    if (["profile", "about"].includes(hash)) view(hash);
    setTimeout(poll, 10000);
  } catch (error) {
    notice(error.message);
  }
})();
