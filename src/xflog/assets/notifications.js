let currentNotification = null;

function supported() {
  return globalThis.isSecureContext && typeof globalThis.Notification === "function";
}

export function activityDelta(previous, current) {
  if (!previous?.selection?.notifications || !current.selection.notifications) return 0;
  const count = current.notification_sequence - previous.notification_sequence;
  return Number.isInteger(count) && count > 0 ? count : 0;
}

export async function requestBrowserNotifications() {
  if (!supported()) return "unsupported";
  try {
    if (Notification.permission === "default") return await Notification.requestPermission();
    return Notification.permission;
  } catch {
    return "unsupported";
  }
}

export function clearActivityNotification() {
  try {
    currentNotification?.close();
  } catch {
    // Browser alert failures must not affect the in-app listener.
  }
  currentNotification = null;
}

export function notifyActivity(count) {
  if (!supported() || Notification.permission !== "granted" || !Number.isInteger(count) || count < 1)
    return false;
  try {
    clearActivityNotification();
    const notification = new Notification("XFlog", {
      body: `${count} new audience ${count === 1 ? "event" : "events"} recorded. Open XFlog to view your history.`,
      icon: "/static/xf/mark.svg",
      tag: "xflog-activity",
    });
    notification.onclick = () => {
      globalThis.focus?.();
      notification.close();
    };
    currentNotification = notification;
    return true;
  } catch {
    return false;
  }
}
