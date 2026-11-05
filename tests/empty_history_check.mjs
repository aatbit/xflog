import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { emptyHistory } = await import(pathToFileURL(process.argv[2]));
const state = { demo:false, subject:"followers", filter:"all", status:{connected:true,state:"stopped",selection:{subscriptions:false}} };
let html = emptyHistory(state);
assert.match(html, /data-empty-action="tracking"/);
assert.match(html, /Start tracking/);
assert.doesNotMatch(html, /Explore the demo/);
for (const status of ["tracking","connecting","reconnecting"]) {
  html = emptyHistory({...state,status:{...state.status,state:status}});
  assert.match(html,/Pause tracking/);
  assert.match(html,/Listening for activity/);
}
html = emptyHistory({...state,subject:"subscriptions"});
assert.match(html,/data-empty-action="profile"/);
html = emptyHistory({...state,status:{...state.status,connected:false}});
assert.match(html,/data-empty-action="demo"/);
assert.doesNotMatch(emptyHistory({...state,demo:true}),/<button/);
