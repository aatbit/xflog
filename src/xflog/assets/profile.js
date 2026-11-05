export function createProfileControls({ root, interactions }) {
  const $ = (selector) => root.querySelector(selector);
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
  function fillProfile(status) {
    if (!status) return;
    fillProfileStatus(status);
    for (const key of ["followers", "subscriptions", "notifications", "profile_names"])
      $(`#preferences-form [name="${key}"]`).checked = Boolean(
        status.selection[key],
      );
    const names = $('#preferences-form [name="profile_names"]');
    names.disabled = !status.connected && !names.checked;
    const follow = $('#preferences-form [name="follow_actions"]');
    follow.checked = Boolean(status.follow_actions?.enabled);
    follow.disabled = !status.follow_actions?.available && !follow.checked;
    interactions.fillProfile(status);
  }
  return { render: fillProfile, renderStatus: fillProfileStatus };
}
