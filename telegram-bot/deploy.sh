#!/usr/bin/env bash
# DIY-VPN Telegram bot deployer.
# Run this from telegram-bot/ on YOUR LOCAL MACHINE after the VPN itself is
# already deployed (you need its app name + a Fly API token).
#
# Prereqs:
#   - flyctl installed and logged in
#   - jq installed
#   - You've already created a Telegram bot via @BotFather and have the token
#   - You know your Telegram user ID (use @userinfobot or the /whoami command
#     on the bot once it's running)
#
# Env vars you can override:
#   BOT_APP_NAME    (default: <vpn-app>-bot)        Fly app name for the bot
#   VPN_APP_NAME    (required)                      The VPN app this bot controls
#   REGION          (default: same as VPN, fallback nrt)
#   TG_BOT_TOKEN    (prompted if unset)
#   TG_ALLOWED_USERS(prompted if unset)
#
# Examples:
#   VPN_APP_NAME=diyvpn-sgad ./deploy.sh
#   VPN_APP_NAME=diyvpn-sgad TG_BOT_TOKEN=123:abc TG_ALLOWED_USERS=1234567 ./deploy.sh

set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; CYA='\033[0;36m'; BLD='\033[1m'; RST='\033[0m'
log()   { echo -e "${CYA}[*]${RST} $*"; }
ok()    { echo -e "${GRN}[OK]${RST} $*"; }
warn()  { echo -e "${YLW}[!]${RST} $*"; }
fatal() { echo -e "${RED}[X]${RST} $*" >&2; exit 1; }

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

command -v flyctl >/dev/null 2>&1 || fatal "flyctl not installed."
command -v jq     >/dev/null 2>&1 || fatal "jq not installed."
flyctl auth whoami >/dev/null 2>&1 || fatal "Not logged in to Fly. Run: flyctl auth login"

#─── Inputs ───────────────────────────────────────────────────────────────────
VPN_APP_NAME="${VPN_APP_NAME:-}"
if [[ -z "$VPN_APP_NAME" ]]; then
  read -rp "Your VPN's Fly app name (e.g. diyvpn-sgad): " VPN_APP_NAME
fi
[[ -n "$VPN_APP_NAME" ]] || fatal "VPN_APP_NAME is required."

# Sanity-check the VPN app exists.
flyctl apps list --json | jq -e --arg n "$VPN_APP_NAME" '.[] | select(.Name == $n)' >/dev/null \
  || fatal "Fly app '$VPN_APP_NAME' not found in your account."

BOT_APP_NAME="${BOT_APP_NAME:-${VPN_APP_NAME}-bot}"
[[ "$BOT_APP_NAME" =~ ^[a-z][a-z0-9-]{1,28}[a-z0-9]$ ]] \
  || fatal "Invalid BOT_APP_NAME (must be 3-30 lowercase chars, start with a letter)."

# Try to get region from the VPN app's machines, else default.
REGION="${REGION:-}"
if [[ -z "$REGION" ]]; then
  REGION="$(flyctl machines list --app "$VPN_APP_NAME" --json 2>/dev/null \
            | jq -r '.[0].region // empty')"
  REGION="${REGION:-nrt}"
fi

# Telegram bot token
TG_BOT_TOKEN="${TG_BOT_TOKEN:-}"
if [[ -z "$TG_BOT_TOKEN" ]]; then
  cat <<EOF

To create your bot:
  1. Open Telegram, search for @BotFather, send /newbot
  2. Pick a name and a username (must end in 'bot', e.g. diyvpn_arinmay_bot)
  3. BotFather replies with a token like 1234567890:ABC-DEF...
  4. Paste that token below.
EOF
  read -rp "Telegram bot token: " TG_BOT_TOKEN
