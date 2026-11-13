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
    aggregate: null,
    selected: null,
    status: null,
    csrf: "",
    groups: [],
    lens: "none",
    activityKind: "",
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
    onGroup: (kind) => {
      setActivityKind(kind);
      void liveHistory.load();
      scene.setZoom(1);
      $("#activity-group-back").focus({preventScroll:true});
    },
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
    onNearEnd: () => requestOlder(false),
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
  const { createLiveHistory, historyScope } = await import("/static/xf/live-history.js");
  const { historyCount } = await import("/static/xf/audience-groups.js");
  const historyMore = $("#history-more");
  const historyStatus = $("#history-page-status");
  let historyPhase;
  let historyError;
  const liveHistory = createLiveHistory({
    api: (path, signal) => api(path, undefined, signal),
    read: () => state,
    connected: () => root.isConnected,
    clear: clearHistory,
    apply: ({events, next, aggregate}, reason) => {
      if (historyError && notices.message === historyError) notice("");
      historyError = null;
      const olderControl = document.activeElement === $("#memory-next");
      if (!events.some(event => event.event_id === state.selected))
        state.selected = events[Math.min(reason === "initial" && !state.activityKind ? 2 : 0, events.length - 1)]?.event_id || null;
      state.events = events;
      state.next = next;
      state.aggregate = aggregate;
      if (root.dataset.route === "timeline") {
        renderEvents(reason === "initial" ? scene.render : scene.update, reason === "older");
        if (state.selected)
          selectEvent(state.selected, false, reason === "initial" ? followControls.select : followControls.update);
        if (olderControl && $("#memory-next").disabled) $("#history").focus({preventScroll:true});
      }
    },
    change: ({phase, catchingUp, olderError}) => {
      historyPhase = phase;
      $("#history").setAttribute("aria-busy", String(phase === "initial" || phase === "older"));
      const hideOlder = !state.next || phase === "initial";
      if (hideOlder && document.activeElement === historyMore)
        $("#history").focus({preventScroll:true});
      historyMore.hidden = hideOlder;
      historyMore.setAttribute("aria-disabled", String(phase === "older"));
      const buttonLabel = olderError ? "Retry older activity" : "Load older activity";
      if (historyMore.textContent !== buttonLabel) historyMore.textContent = buttonLabel;
      const message = phase === "older" ? "Loading older activity…"
        : olderError ? "Older activity couldn’t be loaded."
        : catchingUp ? "Catching up on new activity…"
        : !phase && !state.next && state.events.length ? "All matching activity loaded" : "";
      if (historyStatus.textContent !== message) historyStatus.textContent = message;
    },
    failure: (error, phase) => {
      historyError = error.message;
      notice(error.message, "error");
      if (phase === "initial") {
        $("#history").innerHTML =
          '<div class="empty-state"><h2>History couldn’t be loaded.</h2><p>Check your local database and connection, then refresh to retry.</p><button class="button" type="button" data-retry>Retry</button></div>';
        $("#history [data-retry]").addEventListener("click", () => {
          $("#history").focus({preventScroll:true});
          void liveHistory.load();
        });
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
    if (name !== "timeline") {
      liveHistory.cancel();
      journal.clear({remember: true});
    }
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
      if (liveHistory.needsLoad()) void liveHistory.load(activityHud.refresh);
      else {
        renderEvents(scene.update);
        if (state.selected) selectEvent(state.selected);
        void activityHud.refresh();
      }
    }
    $(".back-button").hidden = name === "timeline";
    if ($("#explore-dialog").open) $("#explore-dialog").close();
    if (document.activeElement !== document.body)
      $("#main").focus({ preventScroll: true });
  }
  function renderStatus(status) {
    const previous = state.status;
    const scope = historyScope(state);
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
    if (previous && account?.id !== previous.account?.id) setActivityKind("");
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
    if (previous && historyScope(state) !== scope) {
      if (root.dataset.route === "timeline") void liveHistory.load();
      else {
        liveHistory.cancel();
        clearHistory();
      }
      return;
    }
    if (
      previous && !state.events.length && !historyPhase &&
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
          await liveHistory.load();
          announce("Audience groups saved. No extra X requests are made.");
        } catch (error) {
          toggle.checked = group.enabled;
          throw error;
        }
      }),
    onLens: (lens) => {
      setActivityKind("");
      state.lens = lens;
      groupControls.render(state.groups, lens, state.groupRange);
      void liveHistory.load();
    },
    onRange: setTimeRange,
  });
  async function setTimeRange(range) {
    state.groupRange = range;
    groupControls.render(state.groups, state.lens, range);
    if (state.activityKind) setActivityKind(state.activityKind);
    await liveHistory.load(activityHud.refresh);
  }
  function setActivityKind(kind) {
    state.activityKind = kind;
    const label = state.groups.find(group => group.key === "activity")
      ?.buckets.find(bucket => bucket.key === kind)?.label;
    $("#scene-lens-label").textContent = label ||
      state.groups.find(group => group.key === state.lens)?.label || "Ungrouped";
    $("#activity-group-back").hidden = !kind;
  }
  $("#activity-group-back").addEventListener("click", () => {
    setActivityKind("");
    void liveHistory.load();
    scene.setZoom(0);
    $("#history").focus({preventScroll:true});
  });
  function renderAudienceGroups(groups) {
    const signature = JSON.stringify(groups);
    if (signature === state.groupSignature) return;
    state.groupSignature = signature;
    state.lens = resolveLens(groups, state.lens);
    state.groups = groups;
    if (state.lens !== "activity") setActivityKind("");
    groupControls.render(groups, state.lens, state.groupRange);
    if (state.activityKind) setActivityKind(state.activityKind);
  }
  function renderEvents(renderScene = scene.render, append = false) {
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
      $("#scene-people-count").textContent = state.lens === "none" ? "" : historyCount(0, 0, state.aggregate);
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
      renderScene(state.events, state.selected, state.aggregate);
    } else {
      scene.clear();
      journal.render(state.events, {
        selected: state.selected,
        modules: state.groups,
        lens: state.lens,
        aggregate: state.aggregate,
        append,
      });
      $("#scene-people-count").textContent =
        historyCount(state.events.length, new Set(state.events.map(event => event.actor_id)).size, state.aggregate);
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
  function requestOlder(retry = true) {
    if (root.dataset.route === "timeline") void liveHistory.older(retry);
  }
  historyMore.addEventListener("click", () => requestOlder());
  function clearHistory() {
    state.events = [];
    state.next = state.selected = state.aggregate = null;
    scene.clear();
    scene.configure(state.groups, state.lens);
    journal.clear();
    selectedSignal.render(null);
    followControls.select(null);
    interactionControls.select(null);
    $("#scene-people-count").textContent = "";
    $("#journey-position").textContent = "Loading local history";
    $("#history").innerHTML =
      '<div class="loading-state"><span class="loading-dot" aria-hidden="true"></span>Loading local history…</div>';
  }
  async function setDemo(enabled) {
    const address = new URL(location.href);
    if (enabled) address.searchParams.set("demo", "1");
    else address.searchParams.delete("demo");
    history.replaceState(null, "", address);
    state.demo = enabled;
    setActivityKind("");
    $("#demo-toggle").textContent = enabled
      ? "Leave demo ↗"
      : "Explore demo ↗";
    notice("");
    if (state.status) renderStatus(state.status);
    if (root.dataset.route === "timeline") await liveHistory.load(activityHud.refresh);
    else view("timeline");
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
      setActivityKind("");
      $$("[data-filter]").forEach((item) =>
        item.setAttribute("aria-pressed", item === button),
      );
      void liveHistory.load();
    }),
  );
  $$("[data-subject]").forEach((button) =>
    button.addEventListener("click", () => {
      state.subject = button.dataset.subject;
      setActivityKind("");
      $$("[data-subject]").forEach((item) =>
        item.setAttribute("aria-pressed", item === button),
      );
      void liveHistory.load(activityHud.refresh);
    }),
  );
  $$("[data-layout]").forEach((button) =>
    button.addEventListener("click", () => {
      state.layout = button.dataset.layout;
      $$("[data-layout]").forEach((item) =>
        item.setAttribute("aria-pressed", item === button),
      );
      if (historyPhase !== "initial") renderEvents();
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
      if (root.dataset.route === "timeline") await liveHistory.refresh();
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
  let pollTimer;
  let pageActive = true;
  function stopHistory() {
    pageActive = false;
    clearTimeout(pollTimer);
    liveHistory.cancel();
  }
  const unmount = new MutationObserver(() => {
    if (!root.isConnected) dispose();
  });
  // Gradio can remove the workspace node or replace its outer host.
  for (let node = root; node; ) {
    const parent = node.parentNode;
    if (parent) {
      unmount.observe(parent, {childList: true});
      node = parent;
    } else node = node.host;
  }
  function dispose() {
    stopHistory();
    unmount.disconnect();
    window.removeEventListener("pagehide", stopHistory);
    window.removeEventListener("pageshow", resumeHistory);
    scene.destroy();
    journal.destroy();
    groupControls.destroy();
    activityHud.destroy();
    selectedSignal.destroy();
    followControls.destroy();
    interactionControls.destroy();
    notices.destroy();
  }
  window.addEventListener("pagehide", stopHistory);
  window.addEventListener("pageshow", resumeHistory);
  function resumeHistory(event) {
    if (event.persisted) {
      pageActive = true;
      void poll();
    }
  }
  async function poll() {
    if (!root.isConnected) {
      dispose();
      return;
    }
    if (!document.hidden || state.status?.selection.notifications) {
      try {
        const status = await api("/api/status");
        if (!pageActive) return;
        renderStatus(status);
        if (root.dataset.route === "timeline") {
          await activityHud.refresh();
          if (pageActive && root.dataset.route === "timeline") await liveHistory.refresh();
        }
      } catch (error) {
        notices.update({ message: error.message, tone: "error" });
      }
    }
    if (pageActive) pollTimer = setTimeout(poll, 10000);
  }
  try {
    const status = await api("/api/status");
    if (!pageActive) return;
    renderStatus(status);
    if (new URLSearchParams(location.search).get("demo") === "1")
      await setDemo(true);
    else await liveHistory.load(activityHud.refresh);
    const hash = location.hash.slice(1);
    if (["profile", "about"].includes(hash)) view(hash);
    if (pageActive) pollTimer = setTimeout(poll, 10000);
  } catch (error) {
    notice(error.message, "error");
  }
})();
