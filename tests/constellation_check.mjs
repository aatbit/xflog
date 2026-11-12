import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";

const base = pathToFileURL(process.argv[2] + "/");
const {
  constellationLayout,
  prepareConstellation,
  peopleFromEvents,
  entriesFromEvents,
  visibleLabels,
  flowStep,
  wheelDistance,
  normalizeMotionSpeed,
} = await import(new URL("constellation-layout.js", base));
const { createConstellation } = await import(new URL("constellation.js", base));
const { resolveLens } = await import(new URL("audience-ui.js", base));
const { groupKey, groupDescription } = await import(new URL("constellation-colors.js", base));
const { groupEvents } = await import(new URL("audience-groups.js", base));
const modules = JSON.parse(process.argv[3]);
const locations = modules.find((module) => module.key === "profile-location");
const cityEvents = Array.from({ length: 40 }, (_, index) => ({
  actor_id: String(index),
  event_id: String(index),
  sequence: index,
  audience_groups: {
    "profile-location": index ? `location-${index}` : "unknown",
  },
  audience_group_buckets: {
    "profile-location": {
      key: index ? `location-${index}` : "unknown",
      label: index ? `City ${index}` : "Unknown",
      tone: "neutral",
    },
  },
}));
for (const width of [320, 390, 798, 1440])
  for (const height of [420, 560, 772])
    for (const zoom of [0, 0.3, 1, 2]) {
      const layout = constellationLayout({
        events: cityEvents,
        width,
        height,
        zoom,
        modules,
        lens: locations.key,
      });
      assert.equal(layout.groups.length,40,"Every available location group remains separate at every zoom");
      assert.ok(!layout.groups.some(group=>group.key==="overview-more"));
      assert.ok(layout.groups.some((group) => group.key === "unknown"));
      assert.equal(
        layout.groups.reduce((total, group) => total + group.people.length, 0),
        40,
      );
      assert.ok(
        layout.people.every((point) => point.y > 0 && point.y < height),
      );
      assert.ok(layout.center < height / 2);
    }
const inactive = modules.map((module) => ({ ...module, enabled: false }));
assert.equal(
  resolveLens(modules, "none"),
  "none",
  "The grouping picker starts ungrouped even when Activity is available.",
);
assert.equal(
  resolveLens(modules, "none"),
  "none",
  "An explicit Ungrouped lens survives optional-group changes.",
);
assert.equal(resolveLens(inactive, "activity"), "none");
assert.equal(
  resolveLens(modules, "activity"),
  "activity",
  "An explicit grouping choice stays selected while enabled.",
);
const events = Array.from({ length: 50 }, (_, index) => ({
  actor_id: String(index % 19),
  event_id: String(index),
  sequence: index,
  audience_groups: Object.fromEntries(
    modules.map((module) => [
      module.key,
      module.buckets[index % module.buckets.length].key,
    ]),
  ),
})).reverse();
const activity = modules.find(module=>module.key==="activity");
for (const fixture of [events, cityEvents]) {
  const expectedEvents = new Set(fixture.map(event => event.event_id));
  const expectedActors = new Set(fixture.map(event => event.actor_id));
  for (const module of modules) {
    const layout = constellationLayout({events:fixture,width:798,height:772,zoom:0.8,modules,lens:module.key});
    assert.deepEqual(new Set(layout.people.map(person => person.event.event_id)), expectedEvents,
      `${module.key} preserves all event identities`);
    assert.deepEqual(new Set(layout.people.map(person => person.event.actor_id)), expectedActors,
      `${module.key} preserves all actors`);
  }
}
const mixed = [
  ["like-new", "A", "interaction.likes_received"],
  ["reply", "A", "interaction.replies"],
  ["follow", "A", "follow.follow"],
  ["unfollow", "A", "follow.unfollow"],
  ["like-old", "A", "interaction.likes_received"],
  ["other-unfollow", "B", "follow.unfollow"],
].map(([event_id, actor_id, kind], index) => ({
  event_id, actor_id, kind, sequence: 6 - index,
  audience_groups: { activity: kind },
}));
for (const zoom of [0, 0.8, 1.5]) {
  const layout = constellationLayout({events:mixed,width:1440,height:886,zoom,modules,lens:"activity"});
  assert.deepEqual(layout.groups.map(group=>group.key), [
    "follow.follow", "follow.unfollow", "interaction.replies", "interaction.likes_received",
  ], "Newer likes and replies must not erase recorded follow/unfollow groups");
  assert.equal(layout.groups.find(group=>group.key==="follow.unfollow").people.length, 2);
  const likes = layout.groups.find(group=>group.key==="interaction.likes_received").people;
  assert.equal(likes.length, 2, "Repeated actions are distinct entries within a group");
  assert.equal(layout.groups.find(group=>group.key==="interaction.likes_received").personCount,1);
  assert.equal(likes[0].event.event_id, "like-new");
}
const separated = constellationLayout({events,width:798,height:772,zoom:0.8,modules,lens:"activity"});
assert.ok(separated.grouped);
assert.equal(new Set(separated.groups.map(group=>group.color)).size,separated.groups.length,
  "Every displayed constellation has a distinct line color");
