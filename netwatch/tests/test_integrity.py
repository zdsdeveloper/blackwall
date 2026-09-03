import json
import os
import tempfile
import unittest
from blackwall_netwatch import hosts, integrity


class TestWeakened(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.hosts = os.path.join(self.dir, "hosts")
        self.policy = os.path.join(self.dir, "policies.json")
        self.unit = os.path.join(self.dir, "unit.service")
        self.source = os.path.join(self.dir, "unit.source")
        with open(self.hosts, "w") as f:
            f.write(hosts.splice("127.0.0.1 localhost\n", hosts.render(["a.com"])))
        with open(self.policy, "w") as f:
            json.dump({"policies": {"DNSOverHTTPS": {"Enabled": False, "Locked": True}}}, f)
        for path in (self.unit, self.source):
            with open(path, "w") as f:
                f.write("[Service]\nExecStart=/usr/local/bin/blackwall-netwatch\n")

    def reasons(self):
        return integrity.weakened(self.hosts, ["a.com"], self.policy,
                                  self.unit, self.source)

    def test_an_intact_wall_has_no_reasons(self):
        self.assertEqual(self.reasons(), [])

    def test_an_unrelated_hosts_entry_is_not_a_weakening(self):
        # The whole point of the change: adding a dev host is not tampering.
        with open(self.hosts, "a") as f:
            f.write("10.0.0.9 my-dev-box.local\n")
        self.assertEqual(self.reasons(), [])

    def test_a_sink_line_the_operator_wrote_themselves_counts(self):
        # What matters is whether the block is in effect, not whose line it is.
        text = open(self.hosts).read().replace("0.0.0.0 a.com\n", "")
        with open(self.hosts, "w") as f:
            f.write("0.0.0.0 a.com\n" + text)
        self.assertEqual(self.reasons(), [])

    def test_a_missing_sink_line_is_a_weakening(self):
        text = open(self.hosts).read().replace("0.0.0.0 a.com\n", "")
        with open(self.hosts, "w") as f:
            f.write(text)
        self.assertTrue(any("a.com" in r for r in self.reasons()))

    def test_the_whole_region_gone_is_a_weakening(self):
        with open(self.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.assertTrue(self.reasons())

    def test_doh_unlocked_is_a_weakening(self):
        with open(self.policy, "w") as f:
            json.dump({"policies": {"DNSOverHTTPS": {"Enabled": True, "Locked": False}}}, f)
        self.assertTrue(any("DNS" in r or "DoH" in r for r in self.reasons()))

    def test_a_missing_policy_file_is_a_weakening(self):
        os.unlink(self.policy)
        self.assertTrue(self.reasons())

    def test_a_malformed_policy_file_is_a_weakening_not_a_crash(self):
        with open(self.policy, "w") as f:
            f.write("{ not json")
        self.assertTrue(self.reasons())

    def test_a_masked_unit_is_a_weakening(self):
        os.unlink(self.unit)
        os.symlink("/dev/null", self.unit)
        self.assertTrue(any("unit" in r for r in self.reasons()))

    def test_an_edited_unit_is_a_weakening(self):
        with open(self.unit, "a") as f:
            f.write("# tampered\n")
        self.assertTrue(any("unit" in r for r in self.reasons()))

    def test_a_missing_unit_is_a_weakening(self):
        os.unlink(self.unit)
        self.assertTrue(any("unit" in r for r in self.reasons()))

    def test_an_absent_source_copy_is_not_a_weakening(self):
        # Nothing to compare against is not evidence of tampering.
        os.unlink(self.source)
        self.assertEqual(self.reasons(), [])

    def test_no_domains_no_sink_reasons(self):
        self.assertEqual(
            integrity.weakened(self.hosts, [], self.policy, self.unit, self.source), [])

    def test_an_unreadable_hosts_file_is_a_weakening_not_a_crash(self):
        os.unlink(self.hosts)
        self.assertTrue(self.reasons())


if __name__ == "__main__":
    unittest.main()
