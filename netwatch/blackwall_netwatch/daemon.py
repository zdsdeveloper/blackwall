"""The wall itself.

Enforcement is a repair loop, not an event handler: whatever the file says, make
it say the right thing again. That means a change made while the daemon was
stopped is caught the moment it starts, and it means there is no edit-detection
race to lose.
"""

import dataclasses
import os
import subprocess

from . import blocklist, hosts, ledger, provenance, zenpolicy


# The socket is 0666 by design -- anyone on this machine may add a domain -- so
# the blocklist is a resource an unprivileged loop can grow without limit. An
# unbounded file is read whole by domains() on every enforcement and on every
# start, so the end state is a daemon that OOMs at boot: the wall down for good
# and needing a root shell to repair.
MAX_DOMAINS = 50000


class BlocklistFull(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Paths:
    blocklist: str
    ledger: str
    hosts: str
    zen_policy: str
    zen_package_policy: str
    window_marker: str
    pacman_lock: str
    socket: str


def flush_resolver_cache():
    """systemd-resolved answers from cache, so a name blocked a moment ago can
    keep resolving until its TTL runs out -- exactly when the block is wanted.

    Best effort by design: on a machine not running resolved this is a no-op,
    and a failure here must never be louder than the enforcement it follows.
    """
    # Only root can flush resolved's cache, and an unprivileged call does not
    # fail fast -- it blocks on polkit waiting for an authentication agent a
    # daemon has not got. The check is about not stalling, not about permission.
    if os.geteuid() != 0:
        return
    try:
        subprocess.run(
            ["resolvectl", "flush-caches"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


class NetWatch:
    def __init__(self, paths, flusher=flush_resolver_cache,
                 proc_dir=provenance.PROC_DIR):
        self.paths = paths
        self.flusher = flusher
        self.proc_dir = proc_dir
        # Set by add(), consumed by the next enforce(). An add changes the
        # blocklist, so the enforcement it triggers finds the managed files
        # disagreeing with it -- which is indistinguishable, to the classifier,
        # from someone having edited them. Without this the operator blocking a
        # site would file a breach against themselves.
        self._applied_pending = False
        # Consecutive failed enforcement cycles. The server owns it; status
        # reports it. A wall that has stopped being repaired has to be visible
        # somewhere, or "the daemon is up" reads as "the wall is up".
        self.enforce_failures = 0

    def domains(self):
        try:
            # errors="replace" for the same reason ledger.read uses it: a
            # corrupted blocklist must cost the unreadable bytes, never the
            # daemon. A replacement character fails normalisation, so parse()
            # drops that line and keeps the rest.
            with open(self.paths.blocklist, encoding="utf-8", errors="replace") as f:
                return blocklist.parse(f.read())
        except (OSError, ValueError):
            return []

    def add(self, raw):
        domain = blocklist.normalize(raw)
        current = self.domains()
        if domain not in current:
            if len(current) >= MAX_DOMAINS:
                raise BlocklistFull(
                    "blocklist is at its %d-domain limit" % MAX_DOMAINS)
            fd = os.open(
                self.paths.blocklist,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
                0o644,
            )
            try:
                os.write(fd, (domain + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            ledger.record(self.paths.ledger, "added", domain=domain)
            # The enforcement this causes is our own work, not tampering: the
            # managed files are about to differ from the blocklist because we
            # just changed the blocklist. Consumed by the next enforce().
            self._applied_pending = True
        return domain

    def enforce(self):
        self._reap_dead_window()
        domains = self.domains()
        targets = []
        if hosts.apply(self.paths.hosts, domains):
            targets.append("hosts")
            self.flusher()
        package = zenpolicy.read_package_policies(self.paths.zen_package_policy)
        if zenpolicy.apply(self.paths.zen_policy, package):
            targets.append("zen_policy")
        if not targets:
            return {"changed": False, "verdict": None, "targets": []}
        # Consumed unconditionally, whatever verdict wins below: a flag left
        # set outlives the enforcement it was raised for, and the next hand
        # edit would be excused as our own work -- a hole in the wall.
        applied = self._applied_pending
        self._applied_pending = False
        if not self._enforced_before():
            # A machine that has never been enforced is being installed, and an
            # install is an install even when an add is what triggered it.
            verdict = "init"
        elif applied:
            verdict = "applied"
        else:
            verdict = provenance.classify(
                self.paths.window_marker, self.paths.pacman_lock,
                proc_dir=self.proc_dir)
        ledger.record(self.paths.ledger, verdict, targets=targets)
        return {"changed": True, "verdict": verdict, "targets": targets}

    def _enforced_before(self):
        # The ledger is the record of whether this machine has ever been in a
        # good state. It is append-only and root-owned, so answering this
        # question dishonestly costs more than the answer is worth.
        return any(
            e.get("kind") in ("init", "applied", "drift", "breach")
            for e in ledger.read(self.paths.ledger)
        )

    def _reap_dead_window(self):
        """Keep the sanctioned transaction window honest.

        A transaction that is aborted never runs its PostTransaction hook, so
        the marker is left behind and every hand edit for the next half hour
        reads as drift. A transaction that outlives the staleness bound has its
        window expire underneath it, and ends in a false breach. Both are the
        same question, asked here once: is a transaction actually still running?
        """
        if not os.path.exists(self.paths.window_marker):
            return
        alive = (os.path.exists(self.paths.pacman_lock)
                 or provenance.transaction_alive(self.proc_dir))
        try:
            if alive:
                os.utime(self.paths.window_marker, None)
            else:
                os.unlink(self.paths.window_marker)
        except OSError:
            pass

    def close_window(self):
        """Drop the sanctioned-transaction marker.

        Only ever called after an enforcement that actually completed. The hook
        used to remove this itself, which meant a failed or undelivered enforce
        left changed files behind with no window open -- and the next cycle
        called a routine system upgrade a breach.
        """
        try:
            os.unlink(self.paths.window_marker)
        except OSError:
            pass

    def status(self):
        entries = ledger.read(self.paths.ledger)
        return {
            "domains": len(self.domains()),
            # .get, matching _enforced_before: a truncated or hand-written
            # ledger line without a "kind" must not take status down with it.
            "breaches": len([e for e in entries if e.get("kind") == "breach"]),
            "enforce_failures": self.enforce_failures,
        }