const orderedGroups = separated.groups.map(group=>separated.people.filter(person=>person.group===group.key));
for(let i=1;i<orderedGroups.length;i++) {
  const rightEdge=Math.max(...orderedGroups[i-1].map(person=>person.x));
  const leftEdge=Math.min(...orderedGroups[i].map(person=>person.x));
  assert.ok(leftEdge-rightEdge>798*0.35,"Neighboring constellations keep their overview left/right order with a clear empty gap");
}
const subset=constellationLayout({events:events.filter(event=>event.audience_groups.activity!==activity.buckets[0].key),width:798,height:772,zoom:0.8,modules,lens:"activity"});
for(const group of subset.groups)
  assert.equal(group.color,separated.groups.find(item=>item.key===group.key).color,
    "Filtering preserves the canonical group colors");
const overview=constellationLayout({events,width:798,height:772,zoom:0,modules,lens:"activity"});
for(const group of overview.groups.filter(group=>group.key!=="overview-more"))
  assert.equal(group.color,separated.groups.find(item=>item.key===group.key).color,
    "Overview and zoomed constellations use the same colors");
for(const a of overview.groups.filter(group=>group.key!=="overview-more"))
  for(const b of overview.groups.filter(group=>group.key!=="overview-more")) {
    if(a.y!==b.y || a.x>=b.x) continue;
    const aPoints=separated.people.filter(person=>person.group===a.key);
    const bPoints=separated.people.filter(person=>person.group===b.key);
    assert.ok(Math.max(...aPoints.map(person=>person.x))<Math.min(...bPoints.map(person=>person.x)),
      "A constellation on the left stays left of its neighbor after zooming in");
  }
