#!/usr/bin/env bash
set +x
set -Eeuo pipefail
umask 077
export LC_ALL=C
ENV_ASSIGNMENT='^[[:space:]]*(export[[:space:]]+)?([A-Z][A-Z0-9_]*)[[:space:]]*=(.*)$'

die() { printf 'XFlog: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Install $1 first, then run this installer again."; }
ask() { IFS= read -r -u 3 -p "$1 " reply || die 'Input closed; installation canceled.'; }
secret() {
  IFS= read -r -s -u 3 -p "$1 " reply || die 'Input closed; installation canceled.'
  printf '\n' >&3
}
valid_port() { [[ $1 =~ ^[0-9]{1,5}$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535)); }
valid_path() { [[ $1 == /* && $1 != / && $1 =~ ^/[A-Za-z0-9_./-]+$ ]]; }
local_origin() { [[ $origin =~ ^https?://(127\.0\.0\.1|localhost)(:[0-9]+)?$ ]]; }
valid_origin() {
  local address=$1 origin_port
  if [[ $address =~ ^http://(127\.0\.0\.1|localhost):([0-9]+)$ ]]; then
    origin_port=${BASH_REMATCH[2]}
    valid_port "$origin_port" && [[ $origin_port == "$port" ]]
  elif [[ $address =~ ^https://[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]+)?$ ]]; then
    [[ ${address#https://} != *:* ]] || valid_port "${address##*:}"
  else
    return 1
  fi
}

# Compose interpolates $, whereas systemd EnvironmentFile leaves it literal.
env_line() {
  local key=$1 value=$2
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  if [[ $mode == docker ]]; then value=${value//\$/\$\$}; fi
  printf '%s="%s"\n' "$key" "$value"
}

write_environment() {
  # The destination path is printed as metadata, never read by env_line.
  # shellcheck disable=SC2094
  {
    env_line X_APP_BEARER_TOKEN "$bearer"
    env_line X_USER_ID "$user_id"
    env_line X_USER_ACCESS_TOKEN "$user_token"
    env_line XFLOG_ADMIN_PASSWORD "$password"
    env_line XFLOG_ORIGIN "$origin"
    env_line XFLOG_ENV_FILE "$install_dir/.env"
    if [[ $mode == docker ]]; then
      env_line COMPOSE_PROJECT_NAME "$project"
      env_line XFLOG_PUBLISH_PORT "$port"
    else
      env_line XFLOG_HOST 127.0.0.1
      env_line XFLOG_PORT "$port"
      env_line XFLOG_DATABASE "$data_dir/history.sqlite3"
      env_line GRADIO_ANALYTICS_ENABLED False
      env_line GRADIO_TEMP_DIR "$data_dir/tmp"
      env_line HF_HOME "$data_dir/cache"
    fi
  } > "$install_dir/.env"
  chmod 600 "$install_dir/.env"
  merge_defaults
}

# Never source a settings file: even an operator's edited .env is data, not shell code.
saved_setting() {
  local key=$1 value=$2 line
  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line =~ $ENV_ASSIGNMENT && ${BASH_REMATCH[2]} == "$key" ]]; then
      [[ $mode != native || -z ${BASH_REMATCH[1]} ]] || die "Native EnvironmentFile does not support export $key; use KEY=value."
      value=${BASH_REMATCH[3]}
    fi
  done < "$install_dir/.env"
  value=${value#"${value%%[![:space:]]*}"}
  value=${value%"${value##*[![:space:]]}"}
  if [[ $value == \"*\" || $value == \'*\' ]]; then value=${value:1:${#value}-2}; fi
  [[ $value =~ ^[A-Za-z0-9_./:~-]*$ ]] || die "Unsupported $key format; use a literal value in .env."
  printf '%s' "$value"
}

merge_defaults() (
  local temporary line key value existing found
  temporary=$(mktemp "$install_dir/.env.XXXXXX")
  trap 'rm -f -- "$temporary"' EXIT
  cat "$install_dir/.env" > "$temporary"
  while IFS= read -r line || [[ -n $line ]]; do
    [[ $line =~ $ENV_ASSIGNMENT ]] || continue
    key=${BASH_REMATCH[2]}; value=${BASH_REMATCH[3]}; found=false
    while IFS= read -r existing || [[ -n $existing ]]; do
      if [[ $existing =~ $ENV_ASSIGNMENT && ${BASH_REMATCH[2]} == "$key" ]]; then found=true; break; fi
    done < "$temporary"
    $found && continue
    case $key in
      XFLOG_ORIGIN) line=$(env_line "$key" "$origin");;
      XFLOG_PUBLISH_PORT) line=$(env_line "$key" "$port");;
      XFLOG_ENV_FILE) line=$(env_line "$key" "$install_dir/.env");;
    esac
    printf '\n%s\n' "$line" >> "$temporary"
    printf 'Added missing setting: %s (default saved; value hidden).\n' "$key" >&3
  done < "$install_dir/.env.example"
  chmod 600 "$temporary"
  mv -- "$temporary" "$install_dir/.env"
)

write_network() {
  [[ -n $network ]] || return 0
  cat > "$install_dir/compose.override.yaml" <<EOF
services:
  xflog:
    networks:
      - default
      - proxy
networks:
  proxy:
    external: true
    name: "$network"
EOF
}

# Prompted settings must win over ambient Compose configuration and shell secrets.
compose() (
  local variable
  local files=(-f "$install_dir/compose.yaml")
  for variable in "${!COMPOSE_@}" "${!XFLOG_@}" X_APP_BEARER_TOKEN X_USER_ID X_USER_ACCESS_TOKEN; do
    unset "$variable"
  done
  if [[ -f $install_dir/compose.override.yaml ]]; then
    files+=(-f "$install_dir/compose.override.yaml")
  fi
  docker compose --project-directory "$install_dir" --env-file "$install_dir/.env" -p "$project" "${files[@]}" "$@"
)

write_unit() {
  cat > "$install_dir/xflog.service" <<EOF
[Unit]
Description=XFlog private audience history
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=exec
WorkingDirectory=$install_dir
EnvironmentFile=$install_dir/.env
ExecStart=$install_dir/.venv/bin/python -m xflog
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
UMask=0077
NoNewPrivileges=yes
RestrictSUIDSGID=yes
LockPersonality=yes

[Install]
WantedBy=default.target
EOF
}

sync_native() (
  local bootstrap_dir
  bootstrap_dir=$(mktemp -d "${TMPDIR:-/tmp}/xflog-bootstrap.XXXXXX")
  trap 'rm -rf -- "$bootstrap_dir"' EXIT
  "$python" -m venv "$bootstrap_dir"
  "$bootstrap_dir/bin/python" -m pip install --disable-pip-version-check --quiet 'uv==0.11.29'
  "$bootstrap_dir/bin/uv" sync --project "$install_dir" --locked --no-dev --no-editable --python "$python"
)

save_unit() {
  write_unit
  systemd-analyze --user verify "$install_dir/xflog.service"
  mkdir -p "$unit_dir"
  install -m 600 "$install_dir/xflog.service" "$unit_dir/xflog.service"
  systemctl --user daemon-reload
}

wait_native() {
  local attempt
  for ((attempt=0; attempt<30; attempt++)); do
    if systemctl --user is-active --quiet xflog.service &&
      XFLOG_PORT="$port" XFLOG_ORIGIN="$origin" "$install_dir/.venv/bin/python" -m xflog.healthcheck; then
      return 0
    fi
    sleep 1
  done
  die 'Service did not become healthy. Inspect: journalctl --user -u xflog.service'
}

start_runtime() {
  if [[ $mode == docker ]]; then
    compose up -d --build --wait --wait-timeout 120
  else
    systemctl --user enable --now xflog.service
    wait_native
  fi
}

install_native() {
  sync_native
  mkdir -p "$data_dir" "$HOME/.local/share/xflog/locks"
  chmod 700 "$data_dir"
  if [[ $(loginctl show-user "$(id -un)" -p Linger --value) != yes ]]; then
    if ! loginctl enable-linger "$(id -un)"; then
      need sudo
      sudo loginctl enable-linger "$(id -un)"
    fi
  fi
  [[ ! -e $unit_dir/xflog.service ]] || die 'A user xflog.service already exists; not overwriting it.'
  save_unit
  start_runtime
}

verify_checkout() {
  [[ $(git -C "$install_dir" rev-parse --show-toplevel) == "$install_dir" ]] || die 'Choose the root of the installed checkout.'
  local remote
  remote=$(git -C "$install_dir" remote get-url origin)
  [[ $remote == https://github.com/aatbit/xflog.git || $remote == git@github.com:aatbit/xflog.git ]] || die 'The checkout must use the official aatbit/xflog origin.'
}

load_installation() {
  [[ -f $install_dir/.env && ! -L $install_dir/.env ]] || die 'A regular saved .env is required; it will never be executed.'
  verify_checkout
  if [[ $mode == docker ]]; then
    project=$(saved_setting COMPOSE_PROJECT_NAME '')
    [[ $project =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die 'Saved COMPOSE_PROJECT_NAME is required to identify the existing stack safely.'
    port=$(saved_setting XFLOG_PUBLISH_PORT 7860)
    [[ -f $install_dir/compose.yaml ]] || die 'Saved Compose configuration is missing.'
    local container working_directory containers
    containers=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
    for container in $containers; do
      working_directory=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$container")
      [[ $working_directory == "$install_dir" ]] || die 'This Compose project belongs to another checkout; no runtime changed.'
    done
  else
    [[ -f $install_dir/xflog.service && ! -L $install_dir/xflog.service ]] || die 'The regular installer-generated xflog.service is missing.'
    grep -Fxq "WorkingDirectory=$install_dir" "$install_dir/xflog.service" || die 'The saved service belongs to another checkout.'
    if [[ -e $unit_dir/xflog.service ]]; then
      cmp -s "$unit_dir/xflog.service" "$install_dir/xflog.service" || die 'The installed user unit differs; reconcile it manually before continuing.'
    fi
    port=$(saved_setting XFLOG_PORT 7860)
    database=$(saved_setting XFLOG_DATABASE "$HOME/.local/share/xflog/history.sqlite3")
    valid_path "$database" || die 'Use an absolute literal XFLOG_DATABASE path.'
    data_dir=${database%/*}
  fi
  valid_port "$port" || die 'Saved port is invalid.'
  origin=$(saved_setting XFLOG_ORIGIN "http://127.0.0.1:$port")
  valid_origin "$origin" || die 'Saved origin is invalid.'
}

update_installation() {
  if ! git -C "$install_dir" diff --quiet || ! git -C "$install_dir" diff --cached --quiet; then
    die 'Tracked files have local changes; commit or move them before updating.'
  fi
  [[ ! -L $install_dir/.env.example ]] || die 'The environment template must be a regular file.'
  git -C "$install_dir" fetch --depth 1 origin "$reference"
  printf 'Update %s installation at %s to %s. Saved settings, history and network overrides stay.\n' "$mode" "$install_dir" "$reference" >&3
  printf 'Back up history before updating. A saved Start choice may resume collection.\n' >&3
  ask 'Update and restart this installation now? [y/N]'
  [[ $reply == y || $reply == Y ]] || { printf 'Update canceled.\n' >&3; return; }
  git -C "$install_dir" checkout --quiet --detach FETCH_HEAD
  [[ -f $install_dir/.env.example && -f $install_dir/uv.lock ]] || die 'The fetched source is incomplete.'
  merge_defaults
  if [[ $mode == docker ]]; then
    compose config --quiet
  else
    [[ -x $install_dir/.venv/bin/python ]] || die 'The existing Python environment is missing; restore it before updating.'
    python=$install_dir/.venv/bin/python
    if [[ -e $unit_dir/xflog.service ]]; then systemctl --user stop xflog.service; fi
    printf 'Native service stopped; a failed dependency update leaves it stopped for repair.\n' >&3
    sync_native
    save_unit
  fi
  start_runtime
  printf 'Updated. History and saved settings retained.\n' >&3
}

uninstall_installation() {
  printf 'Remove the %s runtime at %s. Checkout, .env and history are retained by default.\n' "$mode" "$install_dir" >&3
  printf 'Pause tracking in the UI first if X subscriptions need cleanup; uninstall does not revoke tokens.\n' >&3
  ask 'Uninstall this runtime now? [y/N]'
  [[ $reply == y || $reply == Y ]] || { printf 'Uninstall canceled.\n' >&3; return; }
  if [[ $mode == docker ]]; then
    compose down
  elif [[ -e $unit_dir/xflog.service ]]; then
    systemctl --user disable --now xflog.service
    rm -- "$unit_dir/xflog.service"
    systemctl --user daemon-reload
  fi
  if [[ $mode == docker ]]; then
    printf 'Recorded history: Docker volume %s_history (other/external volumes are never deleted).\n' "$project" >&3
  else
    printf 'Recorded history: %s and its SQLite sidecars/pause marker.\n' "$database" >&3
  fi
  ask 'Delete recorded history permanently? Type DELETE to confirm [keep]'
  if [[ $reply == DELETE ]]; then
    if [[ $mode == docker ]]; then
      local volume=${project}_history owner label
      owner=$(docker volume inspect --format '{{index .Labels "com.docker.compose.project"}}' "$volume")
      label=$(docker volume inspect --format '{{index .Labels "com.docker.compose.volume"}}' "$volume")
      [[ $owner == "$project" && $label == history ]] || die 'History volume ownership could not be verified; no data deleted.'
      docker volume rm "$volume"
    else
      rm -f -- "$database" "$database-wal" "$database-shm" "$database-journal" "$database.paused"
    fi
  fi
  ask 'Delete saved .env credentials and settings? Type DELETE to confirm [keep]'
  if [[ $reply == DELETE ]]; then rm -- "$install_dir/.env"; fi
  printf 'Runtime removed. Unselected data/settings and checkout remain at %s. User lingering and external networks are unchanged.\n' "$install_dir" >&3
}

manage_installation() (
  mkdir "$install_dir/.xflog-maintenance.lock" || die 'Maintenance lock exists; another operation may be running. Remove a stale lock only after checking.'
  trap 'rmdir -- "$install_dir/.xflog-maintenance.lock"' EXIT
  load_installation
  if [[ $action == update ]]; then update_installation; else uninstall_installation; fi
)

choose_installation() {
  while :; do
    ask "Installation directory? [$HOME/.local/share/xflog/app]"
    install_dir=${reply:-$HOME/.local/share/xflog/app}
    install_dir=${install_dir/#\~/$HOME}; install_dir=${install_dir%/}
    valid_path "$install_dir" || { printf 'Use an absolute path with letters, digits, /, ., _ and - only.\n' >&3; continue; }
    if [[ $action == install ]]; then
      [[ ! -e $install_dir ]] || die 'Installation path already exists. Choose a fresh path; existing data is never overwritten.'
    else
      [[ -d $install_dir ]] || die 'Choose an existing installer checkout.'
      install_dir=$(cd "$install_dir" && pwd -P)
    fi
    break
  done
}

check_updates() (
  local temporary installed latest current_installer latest_installer installer_path comparison=0
  verify_checkout
  temporary=$(mktemp -d "${TMPDIR:-/tmp}/xflog-update-check.XXXXXX")
  trap 'rm -rf -- "$temporary"' EXIT
  git init --quiet "$temporary"
  git -C "$temporary" fetch --quiet --depth 1 "$install_dir" HEAD || die 'Could not read the installed revision; nothing changed.'
  installed=$(git -C "$temporary" rev-parse 'FETCH_HEAD^{commit}')
  git -C "$temporary" fetch --quiet --depth 1 https://github.com/aatbit/xflog.git "$reference" || die 'Could not check GitHub. Check your connection and source reference; nothing changed.'
  latest=$(git -C "$temporary" rev-parse 'FETCH_HEAD^{commit}')
  latest_installer=$(git -C "$temporary" rev-parse "$latest:install.sh")
  git -C "$temporary" show "$latest:install.sh" > "$temporary/install.sh" || die 'The selected source has no installer; nothing changed.'
  bash -n "$temporary/install.sh" || die 'The downloaded installer failed its syntax check; nothing changed.'
  installer_path=${BASH_SOURCE[0]:-}
  if [[ -f $installer_path ]]; then
    current_installer=$(git hash-object --no-filters -- "$installer_path")
  else
    # A pipe has no reusable script file; compare the installed installer instead.
    current_installer=$(git -C "$temporary" rev-parse --verify "$installed:install.sh" 2>/dev/null) || current_installer=''
  fi
  printf '\nChecking source: %s\nInstalled: %.12s  Available: %.12s\n' "$reference" "$installed" "$latest" >&3
  if ! git -C "$install_dir" diff --quiet || ! git -C "$install_dir" diff --cached --quiet; then
    printf 'Local app files have edits; save or move them before an app update.\n' >&3
  fi
  git -C "$temporary" diff --quiet "$installed" "$latest" -- . ':!install.sh' ':!README.md' || comparison=$?
  if [[ $comparison == 0 ]]; then
    printf 'XFlog app: up to date.\n' >&3
  elif [[ $comparison == 1 ]]; then
    printf 'XFlog app: update available (files differ from the selected source).\nTo update, run:\n' >&3
    printf 'curl -fsSL https://raw.githubusercontent.com/aatbit/xflog/%s/install.sh | XFLOG_REF=%q bash\nThen choose update and installation folder: %s\n' "$latest" "$reference" "$install_dir" >&3
  else
    die 'Could not compare application files; no update applied.'
  fi
  if [[ $current_installer == "$latest_installer" ]]; then
    printf 'Installer: up to date.\n' >&3
  else
    if [[ -n $current_installer ]]; then
      printf 'Installer: update available.\n' >&3
    else
      printf 'Installer: no saved version to compare; the latest copy is ready to run.\n' >&3
    fi
    printf 'Settings, history and running services stay unchanged.\n' >&3
    ask 'Run the updated installer now and reopen its menu? [y/N]'
    if [[ $reply == y || $reply == Y ]]; then
      XFLOG_REF="$reference" bash "$temporary/install.sh"
    else
      printf 'Installer refresh canceled.\n' >&3
    fi
  fi
)

main() {
  if [[ ${1:-} == --help ]]; then
    printf '%s\n' 'XFlog interactive install/update/uninstall/check: Docker Compose or native Linux/systemd user service.' \
      'Requires Bash, git and an interactive terminal. Docker mode needs Docker Compose v2.' \
      'Native mode needs Python 3.12+, venv/pip and a working systemd user session.' \
      'Optional: XFLOG_REF=branch/tag/commit (default: main). Updates preserve settings/history; uninstall asks before deletion.'
    return
  fi
  [[ $# == 0 ]] || die 'Only --help is supported.'
  exec 3<> /dev/tty || die 'An interactive terminal is required (including for curl | bash).'
  need git
  local action mode port origin install_dir bearer user_id user_token password database='' network='' project='' python='' data_dir='' unit_dir=''
  local reference=${XFLOG_REF:-main}
  [[ $reference =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || die 'Invalid XFLOG_REF.'
  printf '\nXFlog — interactive setup\nFollower tracking needs an app bearer token and account ID. Paid subscription tracking also needs a user access token. The offline demo needs no X credentials.\n' >&3
  while :; do
    ask 'Action: install, update, uninstall or check for updates (check)? [install]'
    action=${reply:-install}
    [[ $action != 'check for updates' ]] || action=check
    [[ $action == install || $action == update || $action == uninstall || $action == check ]] && break
  done
  if [[ $action == check ]]; then choose_installation; check_updates; return; fi
  while :; do
    ask 'Run with Docker or native Linux? [docker]'
    mode=${reply:-docker}
    [[ $mode == docker || $mode == native ]] && break
  done
  if [[ $mode == docker ]]; then
    need docker
    docker compose version >/dev/null
    docker info >/dev/null
  else
    [[ $(uname -s) == Linux && $EUID != 0 ]] || die 'Native mode requires Linux and a regular user; do not run it with sudo.'
    need systemctl; need systemd-analyze; need loginctl
    systemctl --user show-environment >/dev/null || die 'No systemd user session. Log in normally or choose Docker.'
    unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
    if [[ $action == install ]]; then
      ask 'Python 3.12+ executable? [python3]'
      python=$(command -v "${reply:-python3}") || die 'Python executable not found.'
      "$python" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ is required"; import venv, ensurepip'
      [[ ! -e $unit_dir/xflog.service ]] || die 'A user xflog.service already exists; not overwriting it.'
    fi
  fi
  choose_installation
  if [[ $action != install ]]; then manage_installation; return; fi
  while :; do
    ask 'Local port (localhost only)? [7860]'
    port=${reply:-7860}
    valid_port "$port" && { port=$((10#$port)); break; }
    printf 'Enter a port from 1 to 65535.\n' >&3
  done
  while :; do
    ask "Browser-facing origin? [http://127.0.0.1:$port]"
    origin=${reply:-http://127.0.0.1:$port}; origin=${origin%/}
    origin=$(printf '%s' "$origin" | tr '[:upper:]' '[:lower:]')
    valid_origin "$origin" && break
    printf 'Use an HTTPS origin without a path, or a localhost HTTP origin matching the local port.\n' >&3
  done
  if [[ $mode == docker ]]; then
    while :; do
      ask 'Compose project name? [xflog]'
      project=${reply:-xflog}
      [[ $project =~ ^[a-z0-9][a-z0-9_-]*$ ]] && break
    done
    local containers
    containers=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
    [[ -z $containers ]] || die 'This Compose project already has containers; choose a different project.'
    printf 'Available Docker networks:\n' >&3
    docker network ls --format '{{.Name}}' >&3
    while :; do
      ask 'Existing extra network to join (blank for none)?'
      network=$reply
      [[ -z $network ]] && break
      [[ $network =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] && docker network inspect "$network" >/dev/null 2>&1 && break
      printf 'Choose an existing network name from the list.\n' >&3
    done
  else
    while :; do
      ask "Dedicated data directory? [$HOME/.local/share/xflog/data]"
      data_dir=${reply:-$HOME/.local/share/xflog/data}; data_dir=${data_dir/#\~/$HOME}; data_dir=${data_dir%/}
      valid_path "$data_dir" && [[ $data_dir != "$HOME" ]] && break
    done
    "$python" -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1",int(sys.argv[1]))); s.close()' "$port" || die 'Local port is unavailable.'
  fi
  secret 'X app bearer token (blank for offline demo):'
  bearer=$reply; user_id=''
  [[ $bearer != *[!\!-~]* ]] || die 'Tokens must contain only printable ASCII without spaces.'
  if [[ -n $bearer ]]; then
    while :; do
      ask 'Numeric target X user ID?'
      [[ $reply =~ ^[0-9]{1,19}$ ]] && { user_id=$reply; break; }
    done
  fi
  secret 'X user access token (required for paid subscriptions; blank for followers only or demo):'
  user_token=$reply
  [[ $user_token != *[!\!-~]* ]] || die 'Tokens must contain only printable ASCII without spaces.'
  [[ -n $bearer || -z $user_token ]] || die 'A user token also requires the app bearer token and user ID.'
  while :; do
    secret 'Instance password, 16+ ASCII characters (blank disables protection for localhost):'
    password=$reply
    if [[ -z $password ]]; then
      if local_origin; then break; fi
      printf 'A password is required for remote access.\n' >&3
      continue
    fi
    [[ ${#password} -ge 16 && $password != *[!\ -~]* ]] && break
    printf 'Use at least 16 printable ASCII characters.\n' >&3
  done
  mkdir -p "$(dirname "$install_dir")"
  git init --quiet "$install_dir"
  git -C "$install_dir" remote add origin https://github.com/aatbit/xflog.git
  git -C "$install_dir" fetch --depth 1 origin "$reference"
  git -C "$install_dir" checkout --quiet --detach FETCH_HEAD
  [[ -f $install_dir/compose.yaml && -f $install_dir/uv.lock ]] || die 'The fetched source is not a complete XFlog checkout.'
  chmod 700 "$install_dir"
  write_environment
  if [[ $mode == docker ]]; then write_network; else write_unit; fi
  printf '\nPrepared %s installation at %s\nBrowser: %s\nCredentials: %s/.env (0600; not displayed)\n' "$mode" "$install_dir" "$origin" "$install_dir" >&3
  if [[ $mode == docker ]]; then
    printf 'Compose project: %s; extra network: %s. Restarts when Docker starts.\n' "$project" "${network:-none}" >&3
    compose config --quiet
  else
    printf 'User service: %s/xflog.service; data: %s\nBoot startup uses loginctl enable-linger; it may request administrator authorization.\n' "$unit_dir" "$data_dir" >&3
  fi
  printf 'Check X API eligibility, credits, spending limits and auto-recharge before Start tracking.\nFresh installs do not start X collection; reused databases retain their saved Start choice.\n' >&3
  ask 'Activate this installation now? [y/N]'
  [[ $reply == y || $reply == Y ]] || { printf 'Canceled before activation. Prepared files remain for review.\n' >&3; return; }
  if [[ $mode == docker ]]; then
    start_runtime
  else
    install_native
  fi
  printf '\nXFlog is running at %s\n' "$origin" >&3
  if [[ -n $password ]]; then
    printf 'Browser username: xflog. Password is saved in %s/.env\n' "$install_dir" >&3
  else
    printf 'Local password protection is disabled.\n' >&3
  fi
}

if [[ ${BASH_SOURCE[0]:-} == "$0" || -z ${BASH_SOURCE[0]:-} ]]; then main "$@"; fi
