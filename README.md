# XFlog

> See who follows, unfollows, or lets their paid subscription expire on X.

**X** **F**ollower **Log** is a small, self-hosted tracker that logs follower and paid-subscription activity through X’s official Activity API.
The current X UI shows unfollow metrics but does not have a direct way to view users who have unfollowed you or unsubscribed.
**XFlog** shows you these events as they arrive in a live timeline, with profile links and your history stored locally.

> [!NOTE]
> Tracking starts after you choose **Start tracking**. It doesn’t reconstruct past activity. Requires your X account to have API credits.


## Getting started

### Interactive install

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

The installer asks for Docker or native Linux, a fresh installation directory, local port, browser-facing origin, X credentials and a separate instance password. Secrets are hidden while typing and saved in an owner-only `.env`; a blank password generates one there. The browser username is **`xflog`**. Review the prepared configuration before the final activation prompt. Existing installation paths and services are never overwritten. Do not run the installer with `sudo`.

- **Docker:** install Docker Engine, its Compose plugin and git first, and ensure your user can access the daemon. Choose a Compose project name and optionally an existing Docker network for your reverse proxy. The app keeps its private default network and localhost-only published port. Compose builds and starts it with `restart: unless-stopped`; enable Docker's own boot startup separately if your OS has not done so.
- **Native:** Linux, Bash, git, Python 3.12+ with `venv`/`ensurepip`, and a working systemd user session are required. A private virtual environment runs a user `xflog.service`. The installer enables user lingering for startup without an interactive login; the OS may request administrator authorization for that step. It does not install Python or system packages. History defaults to `~/.local/share/xflog/data/history.sqlite3` for this installation method.

Both modes bind the published HTTP endpoint to localhost. For remote access, supply your HTTPS origin and configure a TLS reverse proxy as described below. The optional Docker network joins an existing proxy network; the installer does not provision a proxy, DNS or certificates. Blank X credentials enable the offline demo without making X API calls. A fresh installation does not begin collection automatically.

The default source is `main`. To select a branch, tag or commit, download the script and run `XFLOG_REF=<ref> bash install-xflog.sh`. No automatic updater is installed. After installation, manage Docker from its installation directory with `docker compose ps`, `logs` and `down`; manage native startup with `systemctl --user status|restart|stop xflog.service` and `journalctl --user -u xflog.service`.

To update, pause tracking, back up history, and update the checkout to a reviewed revision. Docker: rebuild with `docker compose up -d --build`. Native: stop the service, run `uv sync --locked --no-dev --no-editable` in the checkout using uv 0.11.29, then restart. Environment changes require Docker recreation (`docker compose up -d --force-recreate`) or a native service restart. The installer intentionally refuses upgrades over an existing path.

To remove native startup, run `systemctl --user disable --now xflog.service`, remove only its unit from `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/`, then `systemctl --user daemon-reload`. Keep the data directory for recovery. Do not disable lingering if other user services depend on it. Docker `down` preserves history; **`down -v` deletes it**. A reused database retains its saved tracking choice, so remove credentials or pause before activating a restored installation if you do not want collection to resume.

### X prerequisites and costs

Before you install and start collection, please ensure the below steps are completed:

1. Create an approved app in [X Developer Console](https://console.x.com) and confirm that its API access permits X Activity.
2. Generate its app bearer token and determine the target account's numeric user ID.
3. **For full functionality, supply `X_USER_ACCESS_TOKEN`: an OAuth 2.0 user-context token for `X_USER_ID`, from the same developer app, with `follows.read`.** Obtain and refresh it through your external authorization flow. App bearer plus user ID supports public follower tracking; paid events require the user token. This repository does not implement X login or token acquisition.
4. **Make sure your developer account has the required credits/billing access. Review current event pricing, configure a provider spending limit, and review auto-recharge.** A local event count is not a billing cap.

No developer-account signup, credit purchase or API entitlement is provisioned by XFlog. Running Docker does not remove X API requirements or charges. The UI requires a separate, explicit **Start tracking** confirmation. No follower-roster polling, scraping or historical reconstruction is used.

Official references: [Activity prerequisites](https://docs.x.com/x-api/activity/quickstart), [private-event authentication](https://docs.x.com/x-api/activity/create-x-activity-subscription), [event pricing](https://docs.x.com/x-api/activity/event-pricing), [credits and spending limits](https://docs.x.com/x-api/getting-started/pricing). Live entitlement, delivery and account pricing remain unverified.

## Docker Compose

Docker Engine with the Compose plugin is sufficient; Python and Node do not need to be installed on the host.

```bash
cp .env.example .env
chmod 600 .env
```

Set `X_APP_BEARER_TOKEN`, `X_USER_ID`, and, for full functionality, `X_USER_ACCESS_TOKEN`. Set a strong random `XFLOG_ADMIN_PASSWORD` of at least 16 ASCII characters. This password protects the private instance; it is **not** your X password. For example, generate one using:

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
| `X_APP_BEARER_TOKEN` | App-only credential for follower subscription management and the central Activity stream. |
| `X_USER_ID` | Numeric target account ID, not an @handle. |
| `X_USER_ACCESS_TOKEN` | User-context OAuth 2.0 token required for full functionality, including paid-subscription events. Externally obtained and maintained. |
| `XFLOG_ADMIN_PASSWORD` | Instance access password; required for Docker/network binding and HTTPS origins. Browser username is `xflog`. Optional for native loopback-only use. |
| `XFLOG_ORIGIN` | Browser origin. Default `http://127.0.0.1:7860`; use HTTPS for a public domain. |
| `XFLOG_PUBLISH_PORT` | Compose host port, default `7860`. Update `XFLOG_ORIGIN` to match local port changes. |
| `XFLOG_DATABASE` | SQLite path. Docker defaults to `/data/history.sqlite3`; keep it under `/data` for persistence. |
| `XFLOG_HOST`, `XFLOG_PORT` | Native listen address/port, default `127.0.0.1:7860`. The image sets these to `0.0.0.0:7860` internally. |

Secrets stay in the runtime environment, never in Profile or image build arguments. Anyone with Docker/host administration privileges can inspect container environments: protect the host and keep `.env` private. The database stores history and preferences, not X tokens. It is not encrypted.

The old Client ID/secret, callback, desktop keyring and browser consent configuration have been removed. Existing history is retained; upgrading does not migrate or delete credentials from any old OS credential store. Remove obsolete authorizations/credentials separately if no longer needed.
