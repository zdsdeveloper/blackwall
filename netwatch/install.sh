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

# The reference the integrity check compares against. Kept beside the package
# rather than in /etc, so an edit to the live unit has something to differ from.
install -m 0644 "$here/units/blackwall-netwatch.service" \
  /usr/local/lib/blackwall-netwatch/blackwall-netwatch.service

install -d -m 0755 /var/lib/blackwall

# Created only if it is not already there. Once the blocklist is append-only,
# chmod on it returns EPERM -- the same kernel restriction the ledger's fchmod
# is guarded against -- so an unconditional chmod fails on exactly the armed
# system the installer most needs to work on, and under `set -e` takes the rest
# of the install down with it: the code lands, the daemon is never restarted,
# and the update looks applied while the old process keeps serving. Updating
# mtime is still permitted, which is why `touch` succeeds and hides it.
if [[ ! -e /var/lib/blackwall/blocklist ]]; then
  touch /var/lib/blackwall/blocklist
  chmod 0644 /var/lib/blackwall/blocklist
fi

systemctl daemon-reload
systemctl enable blackwall-netwatch.service

# Not `enable --now`: on a service that is already running that is a no-op, so a
# reinstall would copy the new code in and leave the old process serving it --
# an update that looks applied and is not.
#
# Once the unit is armed, `restart` is refused, because stopping is exactly what
# arming forbids. Signalling it is not: Restart=always turns a TERM into a fresh
# process on the new code. The wall never comes down, it only comes back newer.
systemctl restart blackwall-netwatch.service 2>/dev/null ||
  systemctl kill --signal=TERM blackwall-netwatch.service

# Wait for it to come back before reporting anything. The kill returns the
# instant the signal is delivered and Restart=always takes a couple of seconds,
# so a status printed here shows the OLD process dying and never the new one
# running: "activating (auto-restart)" over "code=killed, signal=TERM", which is
# what a SUCCESSFUL install looks like and reads exactly like a failed one.
for _ in $(seq 1 40); do
  [[ $(systemctl show blackwall-netwatch.service -P ActiveState) == active ]] && break
  sleep 0.25
done
systemctl --no-pager --lines=0 status blackwall-netwatch.service || true

# What the operator actually wants to know: not that a process exists, but that
# the wall is up and what it currently holds.
echo
netwatchctl status || true
