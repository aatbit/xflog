// Cover the widest label's half-width plus the viewport and collision gaps.
export const overscan = 128;

function bound(items, value, coordinate, afterEqual = false) {
  let start = 0, end = items.length;
  while (start < end) {
    const middle = (start + end) >>> 1;
    const x = coordinate(items[middle]);
    if (x < value || (afterEqual && x === value)) start = middle + 1;
    else end = middle;
  }
  return start;
}

const personX = item => item.label.person.x;
const segmentStart = item => item.start;
const maxEnd = item => item.maxEnd;

export function createViewportIndex(labels, sparks) {
  const people = labels.map((label, index) => ({label, index}))
    .sort((a, b) => personX(a) - personX(b) || a.index - b.index);
  const segments = sparks.map(spark => ({
    spark,
    start: Math.min(spark.a.x, spark.b.x),
    end: Math.max(spark.a.x, spark.b.x),
  })).sort((a, b) => a.start - b.start);
  let end = -Infinity;
  for (const segment of segments) {
    end = Math.max(end, segment.end);
    segment.maxEnd = end;
  }
  return {
    range(left, right) {
      const start = bound(people, left, personX);
      const stop = bound(people, right, personX, true);
      const connections = [];
      // Same-group timeline links join adjacent points. Prefix bounds also
      // retain any segment that spans the range with both endpoints outside it.
      const first = bound(segments, left, maxEnd);
      const last = bound(segments, right, segmentStart, true);
      for (let index = first; index < last; index++)
        if (segments[index].end >= left) connections.push(segments[index].spark);
      return {
        labels: people.slice(start, stop).sort((a, b) => a.index - b.index).map(item => item.label),
        connections,
      };
    },
    nearest(center) {
      const split = bound(people, center, personX);
      const right = people[split];
      const left = split && people[bound(people, personX(people[split - 1]), personX)];
      if (!left) return right?.label.person;
      if (!right) return left.label.person;
      const difference = (center - personX(left)) - (personX(right) - center);
      return (difference < 0 || (difference === 0 && left.index < right.index) ? left : right).label.person;
    },
  };
}
