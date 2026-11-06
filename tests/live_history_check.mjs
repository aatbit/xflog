import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const base = pathToFileURL(process.argv[2] + "/");
const { createLiveHistory, historyPath, updatedSelection, historyPages, groupSince, mergeHistory } = await import(new URL("live-history.js", base));
const { eventLabel, eventTone } = await import(new URL("format.js", base));
const { peopleFromEvents } = await import(new URL("constellation-layout.js", base));
const event = id => ({ event_id: String(id), kind: "interaction.replies", actor_id: "222", sequence: -id });
let state = {
  demo: false, subject: "followers", filter: "all", generation: 1,
  events: [event(4),event(3),event(2),event(1)], next: "older", selected: "2",
  status: { account: {id:"111"}, timeline_revision: "0:6", selection: {notifications:false,interactions:{replies:true}} },
};
const calls = [];
let refreshes = 0;
let blocked = null;
let fail = false;
const pages = {
  "0": {events:[event(8),event(7),event(6)],next:"page2"},
  page2: {events:[event(5),event(4),event(3)],next:"page3"},
};
const feed = createLiveHistory({
  read: () => ({...state}),
  api: async path => {
    calls.push(path);
    if(fail) throw new Error("Local database unavailable");
    if(blocked) await blocked.promise;
    return pages[new URL(path,"http://local").searchParams.get("before")];
  },
  apply: (events,next) => {state.events=events;state.next=next;},
  refreshInteractions: async () => refreshes++,
});
assert.match(historyPath(state),/^\/api\/timeline\?/);
assert.match(historyPath({...state,demo:true}),/^\/api\/demo\?/);
await feed.refresh();
assert.deepEqual(state.events.map(e=>e.event_id),["8","7","6","5","4","3","2","1"]);
assert.equal(state.selected,"2");
assert.equal(state.next,"older","Keep older pages already loaded");
assert.equal(calls.length,2,"Read through a burst larger than one page until overlap");
assert.equal(refreshes,1);
await feed.refresh();
assert.equal(calls.length,2,"Unchanged revision performs no history reads");

state.status={...state.status,timeline_revision:"0:9"};
blocked={};blocked.promise=new Promise(resolve=>blocked.resolve=resolve);
const pending=feed.refresh();
await Promise.resolve();
state.generation++;
const prior=state.events;
blocked.resolve();
await pending;
assert.equal(state.events,prior,"An old response cannot replace a newer view");
blocked=null;
fail=true;
await assert.rejects(feed.refresh(),/Local database unavailable/);
fail=false;
await feed.refresh();
assert.equal(refreshes,2,"Failed or stale requests remain retryable");

state.status={...state.status,timeline_revision:"0:10"};
blocked={};blocked.promise=new Promise(resolve=>blocked.resolve=resolve);
const selectionRace=feed.refresh();
await Promise.resolve();
const rowsBeforeDisable=state.events;
state.status={...state.status,selection:{notifications:false,interactions:{replies:false}}};
blocked.resolve();
await selectionRace;
blocked=null;
assert.equal(state.events,rowsBeforeDisable,"A response from a disabled selection is discarded");
pages["0"]={events:[],next:null};
await feed.refresh();
assert.equal(state.events.length,0,"Disabling a type removes its visible rows, not its saved data");
state.demo=true;
const count=calls.length;
await feed.refresh();
assert.equal(calls.length,count,"Live history never replaces demo examples");

state.demo=false;
state.events=[event(4),event(3),event(2),event(1)];
state.status={...state.status,timeline_revision:"0:11:profile-update",
  selection:{interactions:{replies:true},profile_names:true}};
pages["0"]={events:[{...event(4),name:"Maya",handle:"maya",profile_url:"https://x.com/maya"}],next:null};
await feed.refresh();
assert.equal(state.events.length,1,"Changing name resolution resets the visible history scope");
state.events.push(event(3),event(2),event(1));
state.status={...state.status,timeline_revision:"0:12:profile-update"};
await feed.refresh();
assert.ok(state.events.every(row=>row.name==="Maya" && row.handle==="maya" && row.profile_url==="https://x.com/maya"),
  "A newly cached identity also updates the same person in previously loaded pages");

assert.equal(eventLabel(event(1)),"Replied to you");
assert.equal(eventLabel({...event(1),kind:"interaction.likes_given"}),"You liked their post");
assert.equal(eventTone(event(1)),"neutral");
assert.equal(eventTone({kind:"follow.unfollow"}),"negative");
const people=peopleFromEvents([
  {event_id:"old-follow",actor_id:"222",sequence:100,received_at:"2026-11-04T10:00:00+00:00"},
  {event_id:"new-reply",actor_id:"222",sequence:-1,received_at:"2026-11-04T11:00:00+00:00"},
]);
assert.equal(people[0].event.event_id,"new-reply","Mixed sources select the latest receipt, not the largest table ID");
assert.equal(updatedSelection([event(4),event(3)],"4",[event(5),event(4),event(3)]),"5");
assert.equal(updatedSelection([event(4),event(3)],"3",[event(5),event(4),event(3)]),"3","Explicit older records stay selected");

