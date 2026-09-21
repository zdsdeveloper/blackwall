"""The one exception.

NetWatch has no removal, and these tests are as much about keeping it that way
as about the single domain that was let go. The exception is a fixed decision
in the program, not a mechanism: nothing here may make a second one possible,
and nothing about letting the first one go may look like tampering -- a
mistake in either direction is a hole in the wall or a locked screen.
"""

import hashlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

from blackwall_netwatch import blocklist, hosts, integrity, ledger, server
from blackwall_netwatch.daemon import NetWatch

import test_daemon
from test_daemon import STOCK, paths_in

# The same guard the daemon tests use: enforce() runs a resolver sweep, and a
# test suite that makes real DNS lookups depends on the network it runs on.
setUpModule = test_daemon.setUpModule
tearDownModule = test_daemon.tearDownModule

# A stand-in. The real exception is held as a digest so this public
# repository never names anything on the operator's list, and a test that spelt
# it out would undo that in the very next file. The behaviour below is the
# behaviour of whatever domain the set holds; only the set's shape is checked
# against the real thing.
THE_ONE = "released.example"
STAND_IN = frozenset({hashlib.sha256(THE_ONE.encode("utf-8")).hexdigest()})


class _StandIn(unittest.TestCase):
    """Runs against the stand-in rather than the real exception."""

    def setUp(self):
        patcher = mock.patch.object(blocklist, "RELEASED", STAND_IN)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestTheSetItself(unittest.TestCase):
    def test_there_is_at_most_one_exception_and_there_never_will_be_more(self):
        # The operator's words: the only exception that will ever exist. It
        # may go back to none. It may not become two.
        self.assertLessEqual(len(blocklist.RELEASED), 1)

    def test_the_exception_is_held_as_a_digest_not_a_name(self):
        # The repository is public and the list is not.
        for entry in blocklist.RELEASED:
            self.assertRegex(entry, r"^[0-9a-f]{64}$")



class TestWhatItMatches(_StandIn):
    def test_it_matches_the_apex(self):
        self.assertTrue(blocklist.is_released(THE_ONE))

    def test_and_nothing_beneath_it(self):
        # Every subdomain on the list is still on the wall. This is the line
        # that keeps the release to a storefront and not to its studios.
        self.assertFalse(blocklist.is_released("studio." + THE_ONE))
        self.assertFalse(blocklist.is_released("a.b." + THE_ONE))

    def test_nor_anything_that_merely_looks_like_it(self):
        for name in ("not" + THE_ONE, THE_ONE + ".evil.com", THE_ONE + "o",
                     THE_ONE.replace(".", "") + ".com"):
            self.assertFalse(blocklist.is_released(name), name)


class TestTheListReadsWithoutIt(_StandIn):
    def test_parse_leaves_it_out(self):
        self.assertNotIn(THE_ONE, blocklist.parse(THE_ONE + "\nexample.com\n"))

    def test_including_when_it_was_written_with_www(self):
        self.assertNotIn(THE_ONE, blocklist.parse("www." + THE_ONE + "\n"))

    def test_but_keeps_everything_beneath_it(self):
        self.assertEqual(
            blocklist.parse(THE_ONE + "\nstudio." + THE_ONE + "\nexample.com\n"),
            ["example.com", "studio." + THE_ONE])

    def test_the_ledger_no_longer_promises_it(self):
        # If it did, the restore would put it back every cycle for ever.
        entries = [{"kind": "added", "domain": THE_ONE},
                   {"kind": "added", "domain": "example.com"}]
        self.assertEqual(integrity.promised_domains(entries), {"example.com"})
        self.assertEqual(integrity.unblocked_domains(entries, ["example.com"]), [])


