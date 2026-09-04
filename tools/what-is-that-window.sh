#!/usr/bin/env bash
# Identify a window that has appeared and will not go away.
#
# Run it while the offending window is on screen. It prints every window with
# its class, title, size and the exact command line of the process behind it,
# which is normally enough to say what opened it -- a stray harness, a leftover
# preview, or something the shell itself put up.
#
# The last section lists Quickshell processes that are NOT the omarchy shell,
# which is where a leaked preview or test harness shows up.
set -uo pipefail

echo "=== windows ==="
hyprctl clients -j | python3 -c '
import json, sys, os
for c in json.load(sys.stdin):
    pid = c.get("pid", 0)
    cmd = ""
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        cmd = "(gone)"
    print("  class : %s" % c.get("class"))
    print("  title : %r" % c.get("title"))
    print("  size  : %s   pid: %s" % (c.get("size"), pid))
    print("  cmd   : %s" % cmd[:160])
    print()
'

echo "=== quickshell processes that are not the omarchy shell ==="
found=0
while read -r pid cmd; do
  case "$cmd" in
    *"/usr/share/omarchy/shell"*) continue ;;
  esac
  echo "  pid $pid: $cmd"
  found=1
done < <(pgrep -a quickshell 2>/dev/null | grep -v snapshot)
[[ $found -eq 0 ]] && echo "  none — nothing of ours is leaking"

echo
echo "To stop a leaked one:  kill <pid>"
