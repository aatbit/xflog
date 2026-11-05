import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { createShootingStar } = await import(
  new URL("shooting-star.js", pathToFileURL(process.argv[2] + "/"))
);
for (const width of [320, 390, 800, 1440]) {
  const shoot = createShootingStar(() => 0);
  assert.equal(shoot(0, width, 700), null);
  assert.equal(shoot(5999, width, 700), null);
  const start = shoot(6000, width, 700);
  assert.equal(start.opacity, 0);
  const middle = shoot(6175, width, 700);
  assert.equal(middle.opacity, 0.7);
  assert.ok(
    (middle.x2 - start.x2) * (middle.x2 - middle.x1) +
      (middle.y2 - start.y2) * (middle.y2 - middle.y1) >
      0,
  );
  assert.ok(Object.values(middle).every(Number.isFinite));
  assert.equal(shoot(6350, width, 700), null);
  assert.equal(shoot(18349, width, 700), null);
  assert.equal(shoot(18350, width, 700).opacity, 0);
}
const delayed = createShootingStar(() => 1);
assert.equal(delayed(21999, 800, 700), null);
const entry = delayed(22000, 800, 700);
assert.equal(entry.opacity, 0);
const midpoint = delayed(23700, 800, 700);
const exit = delayed(25399, 800, 700);
const outside = (point) =>
  point.x2 < 0 || point.x2 > 800 || point.y2 < 0 || point.y2 > 700;
assert.ok(
  outside(entry) && !outside(midpoint) && outside(exit),
  "Long-lived meteors cross the whole viewport.",
);
assert.equal(delayed(25400, 800, 700), null);
assert.equal(delayed(41399, 800, 700), null);
assert.equal(delayed(41400, 800, 700).opacity, 0);
assert.equal(createShootingStar(() => 0)(9000, 0, 700), null);
let seed = 37;
const varied = createShootingStar(() => {
  seed = (seed * 1664525 + 1013904223) >>> 0;
  return seed / 2 ** 32;
});
let prior = null,
  lastDirection = null,
  lastBand = null,
  lastLife = null,
  started = 0,
  ended = 0,
  appearances = 0;
const lives = new Set();
for (let clock = 0; clock < 600000; clock += 100) {
  const shot = varied(clock, 1100, 800);
  if (shot && !prior) {
    started = clock;
    const angle = Math.atan2(shot.y2 - shot.y1, shot.x2 - shot.x1);
    const direction = (Math.round(angle / (Math.PI / 4)) + 8) % 8;
    assert.notEqual(
      direction,
      lastDirection,
      "Successive meteors never reuse the direction sector.",
    );
    lastDirection = direction;
    const band = Math.floor((clock - ended - 6000) / 6000);
    assert.notEqual(
      band,
      lastBand,
      "Successive delays never reuse the same timing band.",
    );
    lastBand = band;
    appearances++;
  }
  if (!shot && prior) {
    ended = clock;
    const lifetime = clock - started;
    const life = lifetime <= 700 ? 0 : lifetime <= 1500 ? 1 : 2;
    assert.notEqual(
      life,
      lastLife,
      "Successive meteors never reuse the same lifetime style.",
    );
    lastLife = life;
    lives.add(life);
  }
  if (shot)
    assert.ok(
      Object.values(shot).every(Number.isFinite) &&
        shot.opacity >= 0 &&
        shot.opacity <= 0.7,
    );
  prior = shot;
}
assert.ok(appearances > 25);
assert.equal(lives.size, 3);
console.log(
  "Shooting-star delay, fade, travel, interval bounds and viewport checks passed.",
);