class TestLettingItGoOnTheRealMachine(unittest.TestCase):
    """The machine as it was on the day: the domain contained, enforced, its
    sink lines on disk and its add in the ledger -- and then the daemon comes
    back up running a program that has let it go."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.paths = paths_in(self.dir)
        with open(self.paths.hosts, "w") as f:
            f.write(STOCK)
        os.makedirs(os.path.dirname(self.paths.zen_package_policy))
        with open(self.paths.zen_package_policy, "w") as f:
            f.write('{"policies": {"DisableAppUpdate": true}}')
        self.proc = os.path.join(self.dir, "proc")
        os.makedirs(self.proc)

        # Before: a program with no exception at all.
        with mock.patch.object(blocklist, "RELEASED", frozenset()):
            before = self.daemon([])
            for d in (THE_ONE, "studio." + THE_ONE, "example.com"):
                before.add(d)
            before.enforce()
            before.enforce()
            with open(self.paths.hosts) as f:
                self.assertIn("0.0.0.0 " + THE_ONE + "\n", f.read())

        # After: the daemon restarted on the new program.
        patcher = mock.patch.object(blocklist, "RELEASED", STAND_IN)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls = []
        self.nw = self.daemon(self.calls)

    def daemon(self, calls):
        def notify(method, args=()):
            calls.append((method, list(args)))
            return True
        return NetWatch(self.paths, flusher=lambda: None, proc_dir=self.proc,
                        notifier=notify)

    def hosts_text(self):
        with open(self.paths.hosts) as f:
            return f.read()

    def test_the_cycle_that_lets_it_go_is_a_repair_not_a_breach(self):
        # The one that matters most. Letting it go changes the hosts file, and
        # a change the daemon mistook for tampering would escalate -- ending,
        # on the second rung, in a locked screen.
        result = self.nw.enforce()
        self.assertEqual(result["verdict"], "repair")
        self.assertEqual(result["reasons"], [])

    def test_nothing_is_escalated(self):
        for _ in range(3):
            self.nw.enforce()
        self.assertEqual(self.calls, [])
        kinds = [e.get("kind") for e in ledger.read(self.paths.ledger)]
        self.assertNotIn("breach", kinds)

    def test_its_sink_lines_leave_the_hosts_file(self):
        self.nw.enforce()
        text = self.hosts_text()
        self.assertNotIn(" " + THE_ONE + "\n", text)
        self.assertNotIn(" www." + THE_ONE + "\n", text)

    def test_while_everything_else_stays_sunk(self):
        self.nw.enforce()
        text = self.hosts_text()
        for line in hosts.expected_lines(["example.com", "studio." + THE_ONE]):
            self.assertIn(line + "\n", text)

    def test_the_restore_does_not_put_it_back(self):
        # Every cycle would otherwise append it to the list again: the file
        # growing by a line every thirty seconds, for ever.
        self.nw.enforce()
        size = os.path.getsize(self.paths.blocklist)
        for _ in range(4):
            self.nw.enforce()
        self.assertEqual(os.path.getsize(self.paths.blocklist), size)

    def test_the_list_keeps_its_history(self):
        # Append-only means append-only, for this too. The line stays.
        self.nw.enforce()
        with open(self.paths.blocklist) as f:
            self.assertIn(THE_ONE + "\n", f.read())

    def test_the_release_is_recorded_once(self):
        for _ in range(4):
            self.nw.enforce()
        released = [e for e in ledger.read(self.paths.ledger)
                    if e.get("kind") == "released"]
        self.assertEqual([e.get("domain") for e in released], [THE_ONE])

    def test_status_neither_lists_it_nor_calls_the_wall_short(self):
        self.nw.enforce()
        s = self.nw.status()
        self.assertNotIn(THE_ONE, s["domains_list"])
        self.assertEqual(sorted(s["blocked_live"]), sorted(s["domains_list"]))
        self.assertEqual(s["weakened"], [])

    def test_it_cannot_be_added_back(self):
        # Refused rather than accepted and filtered: an add that reports
        # success and contains nothing is worse than a refusal.
        for raw in (THE_ONE, "www." + THE_ONE, "https://" + THE_ONE + "/games"):
            with self.assertRaises(blocklist.Released):
                self.nw.add(raw)

    def test_and_the_socket_says_why_rather_than_calling_it_a_bad_name(self):
        reply = server.handle(self.nw, {"cmd": "add", "domain": THE_ONE})
        self.assertFalse(reply["ok"])
        self.assertIn("exception", reply["error"])
        self.assertNotIn("not a domain", reply["error"])

    def test_its_studios_can_still_be_added(self):
        self.assertEqual(self.nw.add("another." + THE_ONE), "another." + THE_ONE)


class TestAMachineThatNeverHadIt(_StandIn):
    def test_nothing_is_recorded_as_released(self):
        # A release is a fact about this machine's history. One that never
        # contained the domain has nothing to have let go.
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        paths = paths_in(d)
        with open(paths.hosts, "w") as f:
            f.write(STOCK)
        os.makedirs(os.path.dirname(paths.zen_package_policy))
        with open(paths.zen_package_policy, "w") as f:
            f.write('{"policies": {}}')
        proc = os.path.join(d, "proc")
        os.makedirs(proc)
        nw = NetWatch(paths, flusher=lambda: None, proc_dir=proc,
                      notifier=lambda *a, **k: True)
        nw.add("example.com")
        nw.enforce()
        nw.enforce()
        kinds = [e.get("kind") for e in ledger.read(paths.ledger)]
        self.assertNotIn("released", kinds)


if __name__ == "__main__":
    unittest.main()
