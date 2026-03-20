#!/usr/bin/env bash
# Install Centurion as a macOS LaunchAgent (auto-start on boot, auto-restart on crash).
#
# Usage:
#   ./scripts/install-launchd.sh              # install & start
#   ./scripts/install-launchd.sh --uninstall  # stop & remove
#
set -euo pipefail

LABEL="com.eddie.centurion"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
LOG_FILE="/tmp/centurion.log"
HOST="${CENTURION_HOST:-0.0.0.0}"
PORT="${CENTURION_PORT:-8100}"

# ── Uninstall ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    echo "Stopping and removing ${LABEL}..."
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Done. Centurion LaunchAgent removed."
    exit 0
fi

# ── Preflight checks ────────────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Error: venv not found at ${VENV_DIR}"
    echo "Run: uv venv && uv pip install -e '.[dev]'  in the project root first."
    exit 1
fi

CENTURION_BIN="${VENV_DIR}/bin/centurion"
if [[ ! -x "$CENTURION_BIN" ]]; then
    echo "Error: centurion CLI not found at ${CENTURION_BIN}"
    echo "Run: uv pip install -e .  in the project root first."
    exit 1
fi

# ── Stop existing service if running ─────────────────────────────────────────
if launchctl list "$LABEL" &>/dev/null; then
    echo "Stopping existing ${LABEL}..."
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || \
        launchctl unload "$PLIST" 2>/dev/null || true
fi

# ── Generate plist ───────────────────────────────────────────────────────────
mkdir -p "$(dirname "$PLIST")"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>${HOME}/.local/bin:${VENV_DIR}/bin:/opt/homebrew/bin:/usr/local/bin:/usr/sbin:/usr/bin:/bin</string>
	</dict>
	<key>KeepAlive</key>
	<true/>
	<key>Label</key>
	<string>${LABEL}</string>
	<key>ProgramArguments</key>
	<array>
		<string>${CENTURION_BIN}</string>
		<string>up</string>
		<string>--host</string>
		<string>${HOST}</string>
		<string>--port</string>
		<string>${PORT}</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>StandardErrorPath</key>
	<string>${LOG_FILE}</string>
	<key>StandardOutPath</key>
	<string>${LOG_FILE}</string>
	<key>WorkingDirectory</key>
	<string>${PROJECT_DIR}</string>
</dict>
</plist>
EOF

# ── Load and start ───────────────────────────────────────────────────────────
launchctl load "$PLIST"

echo "Centurion LaunchAgent installed and started."
echo "  Label:   ${LABEL}"
echo "  Port:    ${PORT}"
echo "  Log:     ${LOG_FILE}"
echo "  Plist:   ${PLIST}"
echo ""
echo "To uninstall:  $0 --uninstall"
