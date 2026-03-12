#!/usr/bin/env bash
set -euo pipefail

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/xdg-runtime}"
mkdir -p "${XDG_RUNTIME_DIR}"
chmod 700 "${XDG_RUNTIME_DIR}"

echo "[startup] validating MuseScore runtime libraries"
ldconfig -p | grep -E 'lib(OpenGL|jack|nss3|wayland-client)\.so' || true

pulseaudio --daemonize --exit-idle-time=-1
Xvfb :99 -screen 0 1280x1024x24 -ac +render -noreset &
sleep 3

exec python3 server.py