const ungrouped=constellationLayout({events,width:798,height:772,zoom:0.8,modules,lens:"none"});
assert.equal(ungrouped.grouped,false);
assert.deepEqual(ungrouped.people.map(person=>person.id),entriesFromEvents(events).map(person=>person.id));
assert.ok(ungrouped.people.every(person=>person.color===undefined),"Ungrouped keeps its original neutral timeline");
assert.ok(groupKey(separated.groups,String).includes('role="listitem"'),"Colors have named, counted key entries");
assert.equal(peopleFromEvents(events).length, 19);
assert.equal(
  peopleFromEvents([...events].reverse())[0].event.sequence,
  49,
  "Representative is latest received sequence, independent of input order.",
);
for (const width of [320, 390, 798, 1440])
  for (const height of [560, 772, 920]) {
    for (const lens of [...modules.map((module) => module.key), "none"])
      for (const zoom of [0, 0.25, 0.3, 0.55, 1, 2]) {
        const layout = constellationLayout({
          events,
          width,
          height,
          zoom,
          modules,
          lens,
        });
        const rawGroups = groupEvents(events, modules, lens);
        let expectedPeople = 0;
        for (const group of layout.groups) {
          const records = !rawGroups ? events : group.key === "overview-more"
            ? rawGroups.filter(raw => !layout.groups.some(item=>item.key===raw.key)).flatMap(raw=>raw.events)
            : rawGroups.find(raw=>raw.key===group.key).events;
          const expected = [...new Set(records.map(event=>event.event_id))].sort();
          assert.deepEqual(group.people.map(person=>person.id).sort(), expected,
            "Every group retains each distinct matching recorded event");
          expectedPeople += expected.length;
        }
        assert.equal(layout.people.length, expectedPeople);
        assert.equal(
          layout.groups.reduce((sum, group) => sum + group.people.length, 0),
          expectedPeople,
          "Every recorded event has its own timeline node.",
        );
        assert.ok(layout.center < height / 2);
        assert.ok(
          layout.people.every(
            (point) =>
              Number.isFinite(point.x) &&
              point.x >= 0 &&
              point.x <= layout.width &&
              point.y >= 0 &&
              point.y < height,
          ),
        );
        if (layout.canPan && !layout.overview) {
          layout.people
            .slice(1)
            .forEach((point, index) =>
              assert.ok(
                point.x < layout.people[index].x,
                "Newer received sequences must always lie to the right.",
              ),
            );
        }
        if (layout.overview) {
          layout.groups.forEach((a, index) =>
            layout.groups
              .slice(index + 1)
              .forEach((b) =>
                assert.ok(
                  Math.abs(a.x - b.x) >= 150 ||
                    Math.abs(a.y - b.y) >= (width < 680 ? 124 : 156) - 1e-6,
                  "Group hit targets must not overlap.",
                ),
              ),
          );
        }
        if (zoom <= 0.25) {
          assert.ok(layout.width >= width);
          assert.equal(layout.canPan, layout.width > width + 0.5);
          assert.equal(layout.overview, lens !== "none");
        }
      }
    const disabled = constellationLayout({
      events,
      width,
      height,
      zoom: 0,
      modules: modules.map((module) => ({ ...module, enabled: false })),
      lens: "account-size",
    });
    assert.equal(disabled.overview, false);
    assert.equal(disabled.groups.length, 1);
    const boxes = Array.from({ length: 30 }, (_, index) => ({
      id: String(index),
      left: index * 35,
      right: index * 35 + 125,
      top: (index % 3) * 80,
      bottom: (index % 3) * 80 + 65,
      distance: index,
    }));
    const visible = visibleLabels(boxes, "12");
    assert.ok(visible.has("12"));
    const shown = [...visible.values()];
    shown.forEach((a, index) =>
      shown
        .slice(index + 1)
        .forEach((b) =>
          assert.ok(
            a.right + 12 <= b.left ||
              b.right + 12 <= a.left ||
              a.bottom + 10 <= b.top ||
              b.bottom + 10 <= a.top,
          ),
        ),
    );
  }
const selectedBox = {id:"selected",left:300,right:490,top:200,bottom:284,distance:0};
const neighbors = [
  {...selectedBox,id:"left",left:165,right:291,top:230,bottom:272,distance:167,
    alternates:[{left:165,right:291,top:140,bottom:182}]},
  {...selectedBox,id:"right",left:499,right:625,top:220,bottom:262,distance:167,
    alternates:[{left:499,right:625,top:140,bottom:182}]},
];
const staggered = visibleLabels([...neighbors,selectedBox],"selected");
assert.equal(staggered.size,3,"Nearby labels try the free space above their stars before hiding");
assert.equal(staggered.get("selected"),selectedBox,"The selected label stays in its existing position");
assert.ok(visibleLabels([{...selectedBox,maxBottom:220}],"selected").has("selected"),
  "The selected label remains visible even when an unusually long name exceeds the label area");
