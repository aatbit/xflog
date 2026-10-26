#!/usr/bin/env bash
set +x
set -Eeuo pipefail
umask 077
export LC_ALL=C

die() { printf 'XFlog: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Install $1 first, then run this installer again."; }
ask() { IFS= read -r -u 3 -p "$1 " reply || die 'Input closed; installation canceled.'; }
secret() {
  IFS= read -r -s -u 3 -p "$1 " reply || die 'Input closed; installation canceled.'
  printf '\n' >&3
}
valid_port() { [[ $1 =~ ^[0-9]{1,5}$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535)); }
valid_path() { [[ $1 == /* && $1 != / && $1 =~ ^/[A-Za-z0-9_./-]+$ ]]; }
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
  {
    env_line X_APP_BEARER_TOKEN "$bearer"
    env_line X_USER_ID "$user_id"
    env_line X_USER_ACCESS_TOKEN "$user_token"
    env_line XFLOG_ADMIN_PASSWORD "$password"
    env_line XFLOG_ORIGIN "$origin"
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
}

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

install_native() (
  local bootstrap_dir
  bootstrap_dir=$(mktemp -d "${TMPDIR:-/tmp}/xflog-bootstrap.XXXXXX")
  trap 'rm -rf -- "$bootstrap_dir"' EXIT
  "$python" -m venv "$bootstrap_dir"
  "$bootstrap_dir/bin/python" -m pip install --disable-pip-version-check --quiet 'uv==0.11.29'
  "$bootstrap_dir/bin/uv" sync --project "$install_dir" --locked --no-dev --no-editable --python "$python"
  mkdir -p "$data_dir" "$HOME/.local/share/xflog/locks" "$unit_dir"
  chmod 700 "$data_dir"
  systemd-analyze --user verify "$install_dir/xflog.service"
  if [[ $(loginctl show-user "$(id -un)" -p Linger --value) != yes ]]; then
    if ! loginctl enable-linger "$(id -un)"; then
      need sudo
      sudo loginctl enable-linger "$(id -un)"
    fi
  fi
  [[ ! -e $unit_dir/xflog.service ]] || die 'A user xflog.service already exists; not overwriting it.'
  install -m 600 "$install_dir/xflog.service" "$unit_dir/xflog.service"
  systemctl --user daemon-reload
  systemctl --user enable --now xflog.service
  local attempt
  for ((attempt=0; attempt<30; attempt++)); do
    if systemctl --user is-active --quiet xflog.service &&
      XFLOG_PORT="$port" XFLOG_ORIGIN="$origin" "$install_dir/.venv/bin/python" -m xflog.healthcheck; then
      return 0
    fi
    sleep 1
  done
  die 'Service did not become healthy. Inspect: journalctl --user -u xflog.service'
)

main() {
  if [[ ${1:-} == --help ]]; then
    printf '%s\n' 'XFlog interactive installer: Docker Compose or native Linux/systemd user service.' \
      'Requires Bash, git and an interactive terminal. Docker mode needs Docker Compose v2.' \
      'Native mode needs Python 3.12+, venv/pip and a working systemd user session.' \
      'Optional: XFLOG_REF=branch/tag/commit (default: main). Existing installs are never overwritten.'
    return
  fi
  [[ $# == 0 ]] || die 'Only --help is supported.'
  exec 3<> /dev/tty || die 'An interactive terminal is required (including for curl | bash).'
  need git
  local mode port origin install_dir bearer user_id user_token password network='' project='' python='' data_dir='' unit_dir=''
  local reference=${XFLOG_REF:-main}
  [[ $reference =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || die 'Invalid XFLOG_REF.'
  printf '\nXFlog — interactive setup\nNo X login is performed. Full functionality requires an externally obtained user access token.\n' >&3
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
    ask 'Python 3.12+ executable? [python3]'
    python=$(command -v "${reply:-python3}") || die 'Python executable not found.'
    "$python" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ is required"; import venv, ensurepip'
    unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
    [[ ! -e $unit_dir/xflog.service ]] || die 'A user xflog.service already exists; not overwriting it.'
  fi
  while :; do
    ask "Installation directory? [$HOME/.local/share/xflog/app]"
    install_dir=${reply:-$HOME/.local/share/xflog/app}
    install_dir=${install_dir/#\~/$HOME}; install_dir=${install_dir%/}
    valid_path "$install_dir" || { printf 'Use an absolute path with letters, digits, /, ., _ and - only.\n' >&3; continue; }
    [[ ! -e $install_dir ]] || die 'Installation path already exists. Choose a fresh path; existing data is never overwritten.'
    break
  done
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
    [[ -z $(docker ps -aq --filter "label=com.docker.compose.project=$project") ]] || die 'This Compose project already has containers; choose a different project.'
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
  secret 'X user access token (required for full functionality; blank to skip):'
  user_token=$reply
  [[ $user_token != *[!\!-~]* ]] || die 'Tokens must contain only printable ASCII without spaces.'
  [[ -n $bearer || -z $user_token ]] || die 'A user token also requires the app bearer token and user ID.'
  while :; do
    secret 'Instance password, 16+ ASCII characters (blank to generate and save privately):'
    password=$reply
    if [[ -z $password ]]; then
      password=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
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
    compose up -d --build --wait --wait-timeout 120
  else
    install_native
  fi
  printf '\nXFlog is running at %s\nInstance username: xflog. Password is saved in %s/.env\n' "$origin" "$install_dir" >&3
}

if [[ ${BASH_SOURCE[0]:-} == "$0" || -z ${BASH_SOURCE[0]:-} ]]; then main "$@"; fi
