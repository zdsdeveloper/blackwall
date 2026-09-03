import json
import os
import tempfile
import time
import unittest
from unittest import mock
from blackwall_netwatch import daemon, hosts, integrity, ladder, ledger, provenance
from blackwall_netwatch.daemon import NetWatch, Paths

STOCK = "127.0.0.1 localhost\n"


UNIT = "[Service]\nExecStart=/usr/local/bin/blackwall-netwatch\n"


def paths_in(d):
    """Paths under `d`, with the daemon's own unit installed and intact.

    The unit files are written here rather than in each setUp because an
    intact wall is what every test not about the unit is assuming. Without
    them a test aimed at hosts would also be reporting a weakened unit, and
    its verdict would be right for a reason it never meant to assert.
    """
    paths = Paths(
        blocklist=os.path.join(d, "blocklist"),
        ledger=os.path.join(d, "ledger.jsonl"),
        hosts=os.path.join(d, "hosts"),
        zen_policy=os.path.join(d, "zen", "policies", "policies.json"),
        zen_package_policy=os.path.join(d, "distribution", "policies.json"),
        window_marker=os.path.join(d, "pacman-window"),
        pacman_lock=os.path.join(d, "db.lck"),
        unit_file=os.path.join(d, "blackwall-netwatch.service"),
        unit_source=os.path.join(d, "unit-source.service"),
        socket=os.path.join(d, "netwatch.sock"),
    )
    for path in (paths.unit_file, paths.unit_source):
        with open(path, "w") as f:
            f.write(UNIT)
    return paths


