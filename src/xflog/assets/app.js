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
    loading: false,
    groups: [],
    lens: "none",
    groupRange: "24h",
    groupSignature: "",
  };
  const pendingActions = new WeakSet();
  const {
    esc,
    dateFormat,
    timeFormat,
    fullFormat,
    eventLabel,
    displayDate,
    initials,
  } = await import("/static/xf/format.js");
  const { renderPersonDetail } = await import("/static/xf/person-detail.js");
  const { emptyHistory } = await import("/static/xf/empty-history.js");
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
    onSelect: (identity) => selectEvent(identity),
    onPreview: (identity) => selectEvent(identity, false, followControls.update),
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
    label: eventLabel,
    initials,
    onOpen: (identity) => selectEvent(identity, true),
    onNearEnd: requestOlder,
  });
  const { createActivityHud } = await import("/static/xf/activity-hud.js");
  const activityHud = createActivityHud({
    root,
    api,
    context: () => ({ demo: state.demo, subject: state.subject, period: state.groupRange }),
    onRange: setTimeRange,
    onWindow: window => { state.rangeWindow = window; },
  });
  const { createSelectedSignal } = await import(
    "/static/xf/selected-signal.js"
  );
  const { createFollowControls } = await import("/static/xf/follow-actions.js");
  const { createInteractionControls } = await import(
    "/static/xf/interactions.js"
  );
  const interactionControls = createInteractionControls({
    root, api, esc, onReturn: () => followControls.resume(),
  });
  const { createProfileControls } = await import("/static/xf/profile.js");
  const profileControls = createProfileControls({
    root,
    interactions: interactionControls,
  });
  const fillProfile = () => profileControls.render(state.status);
  const followControls = createFollowControls({
    root,
    api,
    announce: (message) => announce(message),
  });
  const selectedSignal = createSelectedSignal({
    root,
    label: eventLabel,
    date: dateFormat,
    time: timeFormat,
    fullDate: fullFormat,
    onOpen: (identity) => selectEvent(identity, true),
    onFit: () => followControls.fitHud(),
  });
  const announce = (text) => {
    $("#announcer").textContent = text;
  };
  const { createNotice, statusNotice } = await import("/static/xf/notice.js");
  const notices = createNotice($("#notice"));
  const notice = (message, tone = "info") => notices.show(message, tone);
  const { historyPages, groupSince, mergeHistory, createLiveHistory, updatedSelection } = await import("/static/xf/live-history.js");
  const liveHistory = createLiveHistory({
    api,
    read: () => ({ ...state }),
    apply: (events, next) => {
      state.selected = updatedSelection(state.events, state.selected, events);
      state.events = events;
      state.next = next;
      if (root.dataset.route === "timeline") {
        renderEvents(scene.update);
        if (state.selected) selectEvent(state.selected, false, followControls.update);
      }
    },
    refreshInteractions: () => interactionControls.refresh(),
  });
  async function api(path, body, signal) {
    const response = await fetch(path, {
      credentials: "same-origin",
      signal,
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
      } else notice(message, "error");
    } finally {
      pendingActions.delete(button);
      button.disabled = button.id === "tracking-button" && state.demo;
    }
  }
  function view(name) {
    if (name !== "timeline") journal.clear({remember: true});
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
    history.replaceState(null, "", `#${name}`);
    root.dataset.route = name;
    followControls.select(
      name === "timeline"
        ? state.events.find((event) => event.event_id === state.selected)
        : null,
    );
    if (name === "timeline") {
      renderEvents(scene.update);
      if (state.selected) selectEvent(state.selected);
      activityHud.refresh();
    }
    $(".back-button").hidden = name === "timeline";
    if ($("#explore-dialog").open) $("#explore-dialog").close();
    if (document.activeElement !== document.body)
      $("#main").focus({ preventScroll: true });
  }
  function renderStatus(status) {
    const previous = state.status;
    state.status = status;
    state.csrf = status.csrf;
    followControls.configure(status, state.demo);
    interactionControls.configure(status, state.demo);
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
    if (notices.message === "Failed to fetch") notice("");
    notices.update(statusNotice(status));
    const newActivity = state.demo ? 0 : activityDelta(previous, status);
    if (newActivity) {
      notice(
        "New activity received.",
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
      notice(status.message, "warning");
    if (!$("#profile-view").hidden) profileControls.renderStatus(status);
    renderAudienceGroups(status.audience_groups || []);
    if (
      previous && !state.events.length &&
      (previous.state !== status.state || previous.connected !== status.connected ||
        previous.selection.subscriptions !== status.selection.subscriptions)
    ) renderEvents();
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
      groupControls.render(state.groups, lens, state.groupRange);
      scene.configure(state.groups, lens);
      if (state.layout === "vertical") renderEvents();
      void load();
    },
    onRange: setTimeRange,
  });
  async function setTimeRange(range) {
    state.groupRange = range;
    groupControls.render(state.groups, state.lens, range);
    await activityHud.refresh();
    if (state.groupRange === range) await load();
  }
  function renderAudienceGroups(groups) {
    const signature = JSON.stringify(groups);
    if (signature === state.groupSignature) return;
    state.groupSignature = signature;
    state.lens = resolveLens(groups, state.lens);
    state.groups = groups;
    groupControls.render(groups, state.lens, state.groupRange);
    scene.configure(groups, state.lens);
    selectedSignal.render(
      state.events.find((event) => event.event_id === state.selected),
      groups,
    );
    if (state.layout === "vertical") renderEvents();
  }
  function renderEvents(renderScene = scene.render) {
    if ($("#timeline-view").hidden) return;
    const list = $("#history");
    $(".scene-context").hidden = !state.events.length && state.lens === "none";
    $("#timeline-view").dataset.layout = state.layout;
    if (state.layout === "horizontal" || !state.events.length)
      journal.clear({remember: state.layout === "horizontal" && Boolean(state.events.length)});
    list.className = `history ${state.layout}`;
    list.setAttribute(
      "aria-label",
      `${state.subject === "followers" ? "Activity" : "Paid subscription"} timeline`,
    );
    if (!state.events.length) {
      selectedSignal.render(null);
      followControls.select(null);
      scene.clear();
      $("#scene-people-count").textContent = state.lens === "none" ? "" : "0 people in saved history";
      list.innerHTML = state.lens === "none" ? emptyHistory(state) : '<div class="empty-state"><h2>No activity in this range.</h2></div>';
      list
        .querySelector("[data-empty-action]")
        ?.addEventListener("click", (event) => {
          const action = event.currentTarget.dataset.emptyAction;
          if (action === "tracking") startDialog();
          else if (action === "profile") view("profile");
          else setDemo(true);
        });
    } else if (state.layout === "horizontal") {
      renderScene(state.events, state.selected);
    } else {
      scene.clear();
      journal.render(state.events, {
        selected: state.selected,
        modules: state.groups,
        lens: state.lens,
      });
      $("#scene-people-count").textContent =
        `${state.events.length} ${state.events.length === 1 ? "event" : "events"} in ${state.lens === "none" ? "loaded" : "saved"} history`;
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
  function selectEvent(identity, openMobile = false, updateFollow = followControls.select) {
    const event = state.events.find((event) => event.event_id === identity);
    if (!event) return;
    state.selected = identity;
    selectedSignal.render(event, state.groups);
    if (state.layout === "horizontal") scene.select(identity);
    else journal.select(identity);
    renderPersonDetail(root, event);
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
    updateFollow(event);
    interactionControls.select(event);
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
  let historyLoad = null;
  async function load(append = false) {
    historyLoad?.abort();
    const controller = new AbortController();
    historyLoad = controller;
    const generation = ++state.generation;
    state.loading = true;
    const demo = state.demo;
    const snapshot = {...state, since: groupSince(state)};
    if (!append && !state.events.length) {
      selectedSignal.render(null);
      followControls.select(null);
      scene.clear();
      journal.clear();
      $("#history").innerHTML =
        '<div class="loading-state"><span class="loading-dot" aria-hidden="true"></span>Loading local history…</div>';
    }
    $("#history").setAttribute("aria-busy", "true");
    try {
      const rows = [];
      let result;
      const readPage = path => api(path, undefined, controller.signal);
      for await (result of historyPages(readPage, snapshot, append ? state.next : "0")) {
        if (generation !== state.generation) return;
        rows.push(...result.events);
        if (state.lens !== "none") $("#scene-people-count").textContent = `Loading saved history · ${rows.length} records`;
      }
      if (generation !== state.generation) return;
      state.events = mergeHistory([...rows, ...(append ? state.events : [])])
        .filter(event => !snapshot.since || Date.parse(event.received_at) >= Date.parse(snapshot.since));
      state.next = result.next;
      if (!state.events.some((event) => event.event_id === state.selected))
        state.selected =
          state.events[Math.min(2, state.events.length - 1)]?.event_id || null;
      renderEvents();
      if (state.selected) selectEvent(state.selected);
      if (!append) void interactionControls.refresh();
      announce(
        `${rows.length} ${state.subject} events ${append ? "added" : "loaded"}.`,
      );
    } catch (error) {
      if (generation !== state.generation) return;
      notice(error.message, "error");
      if (!state.events.length) {
        scene.clear();
        journal.clear();
        $("#history").innerHTML =
          '<div class="empty-state"><h2>History couldn’t be loaded.</h2><p>Check your local database and connection, then refresh to retry.</p><button class="button" type="button" data-retry>Retry</button></div>';
        $("#history [data-retry]").addEventListener("click", () => load());
      }
    } finally {
      if (generation === state.generation) {
        state.loading = false;
        $("#history").setAttribute("aria-busy", "false");
      }
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
    await activityHud.refresh();
    await load();
  }
  function dialog(html) {
    if ($("#explore-dialog").open) $("#explore-dialog").close();
    $("#dialog-body").innerHTML = html;
    $("#action-dialog").showModal();
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
        "warning",
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
    button.addEventListener("click", async () => {
      state.subject = button.dataset.subject;
      $$("[data-subject]").forEach((item) =>
        item.setAttribute("aria-pressed", item === button),
      );
      state.events = [];
      state.selected = null;
      await activityHud.refresh();
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
  $("#empty-demo").addEventListener("click", () => setDemo(true));
  $("#tracking-button").addEventListener("click", startDialog);
  $("#preferences-form").addEventListener("submit", (event) => {
    event.preventDefault();
    action($('#preferences-form button[type="submit"]'), async () => {
      const form = event.currentTarget;
      const selection = {
        followers: form.elements.followers.checked,
        subscriptions: form.elements.subscriptions.checked,
        notifications: form.elements.notifications.checked,
        profile_names: form.elements.profile_names.checked,
        follow_actions: form.elements.follow_actions.checked,
        interactions: interactionControls.preferences(),
      };
      const permission = selection.notifications
        ? requestBrowserNotifications()
        : Promise.resolve(null);
      const result = await api("/api/preferences", selection);
      renderStatus(await api("/api/status"));
      await liveHistory.refresh();
      if (!result.saved) fillProfile();
      notice(
        result.message,
        !result.saved || state.status?.preference_warning ? "warning" : "success",
      );
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
            "warning",
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
      historyLoad?.abort();
      scene.destroy();
      journal.destroy();
      groupControls.destroy();
      activityHud.destroy();
      selectedSignal.destroy();
      followControls.destroy();
      interactionControls.destroy();
      notices.destroy();
      return;
    }
    if (!document.hidden || state.status?.selection.notifications) {
      try {
        renderStatus(await api("/api/status"));
        if (root.dataset.route === "timeline") await activityHud.refresh();
        await liveHistory.refresh();
      } catch (error) {
        notices.update({ message: error.message, tone: "error" });
      }
    }
    setTimeout(poll, 10000);
  }
  try {
    renderStatus(await api("/api/status"));
    if (new URLSearchParams(location.search).get("demo") === "1")
      await setDemo(true);
    else {
      await activityHud.refresh();
      await load();
    }
    const hash = location.hash.slice(1);
    if (["profile", "about"].includes(hash)) view(hash);
    setTimeout(poll, 10000);
  } catch (error) {
    notice(error.message, "error");
  }
})();