for(const neighbor of neighbors) assert.equal(staggered.get(neighbor.id).top,140);
assert.equal(visibleLabels([selectedBox,{...selectedBox,id:"crowded"}],"selected").size,1,
  "Labels still hide when no non-overlapping placement is available");
const scrolledBoxes = [...neighbors, selectedBox].map(box => ({
  ...box, left: box.left - 35, right: box.right - 35,
  alternates: box.alternates?.map(alternate => ({
    ...alternate, left: alternate.left - 35, right: alternate.right - 35,
  })),
}));
const scrolledLabels = visibleLabels(scrolledBoxes, "selected");
assert.deepEqual([...scrolledLabels].map(([id, box]) => [id, box.top]),
  [...staggered].map(([id, box]) => [id, box.top]),
  "Collision placement preserves priority and vertical positions when only the viewport origin shifts");
const tight = {...neighbors[0],alternates:[{left:165,right:291,top:190,bottom:232}]};
assert.equal(visibleLabels([selectedBox,tight],"selected").get("left").bottom,190,
  "An alternate can move slightly further above a neighboring label to preserve the safety gap");
assert.equal(visibleLabels([selectedBox,{...tight,minTop:180}],"selected").size,1,
  "A crowded label must not be pushed into the header to make it fit");
const extension = {
  key: "future",
  enabled: true,
  buckets: [{ key: "unknown", label: "Unknown", tone: "neutral" }],
};
assert.equal(
  constellationLayout({
    events,
    width: 390,
    height: 772,
    zoom: 0,
    modules: [extension],
    lens: "future",
  }).groups[0].people.length,
  events.length,
  "New registered module needs no renderer branch.",
);
assert.ok(
  Math.abs(flowStep(flowStep(0, 100, 8), 100, 8) - flowStep(0, 100, 16)) < 1e-8,
);
assert.ok(
  wheelDistance({ deltaX: 0, deltaY: 100, deltaMode: 0 }, 390) > 0,
  "Wheel down travels right toward newer events.",
);
assert.equal(normalizeMotionSpeed("invalid"), 1);
assert.equal(normalizeMotionSpeed(-1), 0.25);
assert.equal(normalizeMotionSpeed(20), 2);

