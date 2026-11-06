# Changelog

Each tagged release has an automatically generated list of merged pull requests
and contributors on the [GitHub releases page](https://github.com/aatbit/xflog/releases).

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