const follows = {event_id:"follow",actor_id:"222",kind:"follow.follow",sequence:1,received_at:"2026-11-04T10:00:00Z"};
const unfollows = {...follows,event_id:"unfollow",actor_id:"333",kind:"follow.unfollow",sequence:2};
const newest = Array.from({length:25},(_,i)=>({...event(30-i),received_at:"2026-11-05T10:00:00Z"}));
const groupedState = {...state,lens:"activity",groupRange:"all",filter:"all",subject:"followers"};
const burstCalls=[];
const savedPages={"0":{events:newest,next:"older"},older:{events:[follows,unfollows],next:null}};
const savedApi=async path=>{
  const params=new URL(path,"http://local").searchParams;
  burstCalls.push(Object.fromEntries(params));
  return savedPages[params.get("before")];
};
const all=[];
for await(const page of historyPages(savedApi,groupedState)) all.push(...page.events);
assert.equal(all.length,27,"Grouped reads include all saved pages, not just the latest interaction page");
assert.deepEqual(all.slice(-2).map(row=>row.kind),["follow.follow","follow.unfollow"]);
assert.ok(burstCalls.every(call=>call.local_only==="true" && call.limit==="50"),"Grouped history reads never trigger profile requests");
assert.ok(!new URL(historyPath({...state,lens:"none"}),"http://local").searchParams.has("local_only"),"Ungrouped keeps its usual request");
const cutoff=groupSince({...groupedState,groupRange:"24h"},Date.parse("2026-11-06T10:00:59Z"));
assert.equal(cutoff,"2026-11-05T10:00:00.000Z");
assert.equal(groupSince(groupedState),"");
assert.equal(new URL(historyPath({...groupedState,since:cutoff}),"http://local").searchParams.get("since"),cutoff);
assert.equal(mergeHistory([...all,unfollows]).length,27,"Repeated delivery does not duplicate saved records");
let activityState={...groupedState,generation:1,events:[],next:null,status:{...state.status,timeline_revision:"activity-initial"}};
const activityFeed=createLiveHistory({read:()=>({...activityState}),api:savedApi,
  apply:(events,next)=>{activityState.events=events;activityState.next=next;},refreshInteractions:async()=>{}});
activityState.loading=true;
const callsDuringLoad=burstCalls.length;
await activityFeed.refresh();
assert.equal(burstCalls.length,callsDuringLoad,"A background refresh waits for the active history load instead of replacing it with a partial snapshot");
activityState.loading=false;
await activityFeed.refresh();
assert.equal(activityState.events.length,27,"Live grouped initialization also completes all saved pages");
assert.equal(activityState.next,null);
savedPages["0"]={events:[{...event(40),received_at:"2026-11-06T10:00:00Z"},...newest],next:"older"};
activityState.status={...activityState.status,timeline_revision:"activity-new"};
burstCalls.length=0;
await activityFeed.refresh();
assert.equal(burstCalls.length,1,"Once complete, live updates stop at overlap without rereading all history");
assert.equal(activityState.events.length,28);
await assert.rejects(async()=>{for await(const page of historyPages(async()=>({events:[],next:"0"}),groupedState)) {}},/did not advance/);

const realNow=Date.now;
let now=Date.parse("2026-11-06T10:00:00Z");
Date.now=()=>now;
try {
  const recent={...event(60),received_at:"2026-11-05T10:01:00Z"};
  const older={...follows,received_at:"2026-11-03T10:00:00Z"};
  let ranged={...groupedState,generation:1,events:[],next:null};
  const rangeRequests=[];
  const rangeFeed=createLiveHistory({read:()=>({...ranged}),
    api:async path=>{rangeRequests.push(path);return {events:[recent,older],next:null};},
    apply:(events,next)=>{ranged.events=events;ranged.next=next;},refreshInteractions:async()=>{}});
  await rangeFeed.refresh();
  assert.equal(ranged.events.length,2);
  ranged.groupRange="24h";
  await rangeFeed.refresh();
  assert.deepEqual(ranged.events.map(row=>row.event_id),["60"],"Narrowing a range removes older saved records");
  now+=2*60000;
  await rangeFeed.refresh();
  assert.equal(ranged.events.length,0,"A rolling range expires old activity even without a new event revision");
  ranged.groupRange="all";
  await rangeFeed.refresh();
  assert.equal(ranged.events.length,2,"Returning to All saved restores records outside the former range");
  assert.ok(rangeRequests.every(path=>new URL(path,"http://local").searchParams.get("local_only")==="true"));
} finally {
  Date.now=realNow;
}
