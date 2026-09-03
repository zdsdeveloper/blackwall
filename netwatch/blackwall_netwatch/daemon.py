"""The wall itself.

Enforcement is a repair loop, not an event handler: whatever the file says, make
it say the right thing again. That means a change made while the daemon was
stopped is caught the moment it starts, and it means there is no edit-detection
race to lose.
"""

import dataclasses
import os
import subprocess
import time

from . import (blocklist, hosts, integrity, ladder, ledger, provenance,
               session, zenpolicy)


# The socket is 0666 by design -- anyone on this machine may add a domain -- so
# the blocklist is a resource an unprivileged loop can grow without limit. An
# unbounded file is read whole by domains() on every enforcement and on every
# start, so the end state is a daemon that OOMs at boot: the wall down for good
# and needing a root shell to repair.
MAX_DOMAINS = 50000

# How recently a breach must have been recorded for the start grace to be
# considered already spent. The grace is for a daemon coming up in the middle
# of a package transaction, not for a daemon coming up for the fifth time in a
# minute with a weakening still standing behind it.
GRACE_DENIED_AFTER_BREACH_SECONDS = 10 * 60

# How long a sanctioned window outlives the transaction behind it. pacman drops
# db.lck and exits before the daemon's next cycle notices, and a PostTransaction
# repair that did not land needs somewhere to land: without this grace the tail
# of a real upgrade is a breach, and a breach is the expensive direction.
WINDOW_GRACE_SECONDS = 60


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
    unit_file: str
    unit_source: str
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
                 proc_dir=provenance.PROC_DIR, notifier=session.notify):
        self.paths = paths
        self.flusher = flusher
        self.proc_dir = proc_dir
        self.notifier = notifier
        # Half of the grace for the cycle that runs as the daemon comes up. A
        # restart in the middle of a package transaction finds the managed
        # files part-written and used to read that as a pair of hands; in
        # Phase 2 reading it that way is a locked screen for rebooting. The
        # first cycle records what it finds and escalates nothing.
        #
        # Only half, because this half lives in memory and a restart mints a
        # fresh one. `systemctl kill` is not a stop job, Restart=always brings
        # the daemon straight back, and a loop of that would hand out a free
        # pass every few seconds while breaches piled up. The other half is
        # _start_grace_available, which asks the ledger.
        self._first_enforcement = True
        # What was missing on the previous cycle. A weakening the repair loop
        # cannot undo -- a masked unit, above all -- is still there next cycle
        # and the one after, and re-recording it each time would fire the
        # ladder every thirty seconds for as long as it stands.
        self._last_reasons = None
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
        # Asked before the repair, because the repair is what destroys the
        # evidence: once hosts.apply has put the sink lines back, nothing on
        # disk still says they were missing a moment ago. This is the whole
        # difference between Phase 1 and Phase 2 -- the question is no longer
        # "did the text change" but "was a protection actually missing".
        reasons = integrity.weakened(
            self.paths.hosts, domains, self.paths.zen_policy,
            self.paths.unit_file, self.paths.unit_source)
        targets = []
        if hosts.apply(self.paths.hosts, domains):
            targets.append("hosts")
            self.flusher()
        package = zenpolicy.read_package_policies(self.paths.zen_package_policy)
        if zenpolicy.apply(self.paths.zen_policy, package):
            targets.append("zen_policy")
        # Spent by the cycle it belongs to, whether or not that cycle found
        # anything: a grace that survives every quiet cycle is not a grace for
        # the start, it is a free pass held in reserve for the first breach of
        # the day, whenever that comes.
        first = self._first_enforcement
        self._first_enforcement = False
        # Subset, not equality. A reason set that has only shrunk is the same
        # standing weakening with one of its parts repaired, not a new one:
        # equality would file a second breach for the leftover the moment the
        # repairable half went away, and that second entry raises the rung for
        # the whole of the ladder's window.
        standing = (self._last_reasons is not None
                    and set(reasons) <= set(self._last_reasons))
        self._last_reasons = reasons
        if not targets and (not reasons or standing):
            # Nothing was repaired, and nothing is missing that was not already
            # missing and already recorded last cycle. The second half is what
            # keeps a weakening outside the repair loop's reach -- a unit that
            # is no longer the one we installed -- from being filed afresh on
            # every cycle for as long as it stands.
            #
            # The add() excuse is consumed here too. The flag is spent by the
            # enforcement it was raised for whether or not that enforcement
            # found anything to do; left set past an empty cycle it excuses the
            # NEXT hand edit as our own work, which is a hole in the wall.
            self._applied_pending = False
            return {"changed": False, "verdict": None, "targets": []}
        # Read once and used twice, for the grace and for whether this machine
        # has ever been in a good state. _escalate reads it again, but only
        # after the entry below has landed: the rung has to count the breach
        # being escalated.
        entries = ledger.read(self.paths.ledger)
        first = first and self._start_grace_available(entries)
        # Consumed unconditionally, whatever verdict wins below: a flag left
        # set outlives the enforcement it was raised for, and the next hand
        # edit would be excused as our own work -- a hole in the wall.
        applied = self._applied_pending
        self._applied_pending = False
        if not self._enforced_before(entries):
            # A machine that has never been enforced is being installed, and an
            # install is an install even when an add is what triggered it.
            verdict = "init"
        elif applied:
            verdict = "applied"
        elif not reasons:
            # Something changed but no protection was missing: an unrelated
            # edit, a reordering. Repaired, recorded, never punished.
            verdict = "repair"
        else:
            verdict = provenance.classify(
                self.paths.window_marker, self.paths.pacman_lock,
                proc_dir=self.proc_dir)
        ledger.record(self.paths.ledger, verdict, targets=targets,
                      reasons=reasons)
        if verdict == "breach" and not first:
            self._escalate(reasons)
        return {"changed": bool(targets), "verdict": verdict,
                "targets": targets, "reasons": reasons}

    def _escalate(self, reasons):
        """Fire the ladder for a breach just recorded.

        Only for a NEW breach: a standing one must not re-fire every cycle, or
        an unanswered challenge reappears every thirty seconds until the
        operator kills the shell to stop it -- which teaches them that killing
        the shell is how you deal with the Blackwall.
        """
        entries = ledger.read(self.paths.ledger)
        step = ladder.rung(entries)
        try:
            if step == ladder.LOCK:
                self.notifier("engage", [str(ladder.LOCK_SECONDS)])
            else:
                self.notifier("challenge", [reasons[0] if reasons else "breach"])
        except Exception:
            # No session, no shell, no screen to lock. That is an ordinary
            # outcome rather than an error: the breach stays unacknowledged and
            # the plugin picks it up when it next starts.
            pass

    def _enforced_before(self, entries=None):
        # The ledger is the record of whether this machine has ever been in a
        # good state. It is append-only and root-owned, so answering this
        # question dishonestly costs more than the answer is worth.
        if entries is None:
            entries = ledger.read(self.paths.ledger)
        return any(
            e.get("kind") in ("init", "applied", "drift", "breach")
            for e in entries
        )

    def _start_grace_available(self, entries, now=None):
        """Is the first-cycle grace still honest?

        The grace exists so a daemon coming up in the middle of a package
        transaction does not read part-written files as a pair of hands. It is
        not meant to survive a restart loop: a breach recorded minutes ago is a
        weakening that is still standing, and handing a fresh free pass to
        every restart would hold the ladder at zero for as long as the restarts
        kept coming.

        A legitimate mid-transaction restart still has its grace. What it has
        on the record is drift or applied, not a breach.
        """
        now = time.time() if now is None else now
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("kind") != "breach":
                continue
            at = entry.get("at")
            # bool is an int in Python, and a True here would read as an
            # ancient timestamp rather than the malformed entry it is.
            if isinstance(at, bool) or not isinstance(at, (int, float)):
                continue
            # Both ends, as the ladder does it: a future-dated entry gives a
            # negative age, and an upper bound alone would let one deny the
            # grace for ever.
            if 0 <= now - at <= GRACE_DENIED_AFTER_BREACH_SECONDS:
                return False
        return True

    def _reap_dead_window(self):
        """Keep the sanctioned transaction window honest.

        A window stays open only while a transaction actually is. When one is
        not, the marker is given a short grace before it goes: pacman exits a
        moment before the daemon notices, and cutting the window the instant it
        does would turn the tail of a real upgrade into a breach. After the
        grace it is removed, so an aborted transaction cannot leave the wall
        excusing hand edits for half an hour.
        """
        try:
            age = time.time() - os.stat(self.paths.window_marker).st_mtime
        except OSError:
            return
        if provenance.transaction_in_progress(
                self.paths.pacman_lock, proc_dir=self.proc_dir):
            try:
                os.utime(self.paths.window_marker, None)
            except OSError:
                pass
        elif age > WINDOW_GRACE_SECONDS:
            try:
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
        domains = self.domains()
        return {
            "domains": len(domains),
            # .get, matching _enforced_before: a truncated or hand-written
            # ledger line without a "kind" must not take status down with it.
            "breaches": len([e for e in entries if e.get("kind") == "breach"]),
            "enforce_failures": self.enforce_failures,
            "unacknowledged": ladder.unacknowledged(entries),
            "weakened": integrity.weakened(
                self.paths.hosts, domains, self.paths.zen_policy,
                self.paths.unit_file, self.paths.unit_source),
        }
