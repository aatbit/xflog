# Changelog

Each tagged release has an automatically generated list of merged pull requests
and contributors on the [GitHub releases page](https://github.com/aatbit/xflog/releases).

## 1.0.8 — 2026-11-07

### Fixed

- All saved completes every history page in the ungrouped timeline instead of
  stopping after the first 25 events. Its contents include the matching 24h subset.
- Live refresh completes empty views and recovers correctly when a failed range
  change leaves earlier rows visible. Additional pages stay local-only.

No database migration or new environment settings are required.

## 1.0.7 — 2026-11-07

### Changed

- Constellation group badges and legend counts show total recorded actions, matching
  their event stars. Tooltips and accessible labels include unique people.
- Shared count formatting handles singular and plural actions and people consistently.

No database migration or new environment settings are required.

## 1.0.6 — 2026-11-06

### Fixed

- Each recorded action has its own constellation star, including repeated actions
  from the same person. New actions no longer replace earlier timeline entries.
- Live updates retain the exact selected action. Duplicate event deliveries do not
  create extra entries. Group overview counts continue to represent unique people.
- Navigation, HUD timestamps and documentation describe action-based history.

No database migration or new environment settings are required.

## 1.0.5 — 2026-11-06

### Fixed

- Constellation overview shows every available group separately instead of combining
  additional groups under More groups. Counts and colors stay attached to their groups.
- Dense overviews use the existing horizontal scroll and history slider when the
  available screen space is too small, keeping group targets readable and clickable.
  Group selection, zoom, person actions and ambient motion are preserved.

No database migration or new environment settings are required.

## 1.0.4 — 2026-11-06

### Changed

- The timeline and HUD share one time range. Both clock menus offer 1h, 6h,
  12h, 24h, 3d, 7d, 30d, 90d and All saved, starting at 24h. The range also
  applies to Journal and uses the HUD's server-provided cutoff.
- All saved shows lifetime counts and growth ratio; hourly rates and previous-period
  comparisons are left blank.
- The space background uses blue-black tones, with brighter primary and secondary
  text throughout the interface. Offline examples use recent dates.

### Fixed

- Range filtering keeps the existing opt-in name lookup available on the first
  ungrouped page. Additional range pages and grouped reads stay local-only.
- An empty ranged timeline receives the complete next burst of saved events,
  including bursts larger than one page.

No database migration or new environment settings are required.

## 1.0.3 — 2026-11-06

### Added

- Interaction event details show a compact excerpt of the saved post when text is
  available. Excerpts are limited to 280 characters, including an ellipsis for
  longer posts, and link directly to the corresponding post on X.
- Post previews use the local database without extra X requests. Missing text
  leaves the existing details layout uncluttered.

### Fixed

- Newly saved thread text appears in post previews through the local history
  refresh, including an older selected event, without another X request.

### Changed

- Interaction history and event details share the same validated X post-link helper.

No database migration or new environment settings are required.

## 1.0.2 — 2026-11-06

### Fixed

- Clicking an unselected star or name smoothly centers that person. Clicking the
  selected person again still opens their details; scrolling resumes center-based selection.
- Smooth scrolling finishes correctly when the browser rounds the last few pixels,
  preventing movement from stalling just short of the selected person.

### Added

- Hold the middle mouse button while scrolling over the constellation to zoom:
  wheel up zooms in, wheel down zooms out. Release middle to resume normal timeline
  scrolling. Existing zoom limits, overview behavior and browser zoom shortcuts are preserved.

No database migration or new environment settings are required.

## 1.0.1 — 2026-11-06

### Fixed

- Activity groups retain earlier follows and unfollows when the same person later
  likes a post or replies. Each person is counted once within each matching group.
- Grouped views include older saved records instead of only the newest page of
  activity. Constellation and Journal use the same saved-history range.
- Clicking an off-center star or name selects that person and keeps the selection
  until the timeline moves again. Pending scrolling no longer overrides the click.
- A person appearing in several activity groups has a separate, correct selection
  and event detail in each group.
- Background refresh waits for a full history load, preventing partial results
  from replacing the completed view. Rolling ranges remove expired records even
  when no new events arrive.

### Added

- A compact group range picker: **All saved** (the default), **24h**, **7d**,
  **30d** or **90d**. Grouped history reads use the local database without extra
  X profile requests; the ungrouped timeline keeps its existing pagination.

### Documentation

- Updated the history and grouping instructions to explain manual selection,
  saved-history ranges and people appearing in multiple groups.

No database migration or new environment settings are required.

## 1.0.0

First public release:

- Self-hosted X activity history with an offline demo and optional browser UI.
- Follows, unfollows and optional paid-subscription and interaction tracking.
- Constellation and journal views, audience groups and activity statistics.
- Saved person interactions and conversation threads, loaded from X only on request.
- Optional Follow/Unfollow actions, name lookups and open-page notifications.
- Persistent SQLite history, automatic user-token renewal and a headless Python API.
- Interactive install, update and uninstall for Docker or native Linux services.
- PyPI packages and local Docker Compose builds under Apache 2.0.
