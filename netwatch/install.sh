#!/bin/bash
# Install NetWatch. From the repo root: ./netwatch/install.sh
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.sh"

# Omarchy's own privileged helpers use this shape -- see
# /usr/bin/omarchy-theme-set-browser-policy. sudo when a terminal is attached to
# take the password, pkexec when one is not: an agent or a graphical launcher
# has nowhere to type it.
require_root() {
  if (( EUID == 0 )); then
    return
  elif [[ -t 0 ]]; then
    exec sudo "$SELF" "$@"
  else
    exec pkexec "$SELF" "$@"
  fi
}
require_root "$@"

# Root phase: a dev link can prepend a user-writable bin/ to secure_path, so
# pin PATH before calling install, cp or systemctl by bare name.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install -d -m 0755 /usr/local/lib/blackwall-netwatch
cp -r "$here/blackwall_netwatch" /usr/local/lib/blackwall-netwatch/
install -m 0755 "$here/bin/blackwall-netwatch" /usr/local/bin/blackwall-netwatch
install -m 0755 "$here/bin/netwatchctl"        /usr/local/bin/netwatchctl
install -m 0755 "$here/bin/netwatch-hook"      /usr/local/bin/netwatch-hook

install -d -m 0755 /etc/pacman.d/hooks
install -m 0644 "$here/hooks/"*.hook /etc/pacman.d/hooks/
install -m 0644 "$here/units/blackwall-netwatch.service" /etc/systemd/system/

install -d -m 0755 /var/lib/blackwall
touch /var/lib/blackwall/blocklist
chmod 0644 /var/lib/blackwall/blocklist

systemctl daemon-reload
systemctl enable --now blackwall-netwatch.service
systemctl --no-pager --lines=5 status blackwall-netwatch.service
