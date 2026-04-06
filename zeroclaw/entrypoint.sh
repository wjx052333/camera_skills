#!/bin/sh
set -e

# ── Camera config ────────────────────────────────────────────────────────────
# camera.py reads CONFIG_PATH = Path(__file__).parent / "camera_config.ini"
# so this file must live next to the script.
cat > /zeroclaw-data/workspace/skills/camera-control/scripts/camera_config.ini << EOF
[camera]
ip = ${CAMERA_IP:-192.168.0.100}
port = ${CAMERA_PORT:-80}
username = ${CAMERA_USERNAME:-admin}
password = ${CAMERA_PASSWORD:-admin}
EOF
echo "[zeroclaw-camera] camera_config.ini written (${CAMERA_IP:-192.168.0.100}:${CAMERA_PORT:-80})"

# ── ZeroClaw config ──────────────────────────────────────────────────────────
# Rewritten on every start so env vars always take precedence over any
# previously persisted values in the named volume.
mkdir -p /zeroclaw-data/.zeroclaw
cat > /zeroclaw-data/.zeroclaw/config.toml << EOF
workspace_dir       = "/zeroclaw-data/workspace"
config_path         = "/zeroclaw-data/.zeroclaw/config.toml"
api_key             = "${API_KEY}"
default_provider    = "${PROVIDER:-anthropic}"
default_model       = "${ZEROCLAW_MODEL:-claude-sonnet-4-6}"
default_temperature = 0.7

[gateway]
port              = 42617
host              = "[::]"
allow_public_bind = true
require_pairing   = false

[autonomy]
level = "supervised"
auto_approve = [
  "file_read", "file_write", "file_edit",
  "memory_recall", "memory_store",
  "web_search_tool", "web_fetch",
  "calculator", "glob_search", "content_search",
]

[skills]
# camera-control contains Python scripts — must opt in
allow_scripts = true
EOF
echo "[zeroclaw-camera] config.toml written (provider=${PROVIDER:-anthropic} model=${ZEROCLAW_MODEL:-claude-sonnet-4-6})"

exec zeroclaw "$@"
