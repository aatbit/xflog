# XFlog

> See who follows, unfollows, or lets their paid subscription expire on X.

**X** **F**ollower **Log** is a small, self-hosted tracker that logs follower and paid-subscription activity through X’s official Activity API.
The current X UI shows unfollow metrics but does not have a direct way to view users who have unfollowed you or unsubscribed.
**XFlog** shows you these events as they arrive in a live timeline, with profile links and your history stored locally.

> [!NOTE]
> Tracking starts after you choose **Start tracking**. It doesn’t reconstruct past activity. Requires your X account to have API credits.


## Getting started

### X prerequisites

**The demo works without X credentials. For a real account, the settings you need depend on what you want to track:**

| Setting | What to put here |
| --- | --- |
| `X_APP_BEARER_TOKEN` | Your developer app's bearer token. Required for live tracking. |
| `X_USER_ID` | The number that identifies the X account you want to track. Required for live tracking; this is not its `@handle`. |
| `X_USER_ACCESS_TOKEN` | An OAuth 2.0 access token granted by that account to your app. **Required for paid-subscription tracking; optional for followers only.** |

To get ready:

1. **Create an X developer app.** Open the [X Developer Console](https://console.x.com) and check that your app can use [X Activity](https://docs.x.com/x-api/activity/quickstart).
2. **Get the app token and account ID.** Generate the app's bearer token in the console. Find the numeric ID of the account you want to track; X's quickstart explains how to look it up.
3. **For paid-subscription tracking, also get a user access token.** Use an external [OAuth 2.0 authorization flow](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code) to let that same X account approve your app. Request `follows.read` and save the returned access token as `X_USER_ACCESS_TOKEN`. Both tokens must belong to the same developer app, and the user token must belong to `X_USER_ID`. You can skip this step for followers only. XFlog does not perform this sign-in or refresh tokens for you.
4. **Check your X API balance and spending limit.** Add enough credits in the Developer Console before you start. Check whether automatic credit top-ups are enabled, and set a spending limit you are comfortable with.

**X charges for API usage.** Check the current [Activity prices](https://docs.x.com/x-api/activity/event-pricing) and [credit/spending-limit rules](https://docs.x.com/x-api/getting-started/pricing) before turning tracking on. Running XFlog on your own machine or in Docker does not remove those charges. XFlog's event count does not limit your X bill.

Put the required values in `.env` or enter them in the installer. Tracking starts when you confirm **Start tracking** in the app. Followers are enabled by default; paid subscription tracking stays off until you enable it in Profile. Without the user access token, XFlog will refuse to start or resume paid-subscription tracking when paid-subscription tracking is enabled. 
To try the offline demo instead, leave all X settings blank—no X API calls are made.

### Installation

Run as your regular user in a terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/aatbit/xflog/main/install.sh | bash
```

To inspect the script first:

```bash
curl -fsSL https://raw.githubusercontent.com/aatbit/xflog/main/install.sh -o install-xflog.sh
less install-xflog.sh
bash install-xflog.sh
```

Choose **install**, **update** or **uninstall**. A new install asks for Docker or native Linux, a fresh installation directory, local port, browser-facing origin, X credentials and a separate instance password. Secrets are hidden while typing and saved in an owner-only `.env`; a blank password generates one there. The browser username is **`xflog`**. Review the prepared configuration before the final activation prompt. New installs refuse existing paths and services. Do not run the installer with `sudo`.

- **Docker:** install Docker Engine, its Compose plugin and git first, and ensure your user can access the daemon. Choose a Compose project name and optionally an existing Docker network for your reverse proxy. The app keeps its private default network and localhost-only published port. Compose builds and starts it with `restart: unless-stopped`; enable Docker's own boot startup separately if your OS has not done so.
- **Native:** Linux, Bash, git, Python 3.12+ with `venv`/`ensurepip`, and a working systemd user session are required. A private virtual environment runs a user `xflog.service`. The installer enables user lingering for startup without an interactive login; the OS may request administrator authorization for that step. It does not install Python or system packages. History defaults to `~/.local/share/xflog/data/history.sqlite3` for this installation method.

Both modes bind the published HTTP endpoint to localhost. For remote access, supply your HTTPS origin and configure a TLS reverse proxy as described below. The optional Docker network joins an existing proxy network; the installer does not provision a proxy, DNS or certificates. Blank X credentials enable the offline demo without making X API calls. A fresh installation does not begin collection automatically.

The default source is `main`. To select a branch, tag or commit, download the script and run `XFLOG_REF=<ref> bash install-xflog.sh`. No automatic updater is installed. After installation, manage Docker from its installation directory with `docker compose ps`, `logs` and `down`; manage native startup with `systemctl --user status|restart|stop xflog.service` and `journalctl --user -u xflog.service`.

To update an installer-managed deployment, run the same script, choose **update**, select Docker/native and enter the existing checkout directory. Back up history first. The updater fetches `main` (or `XFLOG_REF`), refuses tracked local changes and restarts the runtime only after confirmation. Existing `.env` assignments—including deliberately blank values—are preserved; missing keys from the new `.env.example` receive their defaults. A newly missing instance password is generated privately. Custom Compose network overrides remain in place. Saved identity/port/path fields must be literal values; unsupported interpolation is rejected instead of executed or guessed. Native dependency failure leaves the service stopped for repair; Docker build failure does not delete history. No automatic database downgrade or rollback is attempted.

To uninstall, choose **uninstall** and the same mode/directory. This removes the Docker runtime or disables/removes the native user service. By default the checkout, native virtual environment, `.env`, history and network overrides remain for recovery; **update** can activate that retained installation again. Separate prompts require typing **`DELETE`** to remove recorded history and to remove `.env`. Docker deletion is restricted to the installation's owned `history` volume; native deletion removes only the configured database, its SQLite sidecars and pause marker. Custom/external volumes, proxy networks, backups and shared user lingering are never deleted. Pause tracking in the UI before uninstalling if X subscriptions need cleanup; uninstall makes no X calls and never revokes external tokens.

A retained or restored database keeps its saved Start choice, so remove credentials or pause before activation if collection should stay stopped. Manual Docker `down` keeps history; **`down -v` deletes it**. Environment changes require container recreation (`docker compose up -d --force-recreate`) or a native service restart. If maintenance was interrupted, remove `.xflog-maintenance.lock` only after verifying that no updater/uninstaller is still running.

## Docker Compose

Docker Engine with the Compose plugin is sufficient; Python and Node do not need to be installed on the host.

```bash
cp .env.example .env
chmod 600 .env
```

For follower tracking, set `X_APP_BEARER_TOKEN` and `X_USER_ID`. Add `X_USER_ACCESS_TOKEN` if you want paid-subscription tracking too. Leave all X settings blank for the offline demo. Set a strong random `XFLOG_ADMIN_PASSWORD` of at least 16 ASCII characters. This password protects the private instance; it is **not** your X password. For example, generate one using:

```bash
docker run --rm python:3.12-slim-bookworm python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Then:

```bash
docker compose up -d --build
docker compose ps
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860). The browser's HTTP Basic username is **`xflog`**, with your configured instance password. This is a private single-account service, not a multi-user login system. Leaving the X credentials blank permits the synthetic offline demo; live collection stays unavailable.

The image uses a digest-pinned Python slim base and uv builder, locked production dependencies, cached dependency layers and a non-editable install. It runs as UID/GID **10001**, with no uv, build context, tests, `.env` or developer tools copied into the final stage. Compose drops Linux capabilities, blocks privilege escalation, makes the root filesystem read-only, gives `/tmp` a bounded tmpfs, and persists `/data` in a named volume. A built-in health check needs no curl or extra package. Build and runtime access logs do not print X credentials; the provided launcher disables HTTP access logging.

The published port binds to **host loopback only**. Rebuild regularly and update the pinned base-image digests to receive upstream security fixes. Do not scale replicas or run multiple workers for one developer app.

## Hosting remotely and using HTTPS

Set the browser-facing origin in `.env`, without a trailing slash or path:

```dotenv
XFLOG_ORIGIN=https://xf.example.com
```

Put your TLS reverse proxy in front of the localhost-published port. For example, with Caddy running on the host:

```caddyfile
xf.example.com {
    reverse_proxy 127.0.0.1:7860
}
```

Preserve the original Host and Authorization headers. XFlog checks the configured host and exact Origin, requires CSRF for mutations and uses Secure cookies for HTTPS origins. It ignores forwarded headers; the proxy must terminate TLS and keep the internal HTTP port private. No X callback URL is required by this repo because it has no OAuth flow.

If the proxy runs in Docker instead, attach it to the same private network and route to `xflog:7860`; do not publicly publish the application's raw HTTP port. This repository supplies the application Compose service; domain registration, TLS provisioning and proxy deployment are operator responsibilities.

After changing environment credentials, **recreate** the container:

```bash
docker compose up -d --force-recreate
```

`docker compose restart` retains the old container environment. An expired or revoked user token stops affected collection with an actionable error. Refresh it externally and recreate the container; XFlog does not silently change collection methods.

## Environment configuration

| Variable | Purpose |
| --- | --- |
| `X_APP_BEARER_TOKEN` | Required for live tracking. App credential for public subscriptions and the Activity stream. |
| `X_USER_ID` | Required for live tracking. Numeric target account ID, not an @handle. |
| `X_USER_ACCESS_TOKEN` | Required for paid-subscription tracking; optional for followers only. OAuth 2.0 token for the target account; obtain and refresh it externally. |
| `XFLOG_ADMIN_PASSWORD` | Instance access password; required for Docker/network binding and HTTPS origins. Browser username is `xflog`. Optional for native loopback-only use. |
| `XFLOG_ORIGIN` | Browser origin. Default `http://127.0.0.1:7860`; use HTTPS for a public domain. |
| `XFLOG_PUBLISH_PORT` | Compose host port, default `7860`. Update `XFLOG_ORIGIN` to match local port changes. |
| `XFLOG_DATABASE` | SQLite path. Docker defaults to `/data/history.sqlite3`; keep it under `/data` for persistence. |
| `XFLOG_HOST`, `XFLOG_PORT` | Native listen address/port, default `127.0.0.1:7860`. The image sets these to `0.0.0.0:7860` internally. |

Secrets stay in the runtime environment, never in Profile or image build arguments. Anyone with Docker/host administration privileges can inspect container environments: protect the host and keep `.env` private. The database stores history and preferences, not X tokens. It is not encrypted.

The old Client ID/secret, callback, desktop keyring and browser consent configuration have been removed. Existing history is retained; upgrading does not migrate or delete credentials from any old OS credential store. Remove obsolete authorizations/credentials separately if no longer needed.
