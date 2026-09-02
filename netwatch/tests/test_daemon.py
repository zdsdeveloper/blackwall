import json
import os
import tempfile
import unittest
from blackwall_netwatch import ledger
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
        self.nw = NetWatch(self.paths)

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


if __name__ == "__main__":
    unittest.main()
