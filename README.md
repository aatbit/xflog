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
| `X_USER_ACCESS_TOKEN` | The account’s permission to use your app. **Required for paid subscriptions; optional for followers only.** |

1. **Create a developer app** in the [X Developer Console](https://console.x.com). Check that it can use [X Activity](https://docs.x.com/x-api/activity/quickstart).
2. **Get your app’s bearer token and the account’s numeric ID.** X’s quickstart explains how to look up the ID.
3. **Add API credits and check your spending limit.** Also check whether automatic credit top-ups are enabled.
4. **Enter the settings in the installer or `.env`.** For paid-subscription tracking, get a user access token too; the details are below.

**X charges for live API usage, even when XFlog runs on your own computer.** Check [Activity prices](https://docs.x.com/x-api/activity/event-pricing) and [X’s spending rules](https://docs.x.com/x-api/getting-started/pricing) before starting. XFlog’s event count does not cap your X bill.

Followers are on by default. Paid-subscription tracking stays off until you enable it in Profile. Choose **Start tracking** when you’re ready. To use the demo instead, leave the X settings blank.

<details>
<summary>Getting a user access token for paid subscriptions</summary>

Use an external [OAuth 2.0 sign-in flow](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code) to let the account approve your app. Request the `follows.read` permission and save the returned access token as `X_USER_ACCESS_TOKEN`.

Both tokens must belong to the same developer app, and the user token must belong to the account in `X_USER_ID`. XFlog does not provide this sign-in flow or refresh tokens for you. You can skip this token for followers only, but XFlog will not start or resume paid-subscription tracking without it.

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

Choose **install**, then follow the prompts for your install method, a new installation folder, port, X settings and optional browser password. Review the choices before confirming. The installer won’t overwrite an existing installation.

**For local use, press Enter at the password prompt to leave protection off.** If you set a password, use at least 16 ASCII characters; the browser username is `xflog`. This password protects XFlog and is separate from your X account.

Open `http://127.0.0.1:7860` when installation finishes, or use the port you chose. Tokens and passwords are hidden while you type and saved in `.env`; keep that file private.

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

Run the installer, choose **check for updates** (type `check`), and enter your existing installation folder. It reports **XFlog app** and **Installer** updates separately. Checking does not change your app, settings or history, and Docker does not need to be running.

If the installer has changed, you can let it run the new copy and reopen the menu first. This uses a temporary copy; it does not overwrite a script you saved elsewhere. If an app update is available, it also prints the command to run—then choose **update**. App updates still need your confirmation.

**Updating**

Run the installer again, choose **update**, then select your install type and existing installation folder.

- Back up your history first.
- Your history, `.env` settings and custom Docker network settings are kept. New settings get their default values; existing values, including blanks, stay unchanged.
- The installer asks before restarting XFlog. It stops if you have edited the app’s tracked files.

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

The example below uses **Caddy installed directly on the same server as XFlog**. Caddy handles HTTPS and passes requests to XFlog, which stays on its private local port. If you already use another HTTPS proxy, you can keep using it.

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

These commands assume Caddy’s standard Linux service is installed. See [Caddy’s service guide](https://caddyserver.com/docs/running) if your installation uses a different setup.

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

The installer saves settings in `.env` inside your installation folder. For a manual setup, supply them through your launcher or environment. After changing these settings, [recreate the Docker container or restart the native app](#hosting-remotely-and-using-https).

These are the settings most people need:

| Setting | What it does |
| --- | --- |
| `X_APP_BEARER_TOKEN` | Your app’s X token. Required for live tracking. |
| `X_USER_ID` | The numeric ID of the X account to track. |
| `X_USER_ACCESS_TOKEN` | Required for paid subscriptions; optional for followers only. Get and refresh it outside XFlog. |
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

If `XFLOG_ENV_FILE` is not supplied, Profile says that no file path was provided. It asks for `X_USER_ACCESS_TOKEN` only when paid-subscription tracking is selected.

</details>

## Preferences and notifications

Change what you track in **Profile**, then choose **Save preferences**. Saving keeps a running listener on and a paused listener off. To turn off every event category, pause tracking first.

Enable **Activity notifications** for in-app notices and browser alerts while the page is open. Your browser may ask for permission when you save. If alerts are blocked or unsupported, in-app notices still work.

<details>
<summary>How preference changes and browser alerts work</summary>

- Saving only notification settings does not change your X subscriptions.
- If X cannot apply an event change, XFlog keeps your saved choices and shows a warning. Fix the X access or server storage problem, then save again to retry.
- Browser alerts need HTTPS or localhost, and each browser has its own permission setting. Alerts require an open page; XFlog does not send push notifications after it is closed.

</details>

## Exploring your audience

The constellation shows one star per person in the history you have loaded. Select a star to see an event, or use **Journal** in timeline settings to browse every recorded event. Scroll up or left for older encounters, down or right for newer ones. Light trails travel from older to newer encounters. Dragging, scrolling and the manual scrubber ease through the scene; reduced motion keeps movement immediate. The side arrows stay visible while there is room to travel; zoom out to **Fit** to see the whole loaded audience.

**Ungrouped** is selected when you open XFlog. Use the spyglass button to choose a grouping in either view. **Activity** is enabled by default and uses events XFlog already records, with no additional X API requests or charges.

In the constellation, zooming out gathers people by their latest recorded activity. In **Journal**, the same lens creates collapsible sections with event counts; events keep their existing order inside each section. A person’s follow and unfollow records can appear in different sections.

In timeline settings, open **Audience Groups** to turn optional groups on or off. **Account size** starts off. When enabled, it saves follower counts only when X includes them with a new event; it never looks up profiles. An older event or a missing count appears as **Unknown**. Enable it to add Account size to the spyglass picker alongside Activity and Ungrouped.

These groups describe the loaded history, not a complete or current follower list. Loading older events can add people or fill out a group. Turning a group off stops its metadata capture and removes its lens; your recorded history stays saved. Group changes save automatically and keep the listener running.

<details>
<summary>Adding an Audience Group as a developer</summary>

Each built-in group is a small, trusted Python module in `src/xflog/audience_groups/`. Register an `AudienceGroup` with a unique key, label, description, bucket definitions and an `assign(event)` function. Include an `unknown` bucket. An optional `capture(source)` function can return the small metadata snapshot to keep from an incoming event. Set `default_enabled=False` for optional features.

Import the module explicitly in the package’s `__init__.py`. The API catalog supplies its settings switch, lens option and overview buckets automatically; no feature-specific frontend code is needed. Follow the existing Account size module and its tests. Capture runs only while that group is enabled, and missing data must remain unknown.

This is a registration mechanism for code shipped with XFlog, not an installer for third-party plugins. Modules receive event data, not the X client or credentials. Keep them event-only: adding network lookups would need a separate design with explicit permission and cost handling.

This version adds a metadata column to the history database. Back up history before upgrading. If you later return to an older XFlog version, you may also need to restore its matching database backup.

</details>

<details>
<summary>Privacy and upgrading from older versions</summary>

X tokens stay in the server’s environment, outside Profile and the history database. Host and Docker administrators can inspect them, so protect your server and `.env` backups. The history database is not encrypted.

Older versions used Client IDs, secrets, callbacks and desktop keyring storage. Those settings and the built-in X sign-in flow have been removed. Existing history is kept, but XFlog does not delete old keyring credentials or revoke old X permissions. Remove those separately if needed.

</details>