class TestNetWatch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = paths_in(self.dir)
        with open(self.paths.hosts, "w") as f:
            f.write(STOCK)
        os.makedirs(os.path.dirname(self.paths.zen_package_policy))
        with open(self.paths.zen_package_policy, "w") as f:
            json.dump({"policies": {"DisableAppUpdate": True}}, f)
        # An empty stand-in for /proc: with a real one, whether a test passes
        # would depend on whether the machine running it happens to be in the
        # middle of a pacman transaction. Tests that need a live package
        # manager build one under here.
        self.proc = os.path.join(self.dir, "proc")
        os.makedirs(self.proc)
        # Both injected, always. The default notifier reaches the live session
        # over the real /proc, so an escalation from a test would lock the
        # screen of whoever happens to be sitting at the machine running it.
        self.calls = []
        self.nw = NetWatch(self.paths, flusher=lambda: None, proc_dir=self.proc,
                           notifier=self.record)

    def record(self, method, args=()):
        self.calls.append((method, list(args)))
        return True

    def make_proc_alive(self, comm="pacman"):
        os.makedirs(os.path.join(self.proc, "4242"), exist_ok=True)
        with open(os.path.join(self.proc, "4242", "comm"), "w") as f:
            f.write(comm + "\n")

    def test_starts_empty(self):
        self.assertEqual(self.nw.domains(), [])

    def test_add_normalises_and_persists(self):
        self.assertEqual(self.nw.add("https://WWW.Example.com/x"), "example.com")
        self.assertEqual(self.nw.domains(), ["example.com"])
        self.assertEqual(
            NetWatch(self.paths, flusher=lambda: None, proc_dir=self.proc,
                     notifier=self.record).domains(), ["example.com"])

    def test_add_is_idempotent(self):
        self.nw.add("a.com")
        self.nw.add("www.a.com")
        self.assertEqual(self.nw.domains(), ["a.com"])

    def test_add_rejects_garbage_without_writing(self):
        from blackwall_netwatch.blocklist import InvalidDomain
        with self.assertRaises(InvalidDomain):
            self.nw.add("localhost")
        self.assertEqual(self.nw.domains(), [])

    def test_add_is_recorded(self):
        self.nw.add("a.com")
        kinds = [e["kind"] for e in ledger.read(self.paths.ledger)]
        self.assertIn("added", kinds)

    def test_enforce_writes_hosts_and_zen_policy(self):
        self.nw.add("a.com")
        result = self.nw.enforce()
        self.assertTrue(result["changed"])
        self.assertIn("0.0.0.0 a.com", open(self.paths.hosts).read())
        policy = json.load(open(self.paths.zen_policy))["policies"]
        self.assertEqual(policy["DNSOverHTTPS"], {"Enabled": False, "Locked": True})
        self.assertTrue(policy["DisableAppUpdate"])

    def test_enforce_is_quiet_when_nothing_changed(self):
        self.nw.add("a.com")
        self.nw.enforce()
        result = self.nw.enforce()
        self.assertFalse(result["changed"])
        self.assertIsNone(result["verdict"])

    def test_hand_edit_of_hosts_is_a_breach(self):
        self.nw.add("a.com")
        self.nw.enforce()
        with open(self.paths.hosts, "w") as f:
            f.write(STOCK)
        result = self.nw.enforce()
        self.assertEqual(result["verdict"], "breach")
        self.assertIn("hosts", result["targets"])
        self.assertIn("0.0.0.0 a.com", open(self.paths.hosts).read())

    def test_edit_during_a_pacman_window_is_drift_not_breach(self):
        self.nw.add("a.com")
        self.nw.enforce()
        os.unlink(self.paths.zen_policy)
        with open(self.paths.window_marker, "w") as f:
            f.write("")
        # The lock as well as the marker: a window is only honoured now if a
        # transaction is actually still running behind it, and a real pacman
        # holds db.lck for the whole of one.
        with open(self.paths.pacman_lock, "w") as f:
            f.write("")
        result = self.nw.enforce()
        self.assertEqual(result["verdict"], "drift")
        self.assertTrue(os.path.exists(self.paths.zen_policy))

    def test_first_enforce_is_initialisation_not_breach(self):
        # Writing the managed region onto a machine that never had one is an
        # install. Calling it tampering would mean every fresh setup starts with
        # a breach on the record.
        self.nw.add("a.com")
        self.assertEqual(self.nw.enforce()["verdict"], "init")

    def test_second_enforce_after_a_hand_edit_is_a_breach(self):
        self.nw.add("a.com")
        self.nw.enforce()
        os.unlink(self.paths.zen_policy)
        self.assertEqual(self.nw.enforce()["verdict"], "breach")

    def test_breach_is_recorded_with_its_target(self):
        self.nw.add("a.com")
        self.nw.enforce()
        os.unlink(self.paths.zen_policy)
        self.nw.enforce()
        breaches = [e for e in ledger.read(self.paths.ledger) if e["kind"] == "breach"]
        self.assertEqual(len(breaches), 1)
        self.assertIn("zen_policy", breaches[0]["targets"])

    def test_status_reports_counts_not_domains(self):
        self.nw.add("a.com")
        s = self.nw.status()
        self.assertEqual(s["domains"], 1)
        self.assertEqual(s["breaches"], 0)

    def test_a_hosts_change_flushes_the_resolver_cache(self):
        calls = []
        nw = NetWatch(self.paths, flusher=lambda: calls.append(1),
                      proc_dir=self.proc, notifier=self.record)
        nw.add("a.com")
        nw.enforce()
        self.assertEqual(len(calls), 1)

    def test_an_unchanged_cycle_does_not_flush(self):
        calls = []
        nw = NetWatch(self.paths, flusher=lambda: calls.append(1),
                      proc_dir=self.proc, notifier=self.record)
        nw.add("a.com")
        nw.enforce()
        nw.enforce()
        self.assertEqual(len(calls), 1)

    def test_a_zen_only_change_does_not_flush(self):
        # The resolver cache has nothing to do with the browser policy file.
        calls = []
        nw = NetWatch(self.paths, flusher=lambda: calls.append(1),
                      proc_dir=self.proc, notifier=self.record)
        nw.add("a.com")
        nw.enforce()
        os.unlink(self.paths.zen_policy)
        nw.enforce()
        self.assertEqual(len(calls), 1)

    def test_a_blocklist_with_invalid_utf8_does_not_raise(self):
        # A corrupted blocklist must cost the unreadable bytes, not the daemon.
        self.nw.add("a.com")
        with open(self.paths.blocklist, "ab") as f:
            f.write(b"\xff\xfe not utf-8\n")
        self.assertEqual(self.nw.domains(), ["a.com"])

    def test_status_survives_a_corrupt_blocklist(self):
        self.nw.add("a.com")
        with open(self.paths.blocklist, "ab") as f:
            f.write(b"\xff\xfe\n")
        self.assertEqual(self.nw.status()["domains"], 1)

    def test_the_default_flusher_returns_promptly_when_not_root(self):
        # Guards the stall: unprivileged, this must not sit on polkit.
        if os.geteuid() == 0:
            self.skipTest("this asserts the non-root path")
        started = time.monotonic()
        daemon.flush_resolver_cache()
        self.assertLess(time.monotonic() - started, 1.0)

    def test_status_survives_a_ledger_line_with_no_kind(self):
        # A truncated or hand-written line must cost that line, not the call:
        # status is how the operator finds out whether the wall is still up.
        with open(self.paths.ledger, "w") as f:
            f.write(json.dumps({"at": 1}) + "\n")
            f.write(json.dumps({"at": 2, "kind": "breach"}) + "\n")
        self.assertEqual(self.nw.status()["breaches"], 1)

    def test_status_does_not_count_a_graced_start(self):
        # A deferral is not yet a finding. If the weakening is still there next
        # cycle it is filed as a real breach and counted then; if it has gone,
        # there was nothing to count. Both numbers agree either way.
        with open(self.paths.ledger, "w") as f:
            f.write(json.dumps({"at": time.time(), "kind": "graced"}) + "\n")
        s = self.nw.status()
        self.assertEqual(s["breaches"], 0)
        self.assertEqual(s["unacknowledged"], 0)

    def test_adding_a_domain_is_never_a_breach(self):
        # An add changes the blocklist, so the enforcement it triggers finds the
        # managed files disagreeing with it -- indistinguishable, to the
        # classifier, from a pair of hands. Before the fix the second and every
        # later add filed a breach against the operator for the ordinary act of
        # blocking a site, which in a later phase locks their screen. That is
        # the failure most likely to make this tool abandoned.
        verdicts = []
        for domain in ("a.com", "b.com", "c.com"):
            self.nw.add(domain)
            verdicts.append(self.nw.enforce()["verdict"])
        self.assertEqual(verdicts, ["init", "applied", "applied"])
        kinds = [e.get("kind") for e in ledger.read(self.paths.ledger)]
        self.assertEqual(kinds.count("breach"), 0)

    def test_an_add_does_not_blind_the_classifier_to_a_hand_edit(self):
        # The other half of it: the excuse is spent by the enforcement its own
        # add caused, so the very next hand edit is still seen for what it is.
        self.nw.add("a.com")
        self.nw.enforce()
        self.nw.add("b.com")
        self.assertEqual(self.nw.enforce()["verdict"], "applied")
        with open(self.paths.hosts, "w") as f:
            f.write(STOCK)
        self.assertEqual(self.nw.enforce()["verdict"], "breach")
        breaches = [e for e in ledger.read(self.paths.ledger)
                    if e.get("kind") == "breach"]
        self.assertEqual(len(breaches), 1)

    def _write_marker(self, age=0):
        with open(self.paths.window_marker, "w") as f:
            f.write("")
        if age:
            past = time.time() - age
            os.utime(self.paths.window_marker, (past, past))

    def _write_lock(self, age=0):
        with open(self.paths.pacman_lock, "w") as f:
            f.write("")
        if age:
            past = time.time() - age
            os.utime(self.paths.pacman_lock, (past, past))

    def test_reap_removes_a_window_with_no_transaction_behind_it(self):
        # An aborted transaction -- Ctrl-C, a failed download, a bad signature
        # -- never runs PostTransaction, so the marker outlives it and every
        # hand edit for the next half hour is excused as drift.
        #
        # Aged past the grace: the marker is no longer cut the instant liveness
        # goes false, because pacman exits a moment before the daemon notices.
        # What must not survive is a window with nothing behind it for long.
        self._write_marker(age=daemon.WINDOW_GRACE_SECONDS + 5)
        self.nw._reap_dead_window()
        self.assertFalse(os.path.exists(self.paths.window_marker))

    def test_a_stale_lock_does_not_buy_permanent_drift(self):
        # The verified regression. A pacman killed mid-transaction leaves both
        # db.lck and the marker behind. The reaper used to treat the mere
        # existence of the lock as a live transaction, refresh the marker on
        # every cycle, and so classify every hand edit from then on as drift --
        # the wall detecting nothing at all, silently and for ever.
        self.nw.add("a.com")
        self.nw.enforce()
        old = provenance.STALE_AFTER_SECONDS + 60
        self._write_lock(age=old)
        self._write_marker(age=old)
        verdicts = []
        for _ in range(3):
            with open(self.paths.hosts, "w") as f:
                f.write(STOCK)
            verdicts.append(self.nw.enforce()["verdict"])
        self.assertEqual(verdicts, ["breach", "breach", "breach"])
        self.assertFalse(os.path.exists(self.paths.window_marker))

    def test_a_fresh_lock_is_a_live_transaction_and_holds_the_window_open(self):
        # The other direction: a lock young enough to belong to a running
        # transaction still means drift, and the window is held open under it
        # rather than expiring in the middle of a real upgrade.
        self.nw.add("a.com")
        self.nw.enforce()
        stale = time.time() - (provenance.STALE_AFTER_SECONDS + 60)
        self._write_marker(age=provenance.STALE_AFTER_SECONDS + 60)
        self._write_lock()
        os.unlink(self.paths.zen_policy)
        self.assertEqual(self.nw.enforce()["verdict"], "drift")
        self.assertTrue(os.path.exists(self.paths.window_marker))
        self.assertGreater(os.stat(self.paths.window_marker).st_mtime, stale + 60)

    def test_a_live_package_manager_alone_does_not_hold_the_window_open(self):
        # `pacman -Q` is an ordinary unprivileged query and it runs a process
        # named pacman. If a live process alone held the window open, any user
        # could run one in a loop and keep the wall permanently in drift with
        # no privilege at all. The lock is what makes a transaction.
        self._write_marker(age=daemon.WINDOW_GRACE_SECONDS + 30)
        self.make_proc_alive("paru")
        self.nw._reap_dead_window()
        self.assertFalse(os.path.exists(self.paths.window_marker))

    def test_reap_gives_a_just_closed_window_its_grace(self):
        # pacman exits a moment before the daemon's next cycle notices. Cutting
        # the window there would turn the tail of a real upgrade -- a repair
        # that the PostTransaction hook did not land -- into a breach, and a
        # false breach is the expensive direction.
        self._write_marker(age=daemon.WINDOW_GRACE_SECONDS - 30)
        self.nw._reap_dead_window()
        self.assertTrue(os.path.exists(self.paths.window_marker))
        # And the grace is a grace, not a reprieve: past it the window goes.
        self._write_marker(age=daemon.WINDOW_GRACE_SECONDS + 30)
        self.nw._reap_dead_window()
        self.assertFalse(os.path.exists(self.paths.window_marker))

    def test_an_enforcement_that_changed_nothing_still_spends_the_excuse(self):
        # The flag is raised by add() and must be spent by the enforcement it
        # was raised for -- including one that finds the managed files already
        # in agreement. Left set past an empty cycle it excused the next
        # genuine hand edit as our own work.
        self.nw.add("a.com")
        self.nw.enforce()
        self.nw._applied_pending = True
        self.assertFalse(self.nw.enforce()["changed"])
        self.assertFalse(self.nw._applied_pending)
        with open(self.paths.hosts, "w") as f:
            f.write(STOCK)
        self.assertEqual(self.nw.enforce()["verdict"], "breach")

    def test_an_enforcement_that_raised_keeps_the_excuse_for_the_retry(self):
        # The deliberate asymmetry. If the enforcement blows up, the change the
        # add asked for really has not been applied yet, so the excuse is still
        # owed to the cycle that eventually applies it. Dropping it here would
        # file a breach against the operator for blocking a site.
        self.nw.add("a.com")
        self.nw.enforce()
        self.nw.add("b.com")
        original = daemon.hosts.apply

        def boom(*args, **kwargs):
            raise RuntimeError("disk went away mid-repair")

        daemon.hosts.apply = boom
        try:
            with self.assertRaises(RuntimeError):
                self.nw.enforce()
        finally:
            daemon.hosts.apply = original
        self.assertTrue(self.nw._applied_pending)
        self.assertEqual(self.nw.enforce()["verdict"], "applied")

    def test_reap_refreshes_the_window_of_a_long_running_transaction(self):
        # A large -Syu can outlast the staleness bound, and a window that
        # expires underneath a transaction still running ends a routine upgrade
        # in a false breach.
        self.nw.add("a.com")
        self.nw.enforce()
        stale = time.time() - (provenance.STALE_AFTER_SECONDS + 60)
        with open(self.paths.window_marker, "w") as f:
            f.write("")
        os.utime(self.paths.window_marker, (stale, stale))
        # The lock as well as the process: a transaction is made by db.lck, and
        # a real -Syu holds it for the whole of one however long that runs.
        # The process check is only what tells this stale lock from a dead one.
        self._write_lock(age=provenance.STALE_AFTER_SECONDS + 60)
        self.make_proc_alive("pacman")
        self.nw._reap_dead_window()
        self.assertTrue(os.path.exists(self.paths.window_marker))
        self.assertGreater(os.stat(self.paths.window_marker).st_mtime, stale + 60)
        os.unlink(self.paths.zen_policy)
        self.assertEqual(self.nw.enforce()["verdict"], "drift")

    def test_add_refuses_to_grow_the_blocklist_past_the_cap(self):
        # The cap is reached by lowering it rather than by writing 50000 real
        # domains: what is being tested is the refusal, not the number. Without
        # a cap any local user can grow the file through the 0666 socket until
        # domains() cannot read it, and the daemon then OOMs on every start.
        original = daemon.MAX_DOMAINS
        daemon.MAX_DOMAINS = 2
        try:
            self.nw.add("a.com")
            self.nw.add("b.com")
            with self.assertRaises(daemon.BlocklistFull):
                self.nw.add("c.com")
            # A domain already on the list adds nothing, so a full list must
            # not turn the idempotent re-add into an error.
            self.assertEqual(self.nw.add("a.com"), "a.com")
        finally:
            daemon.MAX_DOMAINS = original
        self.assertEqual(self.nw.domains(), ["a.com", "b.com"])

    def test_deleting_a_line_from_the_blocklist_is_a_breach(self):
        # The blocklist used to define what "intact" meant, so editing it
        # redefined the promise instead of breaking it.
        self.nw.add("a.com")
        self.nw.enforce()
        with open(self.paths.blocklist, "w") as f:
            f.write("")
        result = self.nw.enforce()
        self.assertEqual(result["verdict"], "breach")
        self.assertTrue(any("blocklist" in r for r in result["reasons"]))
        # Restored within the same cycle, so the next one finds nothing
        # missing and the reason clears on its own -- one deletion is one
        # breach, not one per cycle it takes to notice.
        self.nw.enforce()
        breaches = [e for e in ledger.read(self.paths.ledger)
                    if e["kind"] == "breach"]
        self.assertEqual(len(breaches), 1)

    def test_a_deleted_domain_is_put_back(self):
        # Append-only permits appends, so the removal does not survive a cycle.
        self.nw.add("a.com")
        self.nw.enforce()
        with open(self.paths.blocklist, "w") as f:
            f.write("")
        self.nw.enforce()
        self.assertEqual(self.nw.domains(), ["a.com"])

    def test_the_restored_domain_is_blocked_again_in_hosts(self):
        self.nw.add("a.com")
        self.nw.enforce()
        with open(self.paths.blocklist, "w") as f:
            f.write("")
        self.nw.enforce()
        self.assertIn("0.0.0.0 a.com", open(self.paths.hosts).read())

    def test_restoring_does_not_file_a_second_added_entry(self):
        # It was added once. The ledger already says so.
        self.nw.add("a.com")
        self.nw.enforce()
        with open(self.paths.blocklist, "w") as f:
            f.write("")
        self.nw.enforce()
        added = [e for e in ledger.read(self.paths.ledger) if e["kind"] == "added"]
        self.assertEqual(len(added), 1)

    def test_a_promised_domain_recorded_under_an_older_normalisation(self):
        # www-stripping changed from `if` to `while`, so an entry written
        # before that can name a domain this normalisation would never
        # produce ("www.www.x.com" now normalises straight to "x.com"). The
        # restore must satisfy the promise rather than chase an unnormalised
        # ledger entry every cycle for ever.
        self.nw.add("a.com")
        self.nw.enforce()  # init
        self.nw.enforce()  # quiet
        ledger.record(self.paths.ledger, "added", domain="www.www.x.com")
        counts = []
        for _ in range(3):
            self.nw.enforce()
            counts.append(len([e for e in ledger.read(self.paths.ledger)
                                if e["kind"] == "breach"]))
        # One entry recorded under an old normalisation is one thing to
        # reconcile, not a fresh breach every cycle it takes to notice.
        self.assertEqual(counts[1], counts[2])

    def test_a_restore_that_cannot_be_written_still_records_the_breach(self):
        # ENOSPC, EPERM or a chattr +i on the blocklist must not take the
        # whole cycle down with it: the tampering still gets recorded, and
        # the rest of the pipeline still runs.
        self.nw.add("a.com")
        self.nw.enforce()  # init
        self.nw.enforce()  # quiet
        os.unlink(self.paths.zen_policy)
        with open(self.paths.blocklist, "w") as f:
            f.write("")
        os.chmod(self.paths.blocklist, 0o444)
        try:
            result = self.nw.enforce()
        finally:
            os.chmod(self.paths.blocklist, 0o644)
        self.assertEqual(result["verdict"], "breach")
        breaches = [e for e in ledger.read(self.paths.ledger)
                    if e["kind"] == "breach"]
        self.assertEqual(len(breaches), 1)
        # The policy repair is independent of the blocklist write and still
        # ran despite the failed restore.
        policy = json.load(open(self.paths.zen_policy))["policies"]
        self.assertEqual(policy["DNSOverHTTPS"], {"Enabled": False, "Locked": True})
        # hosts.apply ran to completion too, rather than the cycle dying
        # before it got there.
        self.assertIn("127.0.0.1 localhost", open(self.paths.hosts).read())

    def test_close_window_removes_the_marker(self):
        with open(self.paths.window_marker, "w") as f:
            f.write("")
        self.nw.close_window()
        self.assertFalse(os.path.exists(self.paths.window_marker))

    def test_close_window_without_a_marker_is_a_no_op(self):
        # Called after any completed enforce, including outside a package
        # transaction, so "already gone" is the ordinary case.
        self.nw.close_window()
        self.assertFalse(os.path.exists(self.paths.window_marker))

    def test_arming_is_recorded_once(self):
        # append_only can't be exercised for real without root, so the seam
        # is mocked: what matters here is that enforce() writes the entry on
        # first sight of the attribute and never again, however many cycles
        # follow.
        with mock.patch.object(integrity, "append_only", return_value=True):
            self.nw.enforce()
            self.nw.enforce()
            self.nw.enforce()
        kinds = [e.get("kind") for e in ledger.read(self.paths.ledger)]
        self.assertEqual(kinds.count("armed"), 1)

    def test_an_armed_entry_alone_does_not_count_as_ever_enforced(self):
        # A fresh install writes nothing but the arming entry until its first
        # real cycle; that must not read as "this machine has a history".
        ledger.record(self.paths.ledger, "armed")
        self.assertFalse(self.nw._enforced_before())

    def test_an_armed_entry_does_not_count_toward_unacknowledged(self):
        # Recording that the ledger is now armed must not itself look like a
        # breach worth escalating.
        ledger.record(self.paths.ledger, "armed")
        entries = ledger.read(self.paths.ledger)
        self.assertEqual(ladder.unacknowledged(entries), 0)

    def test_a_ledger_that_loses_append_only_after_arming_is_a_breach(self):
        with mock.patch.object(integrity, "append_only", return_value=True):
            self.nw.enforce()  # init: arms the ledger
        with mock.patch.object(integrity, "append_only", return_value=False):
            result = self.nw.enforce()
        self.assertEqual(result["verdict"], "breach")
        self.assertTrue(any("ledger" in r for r in result["reasons"]))