function exercise(refreshRate, speed = 1, duration = 1000) {
  const pending = new Map();
  let nextId = 0,
    writes = 0,
    observer;
  const handlers = {};
  const control = () => ({
    style: { setProperty() {} },
    classList: { toggle() {} },
    setAttribute() {},
    addEventListener() {},
    removeEventListener() {},
  });
  const controls = new Map();
  const star = {
    style: {
      set opacity(value) {
        this.value = value;
        writes++;
      },
    },
  };
  const sky = { style: {}, setAttribute() {} };
  const meteor = { style: {}, dataset: {}, setAttribute() {} };
  const reduced = {
    matches: false,
    addEventListener(type, callback) {
      this.callback = callback;
    },
    removeEventListener() {},
  };
  globalThis.matchMedia = () => reduced;
  globalThis.requestAnimationFrame = (callback) => {
    pending.set(++nextId, callback);
    return nextId;
  };
  globalThis.cancelAnimationFrame = (id) => pending.delete(id);
  globalThis.document = {
    hidden: false,
    addEventListener(type, callback) {
      handlers[type] = callback;
    },
    removeEventListener() {},
  };
  globalThis.MutationObserver = class {
    constructor(callback) {
      observer = this;
      this.callback = callback;
    }
    observe() {}
    disconnect() {
      this.disconnected = true;
    }
  };
  globalThis.ResizeObserver = class {
    observe() {}
    disconnect() {}
  };
  const root = {
    isConnected: true,
    dataset: { route: "timeline", motion: "on", motionSpeed: String(speed) },
    querySelector(selector) {
      if (!controls.has(selector)) controls.set(selector, control());
      return controls.get(selector);
    },
  };
  const linkLayer = {style: {}, querySelectorAll: () => []};
  const element = {
    isConnected: true,
    dataset: {},
    clientWidth: 800,
    clientHeight: 700,
    scrollWidth: 800,
    scrollLeft: 0,
    classList: { contains: () => true, toggle() {} },
    querySelector: (selector) => selector === ".shooting-star" ? meteor
      : selector === ".constellation-links" ? linkLayer : sky,
    querySelectorAll: (selector) => (selector === ".sky-star" ? [star] : []),
    addEventListener() {},
    removeEventListener() {},
  };
  const scene = createConstellation({ element, root });
  scene.render([], null);
  const frame = (now) => {
    assert.equal(pending.size, 1, "Exactly one animation frame is scheduled.");
    const [id, callback] = pending.entries().next().value;
    pending.delete(id);
    callback(now);
  };
  for (let index = 0; index <= (refreshRate * duration) / 1000; index++)
    frame(1000 + (index * 1000) / refreshRate);
  assert.equal(
    writes,
    (refreshRate * duration) / 1000 + 1,
    "Every available display frame paints; no fixed FPS cap.",
  );
  const finalOpacity = star.style.value;
  root.dataset.motionSpeed = "2";
  observer.callback();
  frame(1000 + duration);
  assert.equal(
    star.style.value,
    finalOpacity,
    "Speed change preserves current phase.",
  );
  root.dataset.route = "profile";
  observer.callback();
  assert.equal(pending.size, 0);
  assert.equal(root.dataset.animating, "false");
  root.dataset.route = "timeline";
  observer.callback();
  frame(100000);
  assert.equal(
    star.style.value,
    finalOpacity,
    "Profile return resumes without a time jump.",
  );
  document.hidden = true;
  handlers.visibilitychange();
  assert.equal(pending.size, 0);
  document.hidden = false;
  handlers.visibilitychange();
  frame(100100);
  root.dataset.motion = "off";
  observer.callback();
  frame(100200);
  assert.equal(pending.size, 0);
  root.dataset.motion = "on";
  observer.callback();
  frame(100300);
  reduced.matches = true;
  reduced.callback();
  frame(100400);
  assert.equal(pending.size, 0, "Reduced motion stops the continuous loop.");
  scene.destroy();
  assert.equal(pending.size, 0);
  assert.ok(observer.disconnected);
  return Number(finalOpacity);
}
assert.ok(Math.abs(exercise(60) - exercise(120)) < 1e-10);
assert.ok(Math.abs(exercise(60) - exercise(144)) < 1e-10);
assert.ok(Math.abs(exercise(60, 2) - exercise(60, 1, 2000)) < 1e-10);
await import("./audience_ui_check.mjs");

const repeated = mixed.filter(event=>event.kind==="interaction.likes_received");
const entryLayout = constellationLayout({events:repeated,width:798,height:772,zoom:0.8,modules,lens:"none"});
assert.equal(entryLayout.people.length,2);
assert.notEqual(entryLayout.people[0].x,entryLayout.people[1].x);
assert.notEqual(entryLayout.people[0].id,entryLayout.people[1].id);
assert.equal(entriesFromEvents([...repeated,repeated[0]]).length,2,"Duplicate delivery of the same event does not add another entry");

const repeatedGroup = {label:"Likes", people:entriesFromEvents(repeated), personCount:1};
assert.equal(groupDescription(repeatedGroup), "2 actions · 1 person");
const repeatedKey = groupKey([repeatedGroup], String);
assert.ok(repeatedKey.includes('constellation-key-count">2</span>'));
assert.ok(repeatedKey.includes('title="2 actions · 1 person"'));
assert.ok(repeatedKey.includes('aria-label="Likes, 2 actions · 1 person"'));
assert.equal(groupDescription({...repeatedGroup,people:repeatedGroup.people.slice(0,1)}),"1 action · 1 person");
assert.equal(groupDescription({...repeatedGroup,personCount:2}),"2 actions · 2 people");

