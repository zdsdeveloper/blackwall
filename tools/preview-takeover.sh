#!/usr/bin/env bash
# Watch the lock's opening sequence on a loop, without engaging a lock.
#
# Captures the desktop the way Service.qml does, then runs the real
# TakeoverView over it in an ordinary window until you close it. Nothing here
# touches the session lock, the daemon, or any state.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
shot="${XDG_RUNTIME_DIR:-/tmp}/blackwall-preview.png"

command -v grim >/dev/null || { echo "grim is needed to capture the desktop" >&2; exit 1; }
grim -l 0 -t png "$shot"
trap 'rm -f "$shot"' EXIT

echo "looping the takeover — close the window to stop"
BW_PREVIEW_SHOT="$shot" qs -p "$here/../preview-takeover.qml" -n
