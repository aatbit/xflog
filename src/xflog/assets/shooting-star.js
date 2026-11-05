export function createShootingStar(random = Math.random) {
  let next;
  let star = null;
  let direction = -1;
  let delayBand = -1;
  let lifeBand = -1;
  function pickOther(previous, count) {
    const available = previous < 0 ? count : count - 1;
    const choice = Math.min(available - 1, Math.floor(random() * available));
    return previous >= 0 && choice >= previous ? choice + 1 : choice;
  }
  function schedule(clock) {
    delayBand = pickOther(delayBand, 3);
    next = clock + 6000 + delayBand * 6000 + random() * 4000;
  }
  schedule(0);
  return (clock, width, height) => {
    if (width <= 0 || height <= 0) return null;
    if (!star && clock >= next) {
      direction = pickOther(direction, 8);
      lifeBand = pickOther(lifeBand, 3);
      const angle =
        (direction * Math.PI) / 4 + ((random() - 0.5) * Math.PI) / 6;
      const duration =
        [350, 900, 1800][lifeBand] + random() * [350, 600, 1600][lifeBand];
      star = {
        start: clock,
        duration,
        lifeBand,
        reach: random(),
        x: width * (0.2 + random() * 0.6),
        y: height * (0.05 + random() * 0.4),
        vx: Math.cos(angle),
        vy: Math.sin(angle),
      };
    }
    if (!star) return null;
    const progress = (clock - star.start) / star.duration;
    if (progress >= 1) {
      star = null;
      schedule(clock);
      return null;
    }
    const distance =
      star.lifeBand === 2
        ? Math.hypot(width, height) * 1.4
        : Math.min(width, height) *
          (star.lifeBand === 0
            ? 0.2 + star.reach * 0.2
            : 0.6 + star.reach * 0.35);
    const tail = Math.min(120, width * 0.18);
    const offset = (star.reach - 0.5) * Math.min(width, height) * 0.2;
    const centerX = star.lifeBand === 2 ? width / 2 - star.vy * offset : star.x;
    const centerY =
      star.lifeBand === 2 ? height / 2 + star.vx * offset : star.y;
    const x = centerX + (progress - 0.5) * distance * star.vx;
    const y = centerY + (progress - 0.5) * distance * star.vy;
    return {
      x1: x - tail * star.vx,
      y1: y - tail * star.vy,
      x2: x,
      y2: y,
      opacity: Math.sin(progress * Math.PI) * 0.7,
    };
  };
}