// Compare placement with the original identity-based searches, independently of the new index.
const lookupEvents = Array.from({length: 24}, (_, index) => {
  const activityKey = ["follow.follow", "follow.unfollow", "interaction.replies", "missing"][index % 4];
  const locationKey = index % 5 ? `city-${String(index % 17).padStart(2, "0")}` : "unknown";
  return {
    event_id: `event-${index}`, actor_id: `actor-${index % 3}`, sequence: 24 - index,
    audience_groups: {activity: activityKey, "profile-location": locationKey},
    audience_group_buckets: {"profile-location": {key: locationKey, label: `City ${locationKey}`}},
  };
});
const duplicateDelivery = {...lookupEvents[0], sequence: -1};
// Conflicting duplicate IDs have historically been deduplicated within each group, not globally.
const crossGroupDuplicate = {...lookupEvents[0], audience_groups: {
  activity: "interaction.replies", "profile-location": "city-09",
}, audience_group_buckets: {"profile-location": {key: "city-09", label: "City city-09"}}};
const skewedEvents = lookupEvents.map((event, index) => ({
  ...event, audience_groups: {...event.audience_groups, activity: index < 22 ? "follow.follow" : event.audience_groups.activity},
}));
const lookupFixtures = [
  [], [lookupEvents[0]], lookupEvents.slice(0, 3),
  skewedEvents, [...lookupEvents, duplicateDelivery, crossGroupDuplicate],
];
const baselineGeometry = [];
for (const records of lookupFixtures)
  for (const lens of ["none", "activity", "profile-location"])
    for (const width of [390, 1024])
      for (const zoom of [0, 0.25, 0.250001, 0.6, 1, 2]) {
        const height = 772;
        const layout = constellationLayout({events: records, width, height, zoom, modules, lens});
        const occupied = layout.groups;
        const ordered = layout.grouped
          ? [...occupied].reverse().flatMap(group => group.people)
          : occupied[0]?.people || [];
        assert.equal(layout.people.length, ordered.length);
        const blend = clampReference((zoom - 0.25) / 0.75, 0, 1);
        const spacing = (width < 680 ? 245 : 285) * zoom;
        const groupGap = layout.grouped ? width * 0.5 * blend : 0;
        ordered.forEach((entry, index) => {
          const matchingGroups = occupied.filter(group => group.people.includes(entry));
          assert.equal(matchingGroups.length, 1, "Each entry object belongs to exactly one occupied group");
          const group = occupied.find(item => item.people.includes(entry));
          const member = group.people.indexOf(entry);
          const groupIndex = occupied.indexOf(group);
          const angle = member * 2.399963229728653;
          const radius = Math.min(width < 600 ? 44 : 76, 14 + Math.sqrt(member) * 13);
          const fitX = clampReference(group.x + Math.cos(angle) * radius, 32,
            (zoom <= 0.25 ? layout.width : width) - 32);
          const fitY = clampReference(group.y + Math.sin(angle) * radius * 0.6, layout.upper, layout.lower);
          const timelineX = width / 2 + (ordered.length - 1 - index) * spacing;
          const timelineY = clampReference(group.y + (seedReference(entry.id) - 0.5) *
            Math.min(400, (layout.lower - layout.upper) * 0.9), layout.upper + 20, layout.lower - 20);
          const point = layout.people[index];
          assert.strictEqual(point.event, entry.event, "Event object identity and reverse flattening stay unchanged");
          assert.strictEqual(point.events, entry.events);
          assert.equal(point.group, group.key);
          assert.equal(point.tone, group.tone);
          assert.equal(point.color, group.color);
          assert.equal(point.x, zoom <= 0.25 ? fitX : width / 2 + (timelineX - width / 2) * blend + groupIndex * groupGap);
          assert.equal(point.y, fitY * (1 - Math.sqrt(blend)) + timelineY * Math.sqrt(blend));
        });
        // Record positions and group order as well as points to catch changes outside the reference calculation.
        const rounded = value => typeof value === "number" ? Number(value.toFixed(8)) : value;
        baselineGeometry.push({
          grouped: layout.grouped, overview: layout.overview, width: rounded(layout.width),
          upper: rounded(layout.upper), lower: rounded(layout.lower), center: rounded(layout.center),
          groups: occupied.map(group => [group.key, group.tone, group.color, rounded(group.x), rounded(group.y), group.people.map(person => person.id)]),
          points: layout.people.map(point => [point.id, point.group, point.tone, point.color, rounded(point.x), rounded(point.y)]),
        });
      }