fi
[[ "$TG_BOT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] \
  || fatal "That doesn't look like a valid Telegram bot token."

# Allowed users
TG_ALLOWED_USERS="${TG_ALLOWED_USERS:-}"
if [[ -z "$TG_ALLOWED_USERS" ]]; then
  cat <<EOF

To find your Telegram user ID, open @userinfobot in Telegram and send /start.
You can list multiple IDs separated by commas (no spaces), e.g.: 1234567,7654321
EOF
  read -rp "Telegram user IDs allowed to use the bot: " TG_ALLOWED_USERS
fi
[[ "$TG_ALLOWED_USERS" =~ ^[0-9]+(,[0-9]+)*$ ]] \
  || fatal "Allowed users must be a comma-separated list of integers."

#─── Plan ─────────────────────────────────────────────────────────────────────
log "Plan:"
echo "  Bot app:       $BOT_APP_NAME"
echo "  VPN app:       $VPN_APP_NAME"
echo "  Region:        $REGION"
echo "  Allowed users: $TG_ALLOWED_USERS"
echo "  Bot token:     ${TG_BOT_TOKEN:0:8}...${TG_BOT_TOKEN: -4} (set as Fly secret)"
echo
read -rp "Proceed? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }

#─── 1) Create the bot's Fly app ──────────────────────────────────────────────
log "Creating Fly app for the bot..."
if flyctl apps list --json | jq -e --arg n "$BOT_APP_NAME" '.[] | select(.Name == $n)' >/dev/null; then
  ok "App $BOT_APP_NAME already exists -- reusing."
else
  flyctl apps create "$BOT_APP_NAME" --org personal
  ok "Bot app created."
fi

#─── 2) Mint a Fly API token the bot can use ─────────────────────────────────
# The bot needs to control the VPN app (start/stop, ips, ssh). We ask flyctl
# to mint a token scoped to both apps. If that subcommand doesn't behave on
# this flyctl version we fall back to a broader org token, then finally to
# the live auth token. We capture stderr so any failure is visible.
log "Creating Fly API token for the bot..."

mint_token() {
  # Print the raw token on stdout, diagnostic messages on stderr.
  # flyctl prints the token as a single quoted line, typically starting with
  # "FlyV1 fm2_..." — we grab the last non-empty line and strip quotes.
  local out
  if out="$(flyctl tokens create deploy --app "$VPN_APP_NAME" -x 8760h 2>&1)"; then
    printf '%s' "$out" | awk 'NF' | tail -1 | tr -d '"'
    return 0
  fi
  echo "[!] 'tokens create deploy' failed:" >&2
  printf '%s\n' "$out" >&2
  return 1
}

mint_token_org() {
  local out
  if out="$(flyctl tokens create org personal -x 8760h 2>&1)"; then
    printf '%s' "$out" | awk 'NF' | tail -1 | tr -d '"'
    return 0
  fi
  echo "[!] 'tokens create org personal' failed:" >&2
  printf '%s\n' "$out" >&2
  return 1
}

set +e
FLY_API_TOKEN="$(mint_token_org)"
set -e

# Validate: Fly tokens are long and start with FlyV1 (old) or fm2_ (new style).
if [[ -z "$FLY_API_TOKEN" || ${#FLY_API_TOKEN} -lt 40 ]]; then
  warn "Org-token mint failed or returned garbage -- trying auth token as fallback."
  FLY_API_TOKEN="$(flyctl auth token 2>/dev/null | tr -d '"' | awk 'NF' | tail -1)"
fi

if [[ -z "$FLY_API_TOKEN" || ${#FLY_API_TOKEN} -lt 40 ]]; then
  fatal "Could not obtain a Fly API token. Try manually:
    flyctl tokens create org personal -x 8760h
  then set it with:
    flyctl secrets set --app ${BOT_APP_NAME} FLY_API_TOKEN='...'"
fi
ok "Fly API token obtained (${#FLY_API_TOKEN} chars)."

#─── 3) Render fly.toml ───────────────────────────────────────────────────────
log "Rendering fly.toml..."
sed \
  -e "s|BOT_APP_NAME_PLACEHOLDER|${BOT_APP_NAME}|g" \
  -e "s|REGION_PLACEHOLDER|${REGION}|g" \
  -e "s|VPN_APP_NAME_PLACEHOLDER|${VPN_APP_NAME}|g" \
  fly.toml.template > fly.toml
ok "fly.toml written."

#─── 4) Set secrets BEFORE first deploy (so the machine boots with them) ──────
log "Setting Fly secrets on the bot app..."
flyctl secrets set --app "$BOT_APP_NAME" --stage \
  TG_BOT_TOKEN="$TG_BOT_TOKEN" \
  TG_ALLOWED_USERS="$TG_ALLOWED_USERS" \
  FLY_API_TOKEN="$FLY_API_TOKEN" \
  >/dev/null
ok "Secrets staged."

#─── 5) Deploy ────────────────────────────────────────────────────────────────
log "Deploying bot (~2-3 min for first build)..."
flyctl deploy --app "$BOT_APP_NAME" --ha=false --config fly.toml
ok "Bot deployed."

#─── 6) Summary ───────────────────────────────────────────────────────────────
echo
echo -e "${BLD}===================================================================${RST}"
echo -e "${BLD}  DIY-VPN Telegram bot is live${RST}"
echo -e "${BLD}===================================================================${RST}"
echo "  Bot app:   https://fly.io/apps/${BOT_APP_NAME}"
echo "  Logs:      flyctl logs --app ${BOT_APP_NAME}"
echo "  Restart:   flyctl machine restart \$(flyctl machines list --app ${BOT_APP_NAME} --json | jq -r '.[0].id')"
echo
echo "Open Telegram, find your bot, and send /start. If it replies, you're done."
echo "Send /help to see all commands."
echo -e "${BLD}===================================================================${RST}"