class TestWeakeningAndLadder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = paths_in(self.dir)
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        for path in (self.paths.unit_file, self.paths.unit_source):
            with open(path, "w") as f:
                f.write("[Service]\n")
        self.calls = []
        self.nw = NetWatch(self.paths, flusher=lambda: None,
                           proc_dir=self.empty_proc(), notifier=self.recorder)

    def recorder(self, method, args=()):
        """A session that is up. Injected, always: the real notifier reaches
        the live session over the real /proc, and a delivery from a test would
        lock the screen of whoever is sitting at the machine running it."""
        self.calls.append((method, list(args)))
        return True

    def empty_proc(self):
        p = os.path.join(self.dir, "proc")
        os.makedirs(os.path.join(p, "1"), exist_ok=True)
        with open(os.path.join(p, "1", "comm"), "w") as f:
            f.write("bash\n")
        return p

    def settle(self):
        self.nw.add("a.com")
        self.nw.enforce()          # init
        self.nw.enforce()          # quiet
        self.calls.clear()

    def restarted(self):
        """A second NetWatch over the same paths, as a restart leaves one."""
        return NetWatch(
            self.paths, flusher=lambda: None, proc_dir=self.empty_proc(),
            notifier=self.recorder)

    def break_hosts(self):
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")

    def mask_unit(self):
        os.unlink(self.paths.unit_file)
        os.symlink("/dev/null", self.paths.unit_file)

    def breaches(self):
        return [e for e in ledger.read(self.paths.ledger)
                if e.get("kind") == "breach"]

    def weakenings(self):
        """Everything that counts toward the rung, however it was recorded."""
        return [e for e in ledger.read(self.paths.ledger)
                if e.get("kind") in ("breach", "graced")]

    def test_a_weakening_already_there_at_startup_is_shown_on_the_next_cycle(self):
        # The grace defers, it does not forgive. A masked unit that was in place
        # before the daemon came up used to be recorded once, never delivered,
        # and then suppressed as standing for ever: tolerated in silence.
        self.settle()
        self.mask_unit()
        fresh = self.restarted()
        fresh.enforce()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.breaches(), [])
        fresh.enforce()
        self.assertEqual(len(self.breaches()), 1)
        self.assertEqual(self.calls[-1][0], "challenge")

    def test_a_weakening_gone_by_the_next_cycle_is_never_shown(self):
        # The other half, and the reason the grace exists: a daemon coming up
        # while a package transaction is mid-write finds the managed files
        # short, repairs them in that same cycle, and must not challenge anyone
        # over it.
        self.settle()
        self.break_hosts()
        fresh = self.restarted()
        fresh.enforce()
        fresh.enforce()
        fresh.enforce()
        self.assertEqual(self.breaches(), [])
        self.assertEqual(self.calls, [])

    def test_a_standing_weakening_is_not_recorded_twice_across_a_restart(self):
        # One act of tampering, one count. The memory of what had already been
        # recorded used to die with the process, so a restart filed the same
        # masked unit a second time -- and because a graced start counts toward
        # the rung, that second filing was a twenty-minute lock.
        self.settle()
        self.mask_unit()
        self.nw.enforce()
        self.assertEqual(len(self.weakenings()), 1)
        self.restarted().enforce()
        self.assertEqual(len(self.weakenings()), 1)

    def test_a_genuinely_new_weakening_after_a_restart_is_recorded(self):
        # The mirror of the above: seeding from the ledger must not swallow a
        # real second act of tampering.
        self.settle()
        self.mask_unit()
        self.nw.enforce()
        self.assertEqual(len(self.weakenings()), 1)
        fresh = self.restarted()
        self.break_hosts()
        fresh.enforce()
        self.assertEqual(len(self.weakenings()), 2)

    def test_an_unrelated_hosts_edit_is_a_repair_not_a_breach(self):
        self.settle()
        with open(self.paths.hosts, "a") as f:
            f.write("10.0.0.9 my-dev-box.local\n")
        result = self.nw.enforce()
        self.assertIn(result["verdict"], (None, "repair"))
        self.assertEqual(self.calls, [])

    def test_a_removed_sink_line_is_a_breach_and_challenges(self):
        self.settle()
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        result = self.nw.enforce()
        self.assertEqual(result["verdict"], "breach")
        self.assertEqual(len(self.calls), 1)
        method, args = self.calls[0]
        self.assertEqual(method, "challenge")
        self.assertEqual(args[0], result["reasons"][0])
        # A token, present and non-empty: the ack that answers this challenge
        # has to prove it, not just claim it.
        self.assertTrue(args[1])

    def test_a_second_breach_locks(self):
        self.settle()
        for _ in range(2):
            with open(self.paths.hosts, "w") as f:
                f.write("127.0.0.1 localhost\n")
            self.nw.enforce()
        self.assertEqual(self.calls[-1][0], "lock")
        self.assertEqual(self.calls[-1][1][0], str(ladder.LOCK_SECONDS))
        self.assertTrue(self.calls[-1][1][1])

    def test_a_masked_unit_is_a_breach(self):
        self.settle()
        os.unlink(self.paths.unit_file)
        os.symlink("/dev/null", self.paths.unit_file)
        self.assertEqual(self.nw.enforce()["verdict"], "breach")

    def test_the_first_enforcement_after_start_never_escalates(self):
        # A restart mid-transaction used to look like tampering. In Phase 2 that
        # is a lockout for rebooting.
        self.settle()
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        fresh = NetWatch(self.paths, flusher=lambda: None,
                         proc_dir=self.empty_proc(), notifier=self.recorder)
        fresh.enforce()
        self.assertEqual(self.calls, [])

    def test_a_standing_breach_does_not_re_fire_the_ladder(self):
        # Otherwise an unanswered challenge reappears every cycle until the
        # operator kills the shell to stop it.
        self.settle()
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.nw.enforce()
        before = len(self.calls)
        self.nw.enforce()
        self.nw.enforce()
        self.assertEqual(len(self.calls), before)

    def test_a_standing_unrepairable_breach_does_not_re_fire_either(self):
        # The masked unit is the one weakening the repair loop cannot undo, so
        # it is the one that would otherwise be re-recorded and re-escalated on
        # every cycle: challenge, then a fresh lock every thirty seconds for as
        # long as it stands.
        self.settle()
        os.unlink(self.paths.unit_file)
        os.symlink("/dev/null", self.paths.unit_file)
        self.assertEqual(self.nw.enforce()["verdict"], "breach")
        before = len(self.calls)
        for _ in range(3):
            self.assertIsNone(self.nw.enforce()["verdict"])
        self.assertEqual(len(self.calls), before)
        breaches = [e for e in ledger.read(self.paths.ledger)
                    if e.get("kind") == "breach"]
        self.assertEqual(len(breaches), 1)

    def test_a_shrinking_reason_set_does_not_re_fire(self):
        # A standing weakening plus a second one that then gets repaired leaves
        # the first still standing. That is the same breach with one part
        # mended, not a new one -- and an equality test would file a second
        # entry for it, raising the rung for the whole of the ladder's window.
        self.settle()
        self.mask_unit()
        self.nw.enforce()                      # the unit, recorded once
        self.nw.enforce()                      # still standing, quiet
        self.break_hosts()
        self.nw.enforce()                      # hosts as well: a new event
        calls = len(self.calls)
        recorded = len(self.breaches())
        # Hosts is repaired now; the unit is all that is left, and it was
        # already recorded and already escalated.
        self.assertIsNone(self.nw.enforce()["verdict"])
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(len(self.breaches()), recorded)

    def test_a_growing_reason_set_does_re_fire(self):
        # The mirror of it. A weakening that arrives alongside one already
        # standing is a new event, or the first breach of the day would buy
        # silence for every one after it.
        self.settle()
        self.mask_unit()
        self.nw.enforce()
        self.nw.enforce()
        self.assertEqual([m for m, _ in self.calls], ["challenge"])
        self.break_hosts()
        self.assertEqual(self.nw.enforce()["verdict"], "breach")
        self.assertEqual(self.calls[-1][0], "lock")
        self.assertEqual(len(self.breaches()), 2)

    def test_a_restart_cannot_mint_a_fresh_grace_after_a_recent_breach(self):
        # The grace cannot live in instance state alone. `systemctl kill` is
        # not a stop job and Restart=always brings the daemon straight back, so
        # a per-instance grace would be reissued every few seconds and the
        # ladder would never leave the ground while breaches piled up.
        self.settle()
        self.break_hosts()
        self.nw.enforce()
        self.assertEqual([m for m, _ in self.calls], ["challenge"])
        restarted = self.restarted()
        self.break_hosts()
        self.assertEqual(restarted.enforce()["verdict"], "breach")
        self.assertEqual(self.calls[-1][0], "lock")

    def test_a_restart_still_gets_the_grace_when_no_breach_is_recent(self):
        # The case the grace exists for. A daemon coming up in the middle of a
        # transaction has drift on the record, not a breach, and its first
        # cycle still escalates nothing.
        self.settle()
        with open(self.paths.window_marker, "w") as f:
            f.write("")
        self.break_hosts()
        self.assertEqual(self.nw.enforce()["verdict"], "drift")
        os.unlink(self.paths.window_marker)
        restarted = self.restarted()
        self.break_hosts()
        self.assertEqual(restarted.enforce()["verdict"], "breach")
        self.assertEqual(self.calls, [])

    def test_a_change_that_removed_no_protection_records_repair(self):
        # The markers stripped and the sink lines left exactly where they are:
        # the region has to be written back, and nothing was ever missing.
        # Repaired, recorded, never punished.
        self.settle()
        with open(self.paths.hosts) as f:
            kept = [line for line in f.read().splitlines()
                    if line.strip() not in (hosts.BEGIN, hosts.END)]
        with open(self.paths.hosts, "w") as f:
            f.write("\n".join(kept) + "\n")
        result = self.nw.enforce()
        self.assertEqual(result["verdict"], "repair")
        self.assertEqual(result["targets"], ["hosts"])
        self.assertEqual(result["reasons"], [])
        self.assertEqual(self.calls, [])

    def test_drift_never_escalates(self):
        self.settle()
        with open(self.paths.window_marker, "w") as f:
            f.write("")
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.assertEqual(self.nw.enforce()["verdict"], "drift")
        self.assertEqual(self.calls, [])

    def test_a_breach_with_no_session_is_delivered_when_one_appears(self):
        # Killing the shell before tampering must not skip rung one.
        self.settle()
        self.nw.notifier = lambda m, a=(): False      # nobody logged in
        self.break_hosts()
        self.nw.enforce()
        self.assertEqual(self.calls, [])
        self.nw.notifier = self.recorder              # a session appears
        self.nw.enforce()
        self.assertEqual(self.calls[-1][0], "challenge")
        # And it says what was weakened, not just that something was.
        self.assertTrue(self.calls[-1][1][0])
        self.assertTrue(self.calls[-1][1][1])

    def test_a_delivered_breach_is_not_delivered_twice(self):
        # Delivery is once per breach, not once per cycle: a challenge that
        # reappeared every thirty seconds would teach the operator that killing
        # the shell is how you deal with the Blackwall.
        self.settle()
        self.break_hosts()
        self.nw.enforce()
        self.assertEqual([m for m, _ in self.calls], ["challenge"])
        for _ in range(3):
            self.nw.enforce()
        self.assertEqual([m for m, _ in self.calls], ["challenge"])

    def test_a_dismissed_challenge_does_not_come_back(self):
        # Delivered but unacknowledged: the breach stands and the next one
        # locks. Ignoring rung one is how the operator chooses rung two.
        self.settle()
        self.break_hosts()
        self.nw.enforce()
        self.nw.enforce()                      # dismissed: no ack on the record
        self.assertEqual([m for m, _ in self.calls], ["challenge"])
        self.break_hosts()
        self.assertEqual(self.nw.enforce()["verdict"], "breach")
        self.assertEqual(self.calls[-1][0], "lock")

    def test_a_restart_loop_cannot_keep_minting_the_start_grace(self):
        # The graced start goes on the record precisely so the next one can see
        # it. Were it to leave no trace, a daemon killed inside its first cycle
        # over and over would be handed a fresh free pass every time and the
        # ladder would never leave the ground.
        self.settle()
        self.break_hosts()
        first = self.restarted()
        self.assertEqual(first.enforce()["verdict"], "breach")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.breaches(), [])
        self.break_hosts()
        second = self.restarted()
        self.assertEqual(second.enforce()["verdict"], "breach")
        self.assertEqual(len(self.breaches()), 1)
        # A challenge, and shown: the second restart is refused the grace, so
        # the weakening is filed as a real breach and delivered rather than
        # deferred again. What the loop cannot do is keep the ladder silent --
        # which was the whole reason the graced start goes on the record.
        self.assertEqual(self.calls[-1][0], "challenge")

    def test_a_notifier_that_fails_does_not_break_enforcement(self):
        self.settle()
        nw = NetWatch(self.paths, flusher=lambda: None, proc_dir=self.empty_proc(),
                      notifier=lambda m, a=(): (_ for _ in ()).throw(OSError("no session")))
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        # Spends this instance's first-enforcement grace, so the breach below
        # actually reaches the notifier instead of passing it by.
        self.assertEqual(nw.enforce()["verdict"], "breach")
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.assertEqual(nw.enforce()["verdict"], "breach")


if __name__ == "__main__":
    unittest.main()