function clampReference(value, low, high) { return Math.max(low, Math.min(high, value)); }
function seedReference(value) {
  let hash = 2166136261;
  for (const letter of String(value)) hash = Math.imul(hash ^ letter.charCodeAt(0), 16777619);
  hash = Math.imul(hash ^ (hash >>> 16), 2246822507);
  hash = Math.imul(hash ^ (hash >>> 13), 3266489909);
  hash ^= hash >>> 16;
  return (hash >>> 0) / 4294967295;
}
const geometryDigest = createHash("sha256").update(JSON.stringify(baselineGeometry)).digest("hex");
assert.equal(geometryDigest, "140fd1844b9614ca831c59b28ff1912b55f2789983d6c3638827166f71041ebb",
  "Group ordering, colors and geometry match the original layout at e283194");
for (const records of lookupFixtures)
  for (const lens of ["none", "activity", "profile-location"])
    for (const width of [390, 1024]) {
      const options = {events: records, width, height: 772, modules, lens};
      const atZoom = prepareConstellation(options);
      const original = atZoom(0.8), points = [...original.people], groups = [...original.groups];
      for (const zoom of [0, 0.05, 0.2, 0.25, 0.250001, 0.3, 0.55, 0.8, 1, 1.5, 2, 0]) {
        const layout = atZoom(zoom);
        assert.equal(layout, original, "Zoom keeps the geometry bindings live");
        assert.ok(layout.people.every((point, i) => point === points[i]));
        assert.ok(layout.groups.every((group, i) => group === groups[i]));
        assert.deepEqual(layout, constellationLayout({...options, zoom}),
          "Repeated in-place layout matches a fresh calculation");
      }
    }

// Count only searches involving layout entries/groups; unrelated color lookups remain untouched.
const originalFind = Array.prototype.find;
const originalIncludes = Array.prototype.includes;
const originalIndexOf = Array.prototype.indexOf;
const searches = {find: 0, includes: 0, indexOf: 0};
let positiveControl;
try {
  Array.prototype.find = function(predicate, ...args) {
    if (this.length && Array.isArray(this[0]?.people)) searches.find++;
    return originalFind.call(this, predicate, ...args);
  };
  Array.prototype.includes = function(item, ...args) {
    if (item && typeof item === "object" && item.event && item.events) searches.includes++;
    return originalIncludes.call(this, item, ...args);
  };
  Array.prototype.indexOf = function(item, ...args) {
    if (item && typeof item === "object" && (item.event && item.events || Array.isArray(item.people))) searches.indexOf++;
    return originalIndexOf.call(this, item, ...args);
  };
  const entry = {event: {}, events: []}, group = {people: [entry]}, occupied = [group];
  occupied.find(item => item.people.includes(entry));
  group.people.indexOf(entry);
  occupied.indexOf(group);
  positiveControl = {...searches};
  Object.assign(searches, {find: 0, includes: 0, indexOf: 0});
  constellationLayout({events: lookupEvents, width: 1024, height: 772, zoom: 0.8, modules, lens: "activity"});
} finally {
  Array.prototype.find = originalFind;
  Array.prototype.includes = originalIncludes;
  Array.prototype.indexOf = originalIndexOf;
}
assert.deepEqual(positiveControl, {find: 1, includes: 1, indexOf: 2}, "The structural counter detects the original searches");
assert.deepEqual(searches, {find: 0, includes: 0, indexOf: 0},
  "Point placement does not linearly search for each entry's group or indexes");
