"""The wall itself.

Enforcement is a repair loop, not an event handler: whatever the file says, make
it say the right thing again. That means a change made while the daemon was
stopped is caught the moment it starts, and it means there is no edit-detection
race to lose.
"""

import dataclasses
import hashlib
import os
import secrets
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
        # first cycle records what it finds as a graced start rather than as a
        # breach, so the ladder never sees it and nothing is delivered for it.
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
        #
        # Seeded from the ledger rather than starting empty, because this half
        # of the memory used to die with the process: a daemon restarted while
        # a masked unit still stood forgot it had already recorded it, filed the
        # same weakening a second time, and -- since a graced start counts
        # toward the rung -- turned one act of tampering into a lock.
        self._last_reasons = self._recorded_reasons()
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

    def _append_domain(self, domain):
        """Write one domain to the blocklist. The one writer, for add() and
        for a restore -- the file is append-only, so this is the whole of
        what either of them is allowed to do to it."""
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

    def add(self, raw):
        domain = blocklist.normalize(raw)
        current = self.domains()
        if domain not in current:
            if len(current) >= MAX_DOMAINS:
                raise BlocklistFull(
                    "blocklist is at its %d-domain limit" % MAX_DOMAINS)
            self._append_domain(domain)
            ledger.record(self.paths.ledger, "added", domain=domain)
            # The enforcement this causes is our own work, not tampering: the
            # managed files are about to differ from the blocklist because we
            # just changed the blocklist. Consumed by the next enforce().
            self._applied_pending = True
        return domain

    def enforce(self):
        self._reap_dead_window()
        domains = self.domains()
        # Read once, before `weakened` needs it, and reused below for
        # `_enforced_before` and `_start_grace_available` -- there is no
        # second or third read per cycle. `_deliver_pending` reads again
        # later, deliberately: the rung it computes has to count the entry
        # this cycle is about to write.
        entries = ledger.read(self.paths.ledger)
        # Asked before the repair, because the repair is what destroys the
        # evidence: once hosts.apply has put the sink lines back, nothing on
        # disk still says they were missing a moment ago. This is the whole
        # difference between Phase 1 and Phase 2 -- the question is no longer
        # "did the text change" but "was a protection actually missing".
        reasons = integrity.weakened(
            self.paths.hosts, domains, self.paths.zen_policy,
            self.paths.unit_file, self.paths.unit_source,
            ledger_entries=entries)
        targets = []
        restored = integrity.unblocked_domains(entries, domains)
        if restored:
            # Appending is permitted on an append-only file, which is what
            # makes deleting a line futile rather than merely detected: it is
            # back within the cycle, and the breach is recorded either way.
            for domain in restored:
                self._append_domain(domain)
            domains = self.domains()
            targets.append("blocklist")
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
            # Kept current even on a quiet cycle. A wall that has gone back to
            # intact must clear this, or a weakening repaired and then repeated
            # would read as the same one still standing and never be filed.
            self._last_reasons = reasons
            # Every cycle, not only the ones that found something. A breach
            # recorded while nobody was logged in is still waiting to be shown,
            # and the quiet cycle after the wall was repaired is exactly when a
            # session tends to appear.
            self._deliver_pending()
            return {"changed": False, "verdict": None, "targets": []}
        # The same read from the top of this cycle, used again here for the
        # grace and for whether this machine has ever been in a good state.
        # _deliver_pending reads afresh, but only after the entry below has
        # landed: the rung has to count the breach being delivered.
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
        recorded = verdict
        if verdict == "breach" and first:
            # The start grace, spent on the record rather than on the notice.
            # Delivery no longer belongs to the cycle that recorded the breach
            # -- an undelivered breach is handed over whenever a session next
            # appears -- so a breach recorded here would reach the screen one
            # cycle later and the grace would be worth thirty seconds. The
            # grace exists so a daemon coming up in the middle of a package
            # transaction does not read part-written files as a pair of hands,
            # and that means the ladder must not learn about this cycle at all.
            #
            # Recorded under its own kind rather than dropped: the restart-loop
            # defence below asks the ledger what the last start found, and a
            # cycle that left no trace would hand a fresh free pass to every
            # restart for as long as they kept coming. The verdict returned to
            # the caller is still the honest one.
            recorded = "graced"
        ledger.record(self.paths.ledger, recorded,
                      targets=targets, reasons=reasons)
        # The grace defers; it does not forgive. Leaving _last_reasons alone on
        # a graced cycle is what lets the NEXT cycle look at the same weakening
        # afresh and file it as a real breach -- which is the whole difference
        # between a package transaction that was half-written when we came up
        # (gone by the next cycle, so nothing is filed) and a masked unit that
        # was already in place (still there, so it is filed and shown).
        #
        # Without this, a weakening that existed before the daemon started was
        # recorded once, never delivered, and then suppressed as standing for
        # ever: silently tolerated, and counted against the operator without
        # ever being put in front of them.
        if recorded != "graced":
            self._last_reasons = reasons
        self._deliver_pending()
        return {"changed": bool(targets), "verdict": verdict,
                "targets": targets, "reasons": reasons}

    def _deliver_pending(self):
        """Hand an undelivered breach to the session, if there is one now.

        Delivery rather than firing: a breach recorded with no session up has
        not been seen, and must still be shown when one appears. Otherwise
        killing the shell before weakening the wall skips rung one entirely --
        the breach counts, nothing is ever shown, and the next weakening lands
        on the lock with nothing to explain it.

        A breach that WAS shown and then dismissed is delivered, and does not
        come back -- ignoring rung one is how the operator chooses rung two.

        The token is minted here, at the moment it is actually handed over, and
        carried to the plugin over the session IPC -- root to plugin, never
        through the 0666 socket -- so a matching ack proves the operator really
        saw it. Minting it here rather than when the breach was recorded is
        what lets a delivery deferred across a daemon restart carry one at all.
        """
        entries = ledger.read(self.paths.ledger)
        if not ladder.needs_delivery(entries):
            return
        token = secrets.token_hex(16)
        # The hash, never the token. The ledger is world-readable by design --
        # the operator should be able to read their own history -- and a token
        # sitting in it would be an acknowledgement anyone could present
        # without ever having been shown a challenge.
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        step = ladder.rung(entries)
        try:
            if step == ladder.LOCK:
                landed = self.notifier("lock", [str(ladder.LOCK_SECONDS), token])
            else:
                landed = self.notifier("challenge", [self._last_reason(entries), token])
        except Exception:
            # No session, no shell, no screen to lock. That is an ordinary
            # outcome rather than an error: the breach stays undelivered and is
            # handed over on the first cycle that finds a session.
            landed = False
        if landed:
            ledger.record(self.paths.ledger, "delivered", token_hash=digest)

    def _last_reason(self, entries):
        """What to put in front of the operator for the breach being delivered.

        The newest breach's first reason, because that is the one being
        delivered. A breach whose entry did not survive intact still has to say
        something: a challenge with no words on it is a challenge the operator
        cannot act on.
        """
        reason = None
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("kind") != "breach":
                continue
            reasons = entry.get("reasons")
            reason = (reasons[0]
                      if isinstance(reasons, list) and reasons
                      and isinstance(reasons[0], str) and reasons[0]
                      else None)
        return reason or "the wall was weakened"

    def _recorded_reasons(self):
        """The reasons on the newest breach or graced start already on record.

        A weakening the ledger already carries is one this instance should treat
        as standing, exactly as if it had recorded it itself. Without this the
        memory of it dies with the process, and a restart files the same masked
        unit a second time.
        """
        try:
            entries = ledger.read(self.paths.ledger)
        except Exception:
            return None
        for entry in reversed(entries):
            if not isinstance(entry, dict):
                continue
            # Breaches only. A graced start is the deferral of a filing,
            # not the filing itself -- seeding from one would suppress
            # the very breach the next cycle is supposed to make.
            if entry.get("kind") != "breach":
                continue
            reasons = entry.get("reasons")
            return reasons if isinstance(reasons, list) else []
        return None

    def _enforced_before(self, entries=None):
        # The ledger is the record of whether this machine has ever been in a
        # good state. It is append-only and root-owned, so answering this
        # question dishonestly costs more than the answer is worth.
        #
        # `graced` belongs here with the rest: it is a real weakening that was
        # recorded and simply not shown. Leaving it out would let a ledger
        # holding nothing else read as "never enforced", and the next weakening
        # would be filed as an install.
        if entries is None:
            entries = ledger.read(self.paths.ledger)
        return any(
            e.get("kind") in ("init", "applied", "drift", "breach", "graced")
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

        A graced start counts alongside a breach, and has to: the grace is what
        stops that cycle recording one, so without this a daemon killed inside
        its first cycle over and over would be handed a fresh free pass every
        time and the ladder would never leave the ground. A start is only ever
        graced when it found a weakening it could not attribute to a package
        transaction, so a genuine mid-upgrade restart -- which records drift --
        is not touched by this.
        """
        now = time.time() if now is None else now
        for entry in entries:
            if (not isinstance(entry, dict)
                    or entry.get("kind") not in ("breach", "graced")):
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
            # A graced start counts here as well, matching the ladder. It was
            # a real weakening; the start grace bought silence about it, not a
            # different classification. This is the number the operator reads
            # to understand their own history, and under-reporting it is worse
            # than the oddity of counting something that was never put on
            # screen -- it would also sit next to an "unacked" of 1 and read as
            # a contradiction.
            #
            # .get, matching _enforced_before: a truncated or hand-written
            # ledger line without a "kind" must not take status down with it.
            "breaches": len([e for e in entries
                             if e.get("kind") == "breach"]),
            "enforce_failures": self.enforce_failures,
            "unacknowledged": ladder.unacknowledged(entries),
            "weakened": integrity.weakened(
                self.paths.hosts, domains, self.paths.zen_policy,
                self.paths.unit_file, self.paths.unit_source,
                ledger_entries=entries),
        }
