export function emptyHistory(state) {
  const connected = state.status?.connected;
  const active = ["tracking", "connecting", "reconnecting"].includes(state.status?.state);
  let title = "Your next chapter starts here.";
  let copy = "Configure the instance, then start tracking to record follower changes.";
  let action = connected ? "tracking" : "demo";
  let label = connected ? (active ? "Pause tracking" : "Start tracking →") : "Explore the demo →";
  if (state.filter !== "all") {
    title = "No matching events yet.";
    copy = "Try All events, or return after more activity is received.";
  } else if (state.subject === "subscriptions" && !state.status?.selection.subscriptions && !state.demo) {
    title = "Subscriber history is optional.";
    copy = "Enable paid subscription events in Profile, then start tracking.";
    action = "profile";
    label = "Open profile →";
  } else if (connected) {
    title = active ? "Listening for activity." : "Ready when you are.";
    copy = active
      ? "New events will appear here as they arrive."
      : "History begins when tracking starts. Activity before that is not reconstructed.";
  }
  return `<div class="empty-state"><img src="/static/xf/mark.svg" width="48" height="48" alt=""><h2>${title}</h2><p>${copy}</p>${!state.demo ? `<button type="button" class="button" data-empty-action="${action}">${label}</button>` : ""}</div>`;
}
