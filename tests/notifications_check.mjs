import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const { requestBrowserNotifications, notifyActivity, clearActivityNotification, activityDelta } =
  await import(pathToFileURL(process.argv[2]));

const status = (sequence, enabled = true) => ({notification_sequence:sequence,selection:{notifications:enabled}});
assert.equal(activityDelta(null,status(10)),0);
assert.equal(activityDelta(status(5,false),status(10)),0);
assert.equal(activityDelta(status(5),status(10,false)),0);
assert.equal(activityDelta(status(5),status(8)),3);
assert.equal(activityDelta(status(5),status(5)),0);
assert.equal(activityDelta(status(5),status(0)),0);

globalThis.isSecureContext = true;
assert.equal(await requestBrowserNotifications(), "unsupported");
assert.equal(notifyActivity(1), false);

let requested = 0;
let focused = 0;
const alerts = [];
globalThis.focus = () => focused++;
class FakeNotification {
  static permission = "default";
  static async requestPermission() {
    requested++;
    this.permission = "granted";
    return this.permission;
  }
  constructor(title, options) {
    this.title = title;
    this.options = options;
    this.closed = false;
    alerts.push(this);
  }
  close() { this.closed = true; }
}
globalThis.Notification = FakeNotification;

// Polling never prompts. Only the explicit settings action asks for permission.
assert.equal(notifyActivity(1), false);
assert.equal(requested, 0);
globalThis.isSecureContext = false;
assert.equal(await requestBrowserNotifications(), "unsupported");
assert.equal(requested, 0);
globalThis.isSecureContext = true;
assert.equal(await requestBrowserNotifications(), "granted");
assert.equal(requested, 1);
assert.equal(await requestBrowserNotifications(), "granted");
assert.equal(requested, 1);

assert.equal(notifyActivity(1), true);
assert.equal(alerts[0].title, "XFlog");
assert.ok(alerts[0].options.body.startsWith("1 new audience event recorded."));
assert.equal(alerts[0].options.tag, "xflog-activity");
assert.equal(notifyActivity(3), true);
assert.ok(alerts[1].options.body.startsWith("3 new audience events recorded."));
assert.equal(alerts[0].closed, true);
alerts[1].onclick();
assert.equal(focused, 1);
assert.equal(alerts[1].closed, true);
clearActivityNotification();
assert.equal(notifyActivity(0), false);
assert.equal(notifyActivity(NaN), false);
assert.equal(notifyActivity(1.5), false);

FakeNotification.permission = "denied";
assert.equal(await requestBrowserNotifications(), "denied");
assert.equal(notifyActivity(1), false);
assert.equal(requested, 1);
FakeNotification.permission = "default";
FakeNotification.requestPermission = async () => { throw new Error("Unavailable"); };
assert.equal(await requestBrowserNotifications(), "unsupported");

// Some mobile browsers expose the API but reject the constructor.
globalThis.Notification = class {
  static permission = "granted";
  constructor() { throw new Error("Not supported"); }
};
assert.equal(notifyActivity(1), false);
