<h1><img src="src/xflog/assets/mark.svg" alt="" width="32" height="32"> XFlog</h1>

**X** **F**ollower **Log** is an open-source, self-hosted X activity tracker. Keep a live history of follows, unfollows, paid subscriptions, likes, replies, mentions, quotes and reposts.
Choose what to track, explore interactions by person, and load and save conversation threads when you need them.

[Watch the demo →](https://www.youtube.com/watch?v=7fqH6rcoUB4) · 70 seconds · sample data

It offers an alternative to the follower and engagement tracking features found in tools such as [Circleboom](https://circleboom.com/twitter-management-tool), [Fedica](https://fedica.com/twitter/who-unfollowed) and [SocialDog](https://social-dog.net/en/product/follower-management), with your history stored on your own machine.

Bring your own X API credentials. X API charges and any hosting costs still apply.

## X prerequisites

**The offline demo needs no X account, tokens or X API credits.** The installer requires the complete live setup below, including automatic token renewal. To get started, create an app in the [X Developer Console](https://console.x.com), check its [X Activity access](https://docs.x.com/x-api/activity/quickstart), and provide the settings below.

| Setting | What to enter |
| --- | --- |
| `X_APP_BEARER_TOKEN` | **Required.** Your developer app’s bearer token. |
| `X_USER_ACCESS_TOKEN` | **Required.** An OAuth 2.0 user access token for the account you want to track. |
| `X_USER_REFRESH_TOKEN` | **Required.** The refresh token returned with that access token. It lets XFlog renew access without asking you to sign in again. |
| `X_CLIENT_ID` | **Required.** The OAuth 2.0 Client ID of the app that issued your user tokens. |
| `X_CLIENT_SECRET` | **Required for a Web App, Automated App or Bot.** Use its OAuth Client Secret. Leave blank for a Native App. |
| `X_USER_ID` | **Leave blank to track yourself.** XFlog identifies the user token’s account at startup. Only enter a numeric account ID if you need to choose it explicitly. |

Use credentials from the **same developer app**, and keep the access/refresh tokens together as a pair. These credentials prepare XFlog to use the features you enable; they do not turn on paid options or start recording by themselves. X access, permissions, credits and the data X returns still determine what works.

**Responsible use:** track your own account, or one whose owner has given you permission. Do not use XFlog to stalk, harass or secretly profile people. Private activity requires that account owner’s authorization through X.

<details>
<summary>Get the user tokens and permissions</summary>

1. Enable **OAuth 2.0** in your app’s authentication settings in the Developer Console. Copy its **Client ID** and, for a Web App, Automated App or Bot, its **Client Secret**. These are different from the app’s API Key and API Secret.
2. Use a separate [OAuth 2.0 sign-in flow](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code) to sign in as the account you want to track and approve your app. XFlog does not provide this initial sign-in flow.
3. Request these permissions to cover all current XFlog features:

   ```text
   tweet.read users.read follows.read follows.write like.read offline.access
   ```

   `offline.access` is needed to receive a refresh token. `follows.write` allows the optional Follow/Unfollow feature; `like.read` is needed for likes. Granting them does not enable those features in XFlog—choose what to use in **Profile**. See [X’s permission guide](https://docs.x.com/fundamentals/authentication/guides/v2-authentication-mapping).
4. Save the returned **access token** and **refresh token** in the settings listed above. If an older token lacks a permission, approve the app again with the updated permissions; refreshing it does not add permissions.

The console’s **Access Token and Secret** pair is OAuth 1.0a. It is not the OAuth 2.0 access/refresh pair used here. Changing the app’s general Read/Write setting alone does not grant OAuth 2.0 permissions to an existing token.

</details>

<details>
<summary>Automatic renewal and reconnecting after an error</summary>

X user access tokens normally expire after about two hours. With the required refresh token and client settings, XFlog renews access when needed and saves the latest token pair privately in the history database. Docker and service restarts reuse that saved pair; `.env` is not rewritten.

Renewal does not start paused tracking, recover missed events or guarantee uninterrupted access. If X revokes access, rejects renewal, or renewal cannot be saved safely, XFlog shows an error and keeps your history. Approve the app again, replace **both user tokens** in `.env`, then [apply the environment changes](#environment-configuration).

- Keep the database and its backups private: they contain saved credentials as well as history.
- After deleting the database or restoring an older backup, obtain a fresh access/refresh pair before starting. An older refresh token may no longer work.
- Use each token pair with one renewing installation. Another installation renewing the same pair can invalidate it.
- **Profile** lists settings needed by the currently enabled features; it is not a complete renewal checklist. Check all the live-setup settings above even if Profile shows no missing settings.

</details>

<details>
<summary>Account identification and the user-id command</summary>

The user ID is the permanent number identifying an X profile. It stays the same if the person changes their `@handle`; it is not your developer app ID. An app bearer token identifies the app, so it cannot tell XFlog which person is “me.”

Leave `X_USER_ID` blank for automatic identification. At each startup XFlog makes one `GET /2/users/me` request using your user token. This can cost X credits even while tracking is paused. If it fails, tracking stays stopped and the error appears in the UI and logs; XFlog does not guess the account or rewrite `.env`.

Setting `X_USER_ID` skips that startup lookup. It must match the account that owns your user token; entering someone else’s ID does not authorize access to their private activity.

If you need to look up an ID manually, export your credentials and run:

```bash
xflog user-id @yourhandle  # Uses X_APP_BEARER_TOKEN
xflog user-id --me         # Uses X_USER_ACCESS_TOKEN
```

From a checkout, load `.env` explicitly:

```bash
uv run --no-sync --env-file .env xflog user-id @yourhandle
```

For a Docker Compose installation:

```bash
docker compose run --rm --no-deps xflog xflog user-id @yourhandle
```

Each command makes one user lookup, which can cost credits. It prints the ID without starting tracking or changing settings. Replace the handle with `--me` in either example to identify the supplied user token’s account. The command uses that access token as supplied; it does not renew it.

</details>

## Local installation

| Method | Install these first |
| --- | --- |
| **Docker** | Docker Engine, the Compose plugin and git; your user must be able to run Docker. |
| **Native Linux** | Bash, git, Python 3.12+ with virtual-environment support, and systemd user services. |

Run as your regular user, **without `sudo`**:

```bash
curl -fsSL https://raw.githubusercontent.com/aatbit/xflog/main/install.sh | bash
```

1. Choose **install**, then Docker or native Linux and a **new installation folder**.
2. Choose a port; press Enter for `7860`. For live use, enter the [required X credentials](#x-prerequisites). The installer asks for your access token, refresh token, Client ID and app type; Web App/Automated App/Bot clients must also supply their Client Secret. Leave the account ID blank to track yourself. For the demo, leave the app bearer blank—the other X questions are skipped.
3. Choose an optional browser password and confirm. The installer saves the credentials privately in `.env`; it won’t overwrite an existing installation.
4. Open `http://127.0.0.1:7860`, replacing `7860` if you chose another port. Choose **Explore the demo**, or **timeline settings → Workspace → Start tracking** to begin recording.

**Local use can be password-free:** press Enter at the password prompt. If you set one, use at least 16 English letters, numbers or symbols (ASCII); the browser username is **`xflog`**. This protects XFlog and is separate from your X password. Secrets are hidden while typing.

The same installer can **check for updates**, **update** or **uninstall**. History and settings are kept unless you explicitly choose to delete them.

<details>
<summary>Build and run with Docker Compose manually</summary>

Clone the repository and create your private settings file:

```bash
git clone https://github.com/aatbit/xflog.git
cd xflog
cp .env.example .env
chmod 600 .env
```

Edit `.env` using the [setup checklist](#x-prerequisites), then build and start XFlog:

```bash
docker compose up -d --build
```

Open `http://127.0.0.1:7860`. Leave X credentials blank for the offline demo. Compose builds the image on your machine, keeps history in a Docker volume and publishes the port only on localhost. No GHCR image or registry login is needed. Use `docker compose down` to stop; **do not add `-v` unless you want to delete history**.

</details>

<details>
<summary>Read the installer before running it</summary>

Download, inspect, then run:

```bash
curl -fsSL https://raw.githubusercontent.com/aatbit/xflog/main/install.sh -o install-xflog.sh
less install-xflog.sh
bash install-xflog.sh
```

</details>

<details>
<summary>Checking for updates, updating and uninstalling</summary>

Run the installer again and enter your existing installation folder.

- **Check for updates** (`check`) reports app and installer changes separately without changing your installation. Docker need not be running. It can offer to run the updated installer first; a script saved elsewhere stays untouched. If an app update is available, it prints the update command.
- **Update:** choose your install type and folder. Back up history first. Existing `.env` values, including blanks, and custom Docker network settings are kept; missing settings get defaults. Older installations are not prompted for new credentials during an update; add any missing renewal settings from the [setup checklist](#x-prerequisites) to `.env` and apply the changes. The installer asks before restarting and stops if you have edited the app’s source files.
- **Uninstall:** pause tracking in the UI first, then choose the same install type and folder. Files, settings and history remain by default. Deleting history or `.env` requires typing **`DELETE`** at a separate prompt for each. Shared networks and X tokens are left alone. **Update** can reactivate a retained installation.

Saved renewal tokens stay with the history database. Deleting only `.env` keeps that saved copy; revoke the app’s access in X if you want to disconnect permanently.

**Restarting can resume tracking if it was previously on.** Pause first if you want it to stay stopped.

</details>

<details>
<summary>Automatic startup, storage and advanced installer options</summary>

- **Docker** restarts XFlog with Docker unless explicitly stopped. Make sure Docker starts at boot. You can join an existing HTTPS-proxy network; XFlog also keeps its own private network.
- **Native Linux** creates a separate Python environment and `xflog.service` user service. Startup without logging in may need OS administrator approval. Python needs `venv`/`ensurepip`; the installer does not install system packages.
- Native history defaults to `~/.local/share/xflog/data/history.sqlite3`; Docker uses a persistent volume.
- Checks and updates use `main`. For another branch, tag or commit, download the script and run `XFLOG_REF=<ref> bash install-xflog.sh`. Checks compare file contents, not version numbers; an older source can also show differences. README-only changes do not count as app updates.
- `docker compose down` keeps history; **`docker compose down -v` deletes it**.
- Remove a stale `.xflog-maintenance.lock` only after checking that no updater or uninstaller is still running.

</details>

## Which features use X credits?

**Self-hosting does not remove X’s API fees.** Before live tracking, add credits, set a spending limit and check automatic top-ups in the [X Developer Console](https://console.x.com).

| Feature | X API cost |
| --- | --- |
| **Offline demo** | None; no X requests. |
| **Account discovery and `user-id` lookup** | One user read, which can be billed. With `X_USER_ID` blank, discovery runs once at every startup. |
| **Groups, filters, layouts, zoom, statistics and notifications** | No extra X requests or charges. Live events you record still follow X’s event pricing. |
| **Live follower tracking** | Follow and unfollow events are billed on X’s pay-per-use plan. |
| **Paid-subscription tracking** | New-subscription and expiry events are currently listed as **not billed**; [setup requirements](#x-prerequisites) still apply. |
| **Allow Follow/Unfollow** | Extra relationship checks and actions can be billed, even if you check someone without pressing Follow. |
| **Interaction history** | Off by default. $0.005 per delivered reply, mention, quote, repost or own-post event; $0.001 per like event. Turning on your posts also receives standalone posts. |
| **Thread loading** | Only on click: $0.005 per returned post, up to 100 per page. A missing conversation may need one extra post lookup. Account verification can add a user read. Saved copies reopen without X requests. |

Checked **4 November 2026** against [X’s event prices](https://docs.x.com/x-api/activity/event-pricing) and [API pricing](https://docs.x.com/x-api/getting-started/pricing). Prices can change. XFlog’s activity counts are **not a bill or spending limit**. Hosting costs are separate.

## Preferences and notifications

Open **Profile** with the person icon, change your choices, then **Save preferences**.

| Setting | Default | What it does |
| --- | --- | --- |
| **Follower events** | On | Records follows and unfollows. |
| **Paid subscription events** | Off | Records new subscribers and expirations. |
| **Activity notifications** | Off | Shows in-app notices and, with browser permission, browser alerts while the page is open. |
| **Allow Follow/Unfollow** | Off | Adds an action to person details and the selected-person readout when space allows. Adds API usage; Unfollow asks for confirmation. |
| **Resolve names & handles** | Off | Fills missing names once per person through X user lookups, then saves them. Extra X charges can apply. |
| **Interaction history** | Off | Choose replies, mentions, quotes, reposts, likes received, your likes or your posts and replies. Each choice shows its X event price. |

**Saving does not pause recording or restart paused tracking.** To stop everything, use **timeline settings → Workspace → Pause tracking** before turning all event options off. To resume, enable at least one event option, save, then choose **Start tracking**.

<details>
<summary>Saved interactions and thread updates</summary>

Open a person’s details, then **Interaction history**. XFlog saves new interactions in its database while tracking runs; it cannot recover earlier interactions. The choices cover your account’s activity, including people outside your follower log. Outgoing replies and quotes can be linked to someone only when X supplies their ID or the referenced post.

Threads stay unloaded until you press **Load thread · X reads**. XFlog saves a dated copy; reopening it uses the database. **Load more** requests another page and **Refresh** checks X again. These requests need X search access and credits; a thread can contain other participants’ posts and may be incomplete.

Enabled interactions also appear in the constellation and journal, including people with no recorded follow event. The open app checks its local database every 10 seconds and updates the timeline and open interaction history automatically. New posts received by tracking are added to matching saved threads without another X request. Full threads are still loaded only when you ask: unseen replies, edits or deletions need a new X read. Cached posts remain when tracking is turned off and can be outdated.

**Resolve names & handles** in Profile is optional and off by default. Enable it to fill missing display names and `@handles` using X user lookups. X can charge per profile, even when several IDs share one request. XFlog checks each new person once, saves the result in SQLite and reuses it across the constellation, journal and HUD. It requests only identity fields, not extra grouping data. Profiles supplied with events are reused first, without a lookup. To retry unavailable profiles, switch this option off and on again; successful cached profiles are kept. Names are not checked repeatedly for changes, but later event-supplied profiles can update them.

</details>

<details>
<summary>Notifications and saving problems</summary>

Your browser may ask for notification permission when you save. Alerts need localhost or HTTPS and permission in each browser/device. If blocked or unsupported, in-app notices still work. Neither works after the page is closed. Changing only notifications does not change the events requested from X.

If saving shows a warning, follow it before assuming your change is active. If choices were saved but could not be applied on X, fix the access or disk problem and save again. If they could not be saved, make your choices again after fixing the problem.

</details>

## Exploring your history

Open timeline settings with the **sliders icon**. Choose Followers or Paid subscribers, filter All/Gained/Lost, or switch between **Constellation** (one star per recorded action) and **Journal** (every recorded event). These viewing choices do not change what you record.

XFlog loads the newest activity first. Scroll toward the older edge or choose **Load older activity** to bring in another page. Both layouts show how many events and people are loaded alongside the totals for the selected filters and time range.

Each star represents one recorded action. Repeated actions from the same person stay as separate entries; new activity does not replace an earlier action. In Constellation, scroll up for older history and down for newer history. The person nearest the center becomes highlighted as you move, and their details appear in the readout. You can also click any visible star or name to select and center that person; they stay selected until you move through history again. Click the selected person or their readout for details. Interaction details include a linked post excerpt of up to 280 characters when text is already saved; no extra X request is made. The side arrows move one recorded action at a time. Use the bottom sliders to move through history or change zoom, which starts at **80%**. You can also hold the middle mouse button and scroll up to zoom in, or down to zoom out. Journal uses normal vertical scrolling and hides the sliders.

<details>
<summary>Motion, statistics and connection history</summary>

- **Ambient motion** controls light trails and shooting stars; **Motion speed** ranges from **0.25× to 2×**. Neither changes recording speed. Your device’s reduced-motion setting is respected.
- The **clock buttons** share one range: **1h, 6h, 12h, 24h, 3d, 7d, 30d, 90d or All saved**. Changing either updates the timeline, Journal and readings. They start at **24h**. Hover or keyboard-focus a reading’s label for help. Paid-subscriber readings show new subscribers and expirations.
- **Growth ratio** is gains divided by losses: 7 follows and 2 unfollows gives **3.5**. A dash means no ratio can be calculated, such as when there are no losses.
- Changes compare the previous equal-length period. Green means more gains or fewer losses; red means the reverse. **New** means the previous period had no activity.
- Readings use the full saved log and the time XFlog received events, regardless of zoom, filters or groups. They are recorded changes, not your current follower total.
- The timeline updates automatically from saved records; notification settings do not control these updates. Your zoom and selected person are preserved. Follow/unfollow readings count only audience changes, not interactions. **Workspace → Connection history** shows interruptions; earlier activity and events missed during gaps cannot be reconstructed. **Explore demo** uses sample data.

</details>

## Audience groups

Open **timeline settings → Audience Groups** to enable groups, then choose one with the **spyglass button**. Switches save automatically without pausing tracking. **Activity** is enabled by default, but the picker starts on **Ungrouped**; other groups start off.

Each constellation has its own colored connections and a separate section when zoomed in. The small hint at the top names the current constellation. Groups keep their order and colors as you zoom; **Ungrouped** returns to the normal timeline.

Use either **clock button** to change the shared time range for Constellation, Journal and readings. **All saved** includes older records already in XFlog’s database; it does not fetch past activity from X. In this view, the HUD shows lifetime totals and growth ratio; hourly rates and comparisons stay blank.

**Groups make no extra X requests or charges.** Missing details stay **Unknown**; XFlog does not look up profiles to fill them in.

<details>
<summary>Available groups and what they mean</summary>

| Group | What it shows |
| --- | --- |
| **Activity** | Follows, unfollows, new subscriptions or expirations, plus enabled interactions such as replies and likes. |
| **Previous encounters** | First appearance in this log, seen before, or followed again after a recorded unfollow. Uses the full saved history, including older records. |
| **Account size** | Under 100, 100–999, 1K–9,999 or 10K+ followers, when supplied. |
| **Account age** | Under 1 year, 1–3 years or 3+ years old when the event was recorded. |
| **Verification** | Verified/unverified and blue, business or government badge types when supplied. |
| **Profile location** | Similar location text, tidied for spacing, capitalization and clear aliases such as NYC → New York City and Bangalore → Bengaluru. |

Zoom out to see all groups with saved events in Constellation. With the **Activity** lens, click a group to show its loaded events immediately and fetch its first saved page from the local database. **Load older activity** continues within that group and time range. Use **All groups** to return to the same overview with your loaded pages, zoom, and position restored. In other lenses, a group marked **0 loaded** becomes selectable after you load a page containing one of its events. On smaller screens, scroll sideways or use the history slider to reach groups that do not fit. Journal uses collapsible sections and shows a summary for groups whose events have yet to load. A person can appear in several groups. Group badges and legend counts show total actions within the selected range. Hover over a group badge or legend count for the number of unique people. Each loaded action has its own star.

Account size, age, verification and location use only details delivered with new events while enabled. Old missing details stay Unknown; turning a group off keeps saved history. Profile facts describe the recorded event, not a live profile check. When space allows, enabled Verification, Account size and Account age add facts to the selected-person readout. Known verified accounts get a checkmark beside their name in Constellation and the readout when Verification is enabled.

**First appearance** does not mean first on X. **Followed again** needs a recorded unfollow followed by a follow; gaps can hide that sequence. Location is profile text, not a verified address: London, UK and London, Ontario stay separate. Missing or unusable labels stay Unknown; XFlog does not guess where someone lives.

</details>

<details>
<summary>How optional Follow/Unfollow checks work</summary>

Enable **Allow Follow/Unfollow** in Profile and save only if you want the extra API usage. XFlog verifies the token’s account, checks the selected person when an action button can be shown, and checks again before an action. While scrolling, the highlight and readout update locally; the relationship check waits until movement settles. XFlog does not download your following list or poll relationships in the background. Recent checks are kept in a small temporary cache, so returning to someone is fast. Selecting someone after five minutes can refresh the check without hiding the last result. A slow check times out with a Retry button; it does not pause tracking.

**Retry** only checks the relationship; a failed write is not automatically repeated. Pending requests and blocked accounts must be managed on X. The offline demo cannot perform actions.

Turn the option off and save to stop further checks/actions; an action already sent may still complete. Following someone does not add an incoming follower event to your log.

</details>

## Environment configuration

The installer saves credentials in `.env` in your installation folder; **keep it private**. For manual Python runs, set environment variables before starting XFlog. **Profile** lists missing settings and shows the `.env` path when provided; token values are never shown.

<details>
<summary>Apply changes to .env</summary>

For Docker, run from the installation folder:

```bash
docker compose up -d --force-recreate
```

This keeps history and loads the new values. **`docker compose restart` does not load changed environment settings.**

For an installer-managed native service, run as its owner:

```bash
systemctl --user restart xflog.service
```

For manual Python runs, stop and relaunch with the updated environment. Restarting can resume tracking if it was previously on.

</details>

<details>
<summary>Ports, storage and advanced environment settings</summary>

| Setting | Purpose |
| --- | --- |
| `XFLOG_ADMIN_PASSWORD` | Browser password. See [password rules](#local-installation); remote access requires one. |
| `XFLOG_ORIGIN` | The exact browser address; defaults to `http://127.0.0.1:7860`. Remote access needs HTTPS, with no trailing slash or extra path. |
| `XFLOG_PUBLISH_PORT` | Docker’s local published port, default `7860`. Update the origin if you open a different port directly. |
| `XFLOG_HOST`, `XFLOG_PORT` | Native bind address/port, default `127.0.0.1:7860`. Docker listens internally on `0.0.0.0:7860`, with its published port restricted to localhost. |
| `XFLOG_DATABASE` | SQLite history path. Docker defaults to `/data/history.sqlite3`; keep it under `/data` to retain history across container replacement. |
| `XFLOG_ENV_FILE` | The host configuration-file path shown in Profile; the installer fills it in. This only displays the path; it does not load the file. |
| `XFLOG_LOOPBACK_PUBLISHED` | Supplied Compose sets `1` for its localhost-only published port. Other container setups may set it only with the same restriction. Native localhost runs do not need it. |

Without `XFLOG_ENV_FILE`, Profile says no path was provided. Follow the complete [live-setup checklist](#x-prerequisites); Profile’s missing-settings list does not check every renewal setting.

The installer gives `.env` owner-only permissions (`0600`), but it is not encrypted; administrators can read it.

</details>

## Hosting remotely and using HTTPS

For another device or a VPS, use your own domain, an HTTPS proxy and a browser password. **Keep XFlog’s HTTP port private.** The installer can join an existing Docker network but does not set up a domain, proxy or certificates.

<details>
<summary>Step-by-step remote setup with Caddy</summary>

This example runs Caddy directly on the same server as XFlog. Caddy handles HTTPS and forwards visitors to XFlog’s private local port.

**1. Point your domain at the server**

Add an **A record** such as `xf` pointing to the server’s public IPv4 address. An optional **AAAA record** must reach the same server over IPv6. Allow ports **80 and 443** through both server and hosting-provider firewalls; keep port **7860 private**. Caddy obtains and renews the certificate when DNS and these ports are ready. See [Caddy’s HTTPS guide](https://caddyserver.com/docs/quick-starts/https).

**2. Set the public address and password in .env**

```dotenv
XFLOG_ORIGIN=https://xf.example.com
XFLOG_ADMIN_PASSWORD="replace-with-your-own-long-password"
```

Use your own domain and a password following the [password rules](#local-installation). Follow the address rules and [apply the .env changes](#environment-configuration).

**3. Set up Caddy**

[Install Caddy for your Linux distribution](https://caddyserver.com/docs/install). With its standard Linux service, add this block to `/etc/caddy/Caddyfile`, keeping existing sites:

```caddyfile
xf.example.com {
    reverse_proxy 127.0.0.1:7860
}
```

Use your domain and replace `7860` if you chose another local port. Validate and load it:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
```

These commands assume Caddy’s standard Linux service; see its [service guide](https://caddyserver.com/docs/running) for other setups.

**4. Open your HTTPS address**

Visit your domain and enter username **`xflog`** and the password from `.env`. No X sign-in callback URL is needed.

</details>

<details>
<summary>Docker proxy or connection problems</summary>

- **Proxy in Docker:** join the same trusted network and forward to **`http://xflog:7860`**; Caddy uses `reverse_proxy xflog:7860`. In a container, `127.0.0.1` means the proxy itself. Keep XFlog private and use the same public origin/password. See [Caddy’s Docker guide](https://caddyserver.com/docs/running#docker-compose).
- **Site/HTTPS won’t open:** check DNS, ports 80/443 and whether another web server is using them.
- **502 Bad Gateway:** check XFlog is running and the proxy address/port matches. For Docker, run `docker compose ps` and `docker compose logs --tail=50 xflog` from its installation folder.
- **Login/settings fail:** use the exact address in `XFLOG_ORIGIN`. A different proxy must preserve the original `Host` and `Authorization` headers.

</details>


## Use it in your own applications

Use XFlog as a Python library without installing the browser interface. Python **3.12+** is required. Install the package from PyPI:

```bash
python -m pip install xflog
# Or, add it to a uv project:
uv add xflog
```

The base package installs only the tracking and storage dependencies. In an existing Python environment, `uv pip install xflog` works too.

For the browser app, install **`xflog[ui]`** instead, then run **`xflog`** (or `uv run xflog` in a uv project). Set your [environment settings](#environment-configuration) before running it; a plain Python launch does not load `.env` automatically. Docker and the interactive installer include the UI automatically. Installing the package does not create an OS service.

<details>
<summary>Upgrades and installing from source</summary>

Use `python -m pip install --upgrade xflog` or `uv lock --upgrade-package xflog` followed by `uv sync`. Keep the `[ui]` extra in your pip command if you use the browser app. Stop XFlog and back up history before upgrading, then restart it with the same settings.

For unreleased development code, use `python -m pip install "xflog @ git+https://github.com/aatbit/xflog.git@main"`. Prefer a released version for normal use.

</details>

<details>
<summary>Use XFlog from another application</summary>

`CoreConfig` needs only a database path and your X settings. It ignores browser origin, port and password settings. Supply values directly or use `CoreConfig.from_env()`; this reads the process environment, **not an `.env` file**.

```python
import asyncio
from xflog import CoreConfig, Runtime

async def main():
    async with Runtime(CoreConfig.from_env()) as xf:
        page = await xf.store.history(xf.config.user_id, {"limit": 25})
        for event in page["events"]:
            print(event["name"], event["kind"])

asyncio.run(main())
```

**A fresh database leaves tracking paused.** With the live credentials configured and `user_id` blank, entering the context first makes one X user read to identify the user token’s account. The resolved ID is available as `xf.config.user_id`; the input configuration and `.env` stay unchanged. An existing database keeps its saved Start/Pause choice: entering the context can resume collection. Closing cancels local work and closes the database and HTTP client; it does not pause future starts or remove X subscriptions. Use `await xf.collector.stop()` to pause explicitly. The [same feature costs](#which-features-use-x-credits) apply to library callers.

Create a fresh `Runtime` for each context; instances are single-use. Both library and browser entry points reject a second runtime for the same database or app token. These are host-local locks for the same OS user. Containers or separate machines need shared ownership coordination; they must not independently consume the same developer app's stream. For automatic renewal, use the [complete live setup](#x-prerequisites). `CoreConfig.from_env()` reads these settings; direct configuration uses `user_refresh_token`, `client_id` and, for a confidential OAuth client, `client_secret`. Library callers may omit renewal settings and supply fresh access tokens themselves. Private features still need a user token with the right permissions; the installer’s stricter requirements do not change the library API.

The context returns `Runtime`. These services are available **inside** it:

| Call | Return value |
| --- | --- |
| `await xf.store.history(account_id, query)` | `dict`: `events` is a list of event dictionaries; `next` is an integer cursor or `None`. Query keys: `kind` (`all`, `gained`, `lost`), `subject` (`followers`, `subscriptions`), `before` (cursor) and `limit` (1–50). |
| `await xf.store.summary(account_id)` | `dict[str, int]`: counts keyed by event type. Local reads only. |
| `await xf.collector.save_preferences(selection)` | `dict`: `saved: bool`, `message: str`. Supply `followers`, `subscriptions`, `notifications` booleans, plus optional `interactions` choices. Preserves running/paused state; a saved change may still have a warning. |
| `await xf.collector.start()` / `stop()` | `None`. Start requests background collection; inspect `xf.collector.state` and `message` for connection/failure status. Stop pauses and attempts subscription cleanup. |
| `await xf.follow_actions.configure(enabled)` | `None`. Opt-in only; requires the user token when enabling. |
| `await xf.follow_actions.relationship(event_id)` / `change(event_id, following)` | `dict`: `following`, `pending`, `blocked` booleans. These can make X requests; use an event ID from the account's saved history. |
| `await xf.interactions.history(event_id, before=0)` | `dict`: `interactions` list and `next` integer cursor or `None`. Saved data only. |
| `await xf.interactions.thread(event_id, options)` | `dict`: `posts` list, `total` and `offset` integers, `more_saved: bool`, `conversation_id` and `checked_at` strings, and `more_available` / `fetched` booleans. |

For threads, import `ThreadOptions` from `xflog`. Its required `sequence` comes from a saved interaction. `action="cached"` reads locally; `"open"` uses the saved copy if available, otherwise requires `accepted_costs=True` before X reads. `"refresh"` and `"more"` also need that consent and the current `checked_at` value, so stale requests cannot repeat a paid refresh. `offset` pages through saved posts. Interaction tracking must be enabled before loading from X.

Handle these errors at your application's boundary:

- `ValueError`: invalid configuration or `ThreadOptions` values.
- `RuntimeBusyError` (a `SetupError`): another runtime owns the app or database; it has not been started or displaced.
- `RuntimeError`: a `Runtime` was entered more than once.
- `SetupError`: missing access, invalid saved state, disabled feature or missing thread-read consent. Its message explains the problem.
- `ProviderError`: rejected X requests in the transport layer; `status` is the HTTP status and `delay` the bounded retry delay in seconds. Feature services can translate these to `SetupError`.
- `httpx.HTTPError`, `sqlite3.Error` or `OSError`: network or local storage failure. Cleanup still runs when context entry or the body fails, including cancellation. Background collection reports its failures through `state` and `message`.

`CoreConfig`, `Runtime`, `ThreadOptions`, `SetupError`, `RuntimeBusyError` and `ProviderError` are exported from `xflog`. Lower-level modules remain grouped by feature:

- `xflog.tracking`: X transport, event parsing, collection and follow actions.
- `xflog.history`: saved events, statistics, filters and demo data.
- `xflog.interactions`: interaction parsing, saved conversations and thread loading.
- `xflog.audience_groups`: the existing grouping registry.
- `xflog.web`: HTTP request models and browser mounting.

`xflog.app.create_app` remains the self-hosted entry point, using `xflog.config.Config` for its additional browser settings. Its runtime is available as `app.state.runtime`; `Runtime.lifespan(app)` is the ASGI adapter for the same async context.

To run the full development suite from a checkout, use `uv sync --extra ui --extra dev` then `uv run --no-sync pytest`. To check the SDK without web packages, create a separate environment, install the base package plus `pytest` and `pytest-asyncio`, then run `python -m pytest tests/test_runtime.py tests/test_identity.py tests/test_cli.py`. No tests make live X requests.

</details>

## Releases and contributing

Pull requests to `main` and updates on `main` run lint, formatting and the mock-data tests on Python 3.12–3.14. No X credentials are needed. See the [changelog](CHANGELOG.md) and [release notes](https://github.com/aatbit/xflog/releases) for published changes.

<details>
<summary>How maintainers publish a release</summary>

1. Update the version in `pyproject.toml`, add its entry to `CHANGELOG.md` and run `uv lock`. Merge the passing release PR into `main`.
2. Tag that commit, for example `git tag v1.0.1`, then `git push origin v1.0.1`.
3. Actions repeats the checks and verifies the tag matches the package version and belongs to `main`. It builds and checks the Python packages, publishes them to PyPI, then creates a GitHub release with package downloads, the version’s changelog and automatically generated change notes. Docker users build locally with Compose; releases do not publish a container image.

PyPI uses Trusted Publishing from this repository’s `release.yml` workflow and `pypi` environment; no long-lived PyPI token is stored in GitHub. Actions are pinned to full commit hashes, with Dependabot checking for updates. If a job fails, inspect it and rerun the failed jobs; do not reuse a published version for different files. Changing a version tag does not replace files already published to PyPI.

</details>

## License

XFlog is licensed under [Apache 2.0](LICENSE). Bundled IBM Plex fonts keep their [SIL Open Font License](src/xflog/assets/FONT-LICENSE.txt).
