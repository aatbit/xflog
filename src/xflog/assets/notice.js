const icons = {
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
  success: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  warning: '<path d="m12 3 10 18H2L12 3Zm0 6v5m0 3v1"/>',
  error: '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/>',
};

export function statusNotice(status) {
  if (status.cleanup_warning) return { message: status.cleanup_warning, tone: "warning" };
  if (["reconnect", "error"].includes(status.state))
    return { message: status.message, tone: "error" };
  if (status.state === "reconnecting") return { message: status.message, tone: "warning" };
  if (status.preference_warning) return { message: status.preference_warning, tone: "warning" };
  if (status.profile_warning) return { message: status.profile_warning, tone: "warning" };
  return null;
}

export function createNotice(element) {
  const text = element.querySelector("#notice-message");
  const icon = element.querySelector(".notice-icon");
  const kind = element.querySelector("#notice-kind");
  let timer;
  let current = null;
  let previousStatus = null;

  function hide() {
    clearTimeout(timer);
    element.hidden = true;
  }
  function schedule() {
    clearTimeout(timer);
    if (!element.hidden && ["info", "success"].includes(current?.tone) &&
        !element.matches(":hover, :focus-within")) timer = setTimeout(hide, 6000);
  }
  function show(message, tone = "info") {
    hide();
    current = message ? { message, tone: icons[tone] ? tone : "info" } : null;
    text.textContent = message || "";
    if (!current) return;
    element.dataset.tone = current.tone;
    icon.innerHTML = icons[current.tone];
    kind.textContent = `${current.tone}: `;
    element.hidden = false;
    schedule();
  }
  function update(next) {
    if (next?.message === previousStatus?.message && next?.tone === previousStatus?.tone) return;
    const old = previousStatus;
    previousStatus = next;
    if (next) show(next.message, next.tone);
    else if (current?.message === old?.message && current?.tone === old?.tone) show("");
  }
  element.querySelector("#notice-dismiss").addEventListener("click", hide);
  for (const event of ["pointerenter", "focusin"])
    element.addEventListener(event, () => clearTimeout(timer));
  for (const event of ["pointerleave", "focusout"])
    element.addEventListener(event, schedule);
  return { show, update, destroy: hide, get message() { return current?.message || ""; } };
}
