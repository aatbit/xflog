# XFlog

> See who follows, unfollows, or lets their paid subscription expire on X.

**X** **F**ollower **Log** is a small, self-hosted tracker that logs follower and paid-subscription activity through X’s official Activity API.
The current X UI shows unfollow metrics but does not have a direct way to view users who have unfollowed you or unsubscribed.
**XFlog** shows you these events as they arrive in a live timeline, with profile links and your history stored locally.

> [!NOTE]
> It doesn’t reconstruct past activity. Live tracking requires X API credits.

## X prerequisites

**You can try the demo without an X developer account, tokens or API charges.** To track a real account, you’ll need an X developer app and the following settings:

| Setting | What you need |
| --- | --- |
| `X_APP_BEARER_TOKEN` | Your developer app’s bearer token. Required for live tracking. |
| `X_USER_ID` | The account’s numeric ID, not its `@handle`. Required for live tracking. |
| `X_USER_ACCESS_TOKEN` | The account’s permission to use your app. **Required for paid subscriptions or Follow/Unfollow; optional for follower tracking alone.** |

1. **Create a developer app** in the [X Developer Console](https://console.x.com). Check that it can use [X Activity](https://docs.x.com/x-api/activity/quickstart).
2. **Get your app’s bearer token and the account’s numeric ID.** X’s quickstart explains how to look up the ID.
3. **Add API credits and check your spending limit.** Also check whether automatic credit top-ups are enabled.
4. **Enter the settings in the installer or `.env`.** For paid-subscription tracking or Follow/Unfollow, get a user access token too; the details are below.

**X charges for live API usage, even when XFlog runs on your own computer.** Check [Activity prices](https://docs.x.com/x-api/activity/event-pricing) and [X’s spending rules](https://docs.x.com/x-api/getting-started/pricing) before starting. XFlog’s event count does not cap your X bill.

Followers are on by default. Paid-subscription tracking stays off until you enable it in Profile. Choose **Start tracking** when you’re ready. To use the demo instead, leave the X settings blank.

<details>
<summary>Getting a user access token</summary>

Use a separate [OAuth 2.0 sign-in flow](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code) to give your app permission to access the account. Save the access token it returns as `X_USER_ACCESS_TOKEN`.

For paid-subscription tracking, request `follows.read`. To use Follow/Unfollow too, also request `tweet.read`, `users.read` and `follows.write`. If you already have a read-only token, approve the app again with these added permissions.

Both tokens must belong to the same developer app, and the user token must belong to the account in `X_USER_ID`. XFlog does not include this sign-in step or renew tokens for you. You can leave the user token blank for follower tracking alone. Paid-subscription tracking and Follow/Unfollow need it.

</details>

## Local installation

Choose how you want to run XFlog:

| Method | Install these first |
| --- | --- |
| **Docker** | Docker Engine, the Compose plugin and git. Your user must be able to run Docker. |
| **Native Linux** | Bash, git, Python 3.12+ with virtual-environment support, and systemd user services. |

Run the installer in a terminal as your regular user, **without `sudo`**:

```bash
curl -fsSL https://raw.githubusercontent.com/aatbit/xflog/main/install.sh | bash
```

Choose **install**, then follow the prompts for Docker or native Linux, a new installation folder, port, X settings and an optional browser password. The port is the number at the end of your local XFlog address; press Enter to use `7860`. Review the choices before confirming. The installer won’t overwrite an existing installation.

**For local use, press Enter at the password prompt to leave protection off.** If you set a password, use at least 16 ASCII characters; the browser username is `xflog`. This password protects XFlog and is separate from your X account.

Open `http://127.0.0.1:7860` when installation finishes, or replace `7860` with the port you chose. Tokens and passwords are hidden while you type and saved in `.env`; keep that file private.

<details>
<summary>Read the installer before running it</summary>

Download it, inspect it, then run it:

```bash
curl -fsSL https://raw.githubusercontent.com/aatbit/xflog/main/install.sh -o install-xflog.sh
less install-xflog.sh
bash install-xflog.sh
```

</details>

<details>
<summary>Startup, storage and Docker network details</summary>

- **Docker:** XFlog restarts with Docker unless you explicitly stop it. Make sure Docker itself starts at boot. You can optionally join an existing network for your HTTPS proxy; XFlog also keeps its own private network.
- **Native Linux:** the installer creates a separate Python environment and a user service named `xflog.service`. It allows that service to run at boot without you logging in; your OS may ask for administrator approval for this step. Python needs `venv`/`ensurepip` support; the installer does not install system packages for you.
- Native installer history defaults to `~/.local/share/xflog/data/history.sqlite3`. Docker keeps history in a persistent volume.
- The installer saves `.env` with owner-only permissions (`0600`). It is a plain-text file, not encrypted; administrators can still read it.

</details>

By default, XFlog is only accessible on the computer where you install it. To use it from another device, follow [the remote hosting guide](#hosting-remotely-and-using-https). You’ll need to set up your own domain and HTTPS proxy.

Leave the X credentials blank to try the demo without X API calls or charges. A new installation waits for you to choose **Start tracking**.

**Checking for updates**

Run the installer, choose **check for updates** (type `check`), and enter your XFlog installation folder. You’ll see separately whether the **XFlog app** or the **Installer** has changed. Checking does not change your app, settings or history, and Docker does not need to be running.

If the installer has changed, it offers to open the updated installer first. A script you saved elsewhere stays untouched. If an app update is available, it shows the command to run; choose **update** from the menu. Nothing is updated without your confirmation.

**Updating**

Run the installer again, choose **update**, then select your install type and existing installation folder.

- Back up your history first.
- Your history, `.env` settings and custom Docker network settings are kept. New settings get their default values; existing values, including blanks, stay unchanged.
- The installer asks before restarting XFlog. If you have changed the app’s source files, it stops so your edits aren’t overwritten.

**Uninstalling**

Pause tracking in the app first. Then run the installer, choose **uninstall**, and select the same install type and folder.

XFlog stops running, but your files, settings and history are kept by default. Deleting history or `.env` requires typing **`DELETE`** at a separate prompt for each. Your shared Docker networks and X tokens are left alone. To run the retained installation again, choose **update**.

**Restarting an existing installation can resume tracking if it was previously on.** Pause first if you want it to stay stopped.

<details>
<summary>Advanced options and troubleshooting</summary>

- Checks and updates use `main` by default. To use another branch, tag or commit, download the script and run `XFLOG_REF=<ref> bash install-xflog.sh`. Checks compare file contents against that source, not version numbers; a deliberately older source can also show different files. README-only changes do not count as app updates.
- After editing `.env`, run `docker compose up -d --force-recreate` for Docker, or restart the native service.
- `docker compose down` keeps history; **`docker compose down -v` deletes it**.
- If an interrupted update leaves `.xflog-maintenance.lock`, check that no updater or uninstaller is running before removing it.

</details>

## Hosting remotely and using HTTPS

Want to open XFlog from another device or run it on a VPS? Give it an address such as `https://xf.example.com`. HTTPS encrypts the connection, including your browser password.

The example below uses **Caddy installed directly on the same server as XFlog**. Caddy provides the secure public address and forwards visitors to XFlog, which stays on a private local address. If you already use another HTTPS proxy, you can keep using it.

**1. Point a domain at your server**

In your domain provider’s DNS settings, add an **A record** for your chosen name (for example, `xf`) pointing to your server’s public IPv4 address. If you add an **AAAA record** for IPv6, make sure that address reaches the same server too.

Allow incoming connections on ports **80 and 443** in your server and hosting-provider firewalls. Keep XFlog’s port **7860 private**. Caddy can obtain and renew the HTTPS certificate automatically once the domain points to your server and these ports are reachable. See [Caddy’s HTTPS setup guide](https://caddyserver.com/docs/quick-starts/https).

**2. Set your address and password**

Open `.env` in your XFlog installation folder and set:

```dotenv
XFLOG_ORIGIN=https://xf.example.com
XFLOG_ADMIN_PASSWORD="replace-with-your-own-long-password"
```

Replace the example domain and password with your own. Use the full `https://` address, with no `/` at the end or extra path such as `/xflog`. A password is required for remote access; use at least 16 ASCII characters (ordinary English letters, numbers and symbols).

**3. Apply the changes to XFlog**

For Docker, run this from your XFlog installation folder:

```bash
docker compose up -d --force-recreate
```

This keeps your history and loads the new `.env` values. A plain `docker compose restart` does **not** load changed environment settings.

For a native installation made with the installer, run as the user who installed XFlog:

```bash
systemctl --user restart xflog.service
```

For a manual Python run, stop and relaunch it with the updated environment settings.

**4. Set up Caddy**

[Install Caddy using the instructions for your Linux distribution](https://caddyserver.com/docs/install). With its standard Linux service installation, edit `/etc/caddy/Caddyfile` and add this block. Keep any existing sites in that file.

```caddyfile
xf.example.com {
    reverse_proxy 127.0.0.1:7860
}
```

Use the same domain you put in `.env`. If you chose a different local XFlog port, replace `7860` with that port.

Check the file, start Caddy at boot, and load the configuration:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
```

These commands are for Caddy’s standard Linux installation. See [Caddy’s service guide](https://caddyserver.com/docs/running) if your installation uses a different setup.

**5. Open XFlog**

Visit `https://xf.example.com` using your own domain. When the browser asks, enter username **`xflog`** and the password you saved in `.env`. No X sign-in callback URL is needed.

<details>
<summary>Already running your proxy in Docker?</summary>

Join XFlog and your proxy to the same trusted Docker network. The installer can attach XFlog to an existing network; it does not install the proxy for you. In the proxy’s settings, forward your domain to **`http://xflog:7860`**. For Caddy, use `reverse_proxy xflog:7860`.

Inside a proxy container, `127.0.0.1` means that container itself, so use `xflog:7860` to reach XFlog. Keep the XFlog port private, and set the same public address and password in `.env` as above. [Caddy’s Docker guide](https://caddyserver.com/docs/running#docker-compose) explains container-to-container routing.

</details>

<details>
<summary>If something doesn’t work</summary>

- **The site won’t open or HTTPS fails:** check that your DNS points to this server, ports 80 and 443 reach Caddy, and another web server isn’t already using those ports.
- **Caddy shows “502 Bad Gateway”:** XFlog may be stopped, or the local address/port in the Caddyfile may be wrong. For Docker, check `docker compose ps` and `docker compose logs --tail=50 xflog` from the installation folder.
- **Login or settings requests fail:** open the exact HTTPS address set in `XFLOG_ORIGIN`. If you use a different proxy, make sure it passes through the original `Host` and `Authorization` headers.
- **An X token expires or is revoked:** obtain a replacement outside XFlog, update `.env`, then recreate the container or restart the native service as shown above. XFlog does not refresh X tokens for you.

</details>

## Environment configuration

The installer saves settings in `.env` inside your installation folder. If you run Python manually, set the environment variables before starting XFlog. After changing these settings, [apply them by restarting XFlog as shown in the hosting guide](#hosting-remotely-and-using-https).

These are the settings most people need:

| Setting | What it does |
| --- | --- |
| `X_APP_BEARER_TOKEN` | Your app’s X token. Required for live tracking. |
| `X_USER_ID` | The numeric ID of the X account to track. |
| `X_USER_ACCESS_TOKEN` | Required for paid subscriptions and optional Follow/Unfollow actions. Follower tracking alone does not need it. Get and refresh it outside XFlog. |
| `XFLOG_ADMIN_PASSWORD` | Leave blank for local access without a password. Required for remote access; browser username is `xflog`. |
| `XFLOG_ORIGIN` | The address you open in your browser. Defaults to `http://127.0.0.1:7860`; use your HTTPS address for remote access. |

**Not sure what’s missing?** Open Profile. It lists missing settings by name and shows the `.env` path when the installer or launcher provides it. Token values are never shown. Add the missing values, then restart as described above.

<details>
<summary>Ports, storage and other advanced settings</summary>

| Setting | When to change it |
| --- | --- |
| `XFLOG_PUBLISH_PORT` | Change the Docker port on your computer; default `7860`. Update `XFLOG_ORIGIN` too if you open that port directly. |
| `XFLOG_HOST`, `XFLOG_PORT` | Native server address and port; defaults `127.0.0.1:7860`. Docker listens on `0.0.0.0:7860` inside its container, while the supplied Compose file keeps the published port local. |
| `XFLOG_DATABASE` | Change where SQLite history is stored. Docker defaults to `/data/history.sqlite3`; keep it under `/data` so it survives container replacement. |
| `XFLOG_ENV_FILE` | Tell Profile which configuration-file path to show. The installer fills this in. For Docker, use the host path. This setting only displays the path; it does not load the file. |
| `XFLOG_LOOPBACK_PUBLISHED` | The supplied Compose file sets this to `1` because its port is published only on `127.0.0.1`. Other container setups may set it only when they also restrict access to localhost. Native localhost runs do not need it. |

If `XFLOG_ENV_FILE` is not set, Profile says that no file path was provided. Its missing-settings list asks for `X_USER_ACCESS_TOKEN` when paid-subscription tracking is selected. Follow/Unfollow also needs this token; its switch stays unavailable until the account ID and user token are set.

</details>

## Preferences and notifications

Open **Profile** using the person icon near the top right. Choose what you want XFlog to do, then select **Save preferences**.

| Setting | Starts | What it does |
| --- | --- | --- |
| **Follower events** | On | Records when someone follows or unfollows you. |
| **Paid subscription events** | Off | Records new paid subscribers and expired subscriptions. Needs a user access token. |
| **Activity notifications** | Off | Shows a notice when new events arrive. Can also show a browser alert while XFlog is open. |
| **Allow Follow/Unfollow** | Off | Adds a Follow/Unfollow button to a person’s details and, when there is room, their readout below the stars. Needs a user access token with permission to follow accounts. Unfollow asks you to confirm. |

**Saving does not pause tracking.** If XFlog is already recording, it keeps recording with your new choices. If you paused it earlier, saving does not start it again. To stop recording everything, choose **Pause tracking** in timeline settings under **Workspace** before turning both tracking options off.

To record again, enable at least one tracking option, save, then choose **Start tracking** under **Workspace**.

When you enable **Activity notifications** and save, your browser may ask whether to allow alerts. If you decline, or your browser cannot show them, notices inside XFlog still work. Keep the page open to receive either type of notice.

Follow/Unfollow makes extra X requests and can add charges, including when it checks whether you already follow someone. Leave it off if you only want to record your audience’s activity. See [which features use X credits](#which-features-use-x-credits) below.

<details>
<summary>If a change or notification doesn’t work</summary>

- **A warning after saving:** read the message before assuming the change is active. If XFlog saved your choices but could not apply them on X, fix the access or disk problem shown, then save again. If it says the choices could not be saved, make your choices again after fixing the problem.
- **No browser alerts:** allow notifications in your browser’s settings for the XFlog address. Browser alerts work on localhost or an HTTPS address. Each browser and device needs its own permission.
- **Alerts stop after closing XFlog:** that is expected. XFlog does not send alerts to a closed page.
- **Only changing notifications:** this does not change which events XFlog asks X to send.

</details>

## Exploring your history

The **sliders icon** near the top right opens timeline settings. The viewing options below change how you explore your saved history without changing what you record.

| Control | How to use it |
| --- | --- |
| **Audience** | Switch between **Followers** and **Paid subscribers**. Choosing a view does not start recording that activity; use Profile for that. |
| **Events** | Choose **All events**, **Gained** or **Lost** to narrow the view. Your other records stay saved. |
| **Layout** | Choose **Constellation** for one star per person, or **Journal** to read each recorded event in a list. |
| **Ambient motion** | Turn the moving light trails and occasional shooting stars on or off. Your device’s reduced-motion setting is respected. |
| **Motion speed** | Slow down or speed up the animation, from **0.25× to 2×**. This does not change how quickly XFlog receives events. |

In the constellation, select a star to choose a person, then select their name or the readout below to open the event details. The side arrows move one person older or newer. Scroll up for older history and down for newer history, or use the long slider at the bottom. The smaller slider controls zoom and starts at **80%**. Journal uses normal up-and-down scrolling and hides these sliders.

The readings at the bottom show follows, unfollows, hourly rates and **Growth ratio**. Use the **clock button** to choose **1h, 6h, 12h, 24h, 3d, 7d, 30d or 90d**. Hover over a reading’s label, or focus it with the keyboard, for a short explanation. In the Paid subscribers view, the readings show subscribers and expirations instead.

<details>
<summary>Understanding the numbers and connection history</summary>

- **Growth ratio** is gains divided by losses. For example, 7 follows and 2 unfollows gives **3.5**. A dash means there is no ratio to calculate, such as when there were no losses.
- **Percentage changes** compare the chosen period with the previous period of the same length. Green means more gains or fewer losses; red means the reverse. **New** means there was activity now but none in the previous period.
- **These are recorded changes, not your current follower total.** The readings use your full saved log and the time XFlog received each event, regardless of zoom, filters or grouping.
- **Workspace → Connection history** shows recorded interruptions. Events that happened before tracking began, or during a gap, may be missing; XFlog cannot reconstruct them.
- **Workspace → Refresh local history** reloads what XFlog has already saved. It does not fetch an old follower list from X. **Explore demo** lets you try the interface with sample data.

</details>

## Audience groups

Groups help you explore patterns without paying for more profile lookups. Open **timeline settings → Audience Groups** and turn on the ones you want. These switches **save automatically** and do not pause tracking. Then use the **spyglass button** on the timeline to choose a grouping.

**Ungrouped** is selected when you open XFlog. **Activity** is already available in the picker; the other groups start off. **None of these groups makes extra X requests or adds X API charges.**

| Group | Starts | What you’ll see |
| --- | --- | --- |
| **Activity** | On | People grouped by follows, unfollows, new subscriptions or expirations. Uses events already in your log. |
| **Previous encounters** | Off | **First appearance**, **Seen before** or **Followed again**, based on your saved history. |
| **Account size** | Off | **Under 100**, **100–999**, **1K–9,999** or **10K+** followers, when X includes the count. |
| **Account age** | Off | **Under 1 year**, **1–3 years** or **3+ years** old when the event was recorded. |
| **Verification** | Off | Verified and unverified accounts, with blue, business or government badge types when supplied. |
| **Profile location** | Off | Similar profile location labels together, with simple variations such as **NYC → New York City** and **Bangalore → Bengaluru** cleaned up. |

Zoom out in Constellation to see groups of stars. In Journal, the same choice gives you sections you can open or collapse. When there is room, enabled Verification, Account size and Account age also add facts to the selected person’s readout. With Verification enabled, known verified accounts get a checkmark beside their name in the constellation and readout.

**Missing details appear as Unknown.** Account size, age, verification and location use only details included with new events while that group is enabled. Turning a group on does not look up profiles or fill in missing details in old records. Turning it off keeps your saved history.

<details>
<summary>A few limits worth knowing</summary>

- **Previous encounters** can use history saved before you enabled it. **First appearance** means first in your XFlog log, not first on X. **Followed again** requires an unfollow followed by a follow in that log; a tracking gap may hide part of the story.
- **Profile facts describe the recorded event.** Someone’s follower count, account age or badge may have changed since then. XFlog does not keep checking their profile.
- **Location is profile text, not a verified address.** XFlog tidies spacing and capitalization and merges a few clear aliases. It does not guess where someone lives: **London, UK** and **London, Ontario** stay separate. Missing or unusable labels become Unknown.
- **The constellation shows people from the history you have loaded.** Loading older records can add people or change the groups you see. Journal lists the events themselves, so one person can appear in more than one section.

</details>

## Which features use X credits?

**Browsing saved history and changing the view do not add X API charges. Collecting live follower events and using Follow/Unfollow can cost money.** Running XFlog on your own computer does not remove X’s API fees.

| Feature | X API cost |
| --- | --- |
| **Offline demo** | None. No X requests. |
| **Groups, filters, layouts, zoom, statistics and notifications** | No extra X requests or charges for these tools. Any live events you record still follow X’s event pricing. |
| **Live follower tracking** | X bills each delivered follow or unfollow event on its pay-per-use plan. |
| **Paid-subscription tracking** | X currently lists new-subscription and subscription-expiry events as **not billed**. You still need a configured developer app, access to X Activity and a user access token. |
| **Allow Follow/Unfollow** | Makes additional X API requests. Checking whether you already follow someone can be billed, even if you never press Follow. Following or unfollowing also uses X’s action pricing. |

Pricing checked **26 October 2026**. See [X’s Activity event prices](https://docs.x.com/x-api/activity/event-pricing) and [API pricing](https://docs.x.com/x-api/getting-started/pricing) for current terms. Check your usage and set a spending limit in the [X Developer Console](https://console.x.com). The numbers shown inside XFlog are activity counts, not a bill or spending limit. VPS or other hosting costs are separate.

<details>
<summary>How to keep Follow/Unfollow requests under control</summary>

The feature starts off. When you enable it, XFlog first checks that the user token belongs to your configured account. It checks the selected person’s relationship only when an action button can be shown, and again before a follow or unfollow. It does not download your whole following list or keep checking X in the background. Selecting the same person again after 30 seconds can refresh the check.

If a check fails, **Retry** checks the relationship again; it does not repeat a follow or unfollow. Pending requests and blocked accounts must be managed on X. The demo cannot make these actions.

To stop further checks and actions, turn **Allow Follow/Unfollow** off in Profile and save. An action already sent to X may still complete. Following someone from XFlog does not create an incoming follower event in your log.

</details>
