import json
import os
import tempfile
import time
import unittest
from blackwall_netwatch import daemon, ledger, provenance
from blackwall_netwatch.daemon import NetWatch, Paths

STOCK = "127.0.0.1 localhost\n"


def paths_in(d):
    return Paths(
        blocklist=os.path.join(d, "blocklist"),
        ledger=os.path.join(d, "ledger.jsonl"),
        hosts=os.path.join(d, "hosts"),
        zen_policy=os.path.join(d, "zen", "policies", "policies.json"),
        zen_package_policy=os.path.join(d, "distribution", "policies.json"),
        window_marker=os.path.join(d, "pacman-window"),
        pacman_lock=os.path.join(d, "db.lck"),
        socket=os.path.join(d, "netwatch.sock"),
    )


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
        self.nw = NetWatch(self.paths, flusher=lambda: None, proc_dir=self.proc)

    def make_proc_alive(self, comm="pacman"):
        os.makedirs(os.path.join(self.proc, "4242"), exist_ok=True)
        with open(os.path.join(self.proc, "4242", "comm"), "w") as f:
            f.write(comm + "\n")

    def test_starts_empty(self):
        self.assertEqual(self.nw.domains(), [])

    def test_add_normalises_and_persists(self):
        self.assertEqual(self.nw.add("https://WWW.Example.com/x"), "example.com")
        self.assertEqual(self.nw.domains(), ["example.com"])
        self.assertEqual(NetWatch(self.paths).domains(), ["example.com"])

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
        nw = NetWatch(self.paths, flusher=lambda: calls.append(1))
        nw.add("a.com")
        nw.enforce()
        self.assertEqual(len(calls), 1)

    def test_an_unchanged_cycle_does_not_flush(self):
        calls = []
        nw = NetWatch(self.paths, flusher=lambda: calls.append(1))
        nw.add("a.com")
        nw.enforce()
        nw.enforce()
        self.assertEqual(len(calls), 1)

    def test_a_zen_only_change_does_not_flush(self):
        # The resolver cache has nothing to do with the browser policy file.
        calls = []
        nw = NetWatch(self.paths, flusher=lambda: calls.append(1))
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

    def test_a_live_package_manager_refreshes_the_window_without_any_lock(self):
        # paru drives libalpm itself; the lock can be absent or already dropped
        # while the transaction is still very much running.
        self._write_marker(age=provenance.STALE_AFTER_SECONDS + 60)
        self.make_proc_alive("paru")
        self.nw._reap_dead_window()
        self.assertTrue(os.path.exists(self.paths.window_marker))
        self.assertLess(
            time.time() - os.stat(self.paths.window_marker).st_mtime, 60)

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


if __name__ == "__main__":
    unittest.main()
