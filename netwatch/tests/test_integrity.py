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

    def test_a_missing_hosts_file_is_a_weakening_not_a_crash(self):
        os.unlink(self.hosts)
        self.assertTrue(self.reasons())

    def test_a_trailing_newline_difference_is_not_a_weakening(self):
        # `systemctl edit` and a plain re-save both do this. Locking the screen
        # for a change that changed nothing is how the tool gets uninstalled.
        with open(self.unit, "a") as f:
            f.write("\n\n")
        self.assertEqual(self.reasons(), [])

    def test_a_dropin_override_is_a_weakening(self):
        # A drop-in replaces ExecStart without the unit file changing at all.
        os.makedirs(self.unit + ".d")
        with open(os.path.join(self.unit + ".d", "override.conf"), "w") as f:
            f.write("[Service]\nExecStart=/bin/true\n")
        self.assertTrue(any("unit" in r for r in self.reasons()))

    def test_an_empty_dropin_directory_is_not_a_weakening(self):
        os.makedirs(self.unit + ".d")
        self.assertEqual(self.reasons(), [])

    def test_a_non_conf_file_in_the_dropin_directory_is_ignored(self):
        os.makedirs(self.unit + ".d")
        with open(os.path.join(self.unit + ".d", "notes.txt"), "w") as f:
            f.write("scratch\n")
        self.assertEqual(self.reasons(), [])

    def test_an_extra_key_beside_the_doh_fields_is_not_a_weakening(self):
        # A future Zen adding a field must not read as DoH being unlocked.
        with open(self.policy, "w") as f:
            json.dump({"policies": {"DNSOverHTTPS": {
                "Enabled": False, "Locked": True, "SomethingNew": 1}}}, f)
        self.assertEqual(self.reasons(), [])

    def test_doh_enabled_with_an_extra_key_is_still_a_weakening(self):
        with open(self.policy, "w") as f:
            json.dump({"policies": {"DNSOverHTTPS": {
                "Enabled": True, "Locked": True, "SomethingNew": 1}}}, f)
        self.assertTrue(any("DNS" in r or "DoH" in r for r in self.reasons()))

    def test_a_domain_removed_from_the_blocklist_is_a_weakening(self):
        entries = [{"kind": "added", "domain": "gone.com"}]
        reasons = integrity.weakened(self.hosts, [], self.policy, self.unit,
                                     self.source, ledger_entries=entries)
        self.assertTrue(any("blocklist" in r for r in reasons))

    def test_a_domain_still_present_is_not(self):
        entries = [{"kind": "added", "domain": "a.com"}]
        self.assertEqual(
            integrity.weakened(self.hosts, ["a.com"], self.policy, self.unit,
                               self.source, ledger_entries=entries), [])

    def test_no_ledger_means_no_blocklist_reason(self):
        self.assertEqual(self.reasons(), [])

    def test_a_malformed_added_entry_is_skipped(self):
        entries = ["junk", {"kind": "added"}, {"kind": "added", "domain": 3}]
        self.assertEqual(integrity.unblocked_domains(entries, []), [])


if __name__ == "__main__":
    unittest.main()
