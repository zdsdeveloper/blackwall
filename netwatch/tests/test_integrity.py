import json
import os
import tempfile
import unittest
from unittest import mock
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

    def test_the_same_ledger_entry_discriminates_present_from_absent(self):
        # Replaces a check that only proved the default argument exists and
        # passed against the pre-fix code either way: the same ledger entry
        # must produce a reason when its domain is missing from the
        # blocklist and must not when the domain is there.
        entries = [{"kind": "added", "domain": "a.com"}]
        self.assertTrue(any("blocklist" in r for r in
            integrity.weakened(self.hosts, [], self.policy, self.unit,
                               self.source, ledger_entries=entries)))
        self.assertEqual(
            integrity.weakened(self.hosts, ["a.com"], self.policy, self.unit,
                               self.source, ledger_entries=entries), [])

    def test_a_malformed_added_entry_is_skipped(self):
        entries = ["junk", {"kind": "added"}, {"kind": "added", "domain": 3}]
        self.assertEqual(integrity.unblocked_domains(entries, []), [])


class TestWasArmed(unittest.TestCase):
    def test_true_once_an_armed_entry_exists(self):
        self.assertTrue(integrity.was_armed([{"kind": "armed"}]))

    def test_false_with_no_armed_entry(self):
        self.assertFalse(integrity.was_armed([{"kind": "added", "domain": "a.com"}]))

    def test_false_on_an_empty_ledger(self):
        self.assertFalse(integrity.was_armed([]))

    def test_ignores_a_malformed_entry(self):
        self.assertFalse(integrity.was_armed(["junk", {"kind": "armed?"}]))


class TestLedgerAppendOnlyWeakening(unittest.TestCase):
    """`append_only` cannot be exercised against a real append-only file
    without root, so these test the seam in `weakened` instead: what it does
    with each of append_only's three possible answers, monkeypatched."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.hosts = os.path.join(self.dir, "hosts")
        self.policy = os.path.join(self.dir, "policies.json")
        self.unit = os.path.join(self.dir, "unit.service")
        self.source = os.path.join(self.dir, "unit.source")
        self.ledger_path = os.path.join(self.dir, "ledger.jsonl")
        with open(self.hosts, "w") as f:
            f.write(hosts.splice("127.0.0.1 localhost\n", hosts.render([])))
        with open(self.policy, "w") as f:
            json.dump({"policies": {"DNSOverHTTPS": {"Enabled": False, "Locked": True}}}, f)
        for path in (self.unit, self.source):
            with open(path, "w") as f:
                f.write("[Service]\nExecStart=/usr/local/bin/blackwall-netwatch\n")

    def reasons(self, ledger_entries):
        return integrity.weakened(self.hosts, [], self.policy, self.unit,
                                  self.source, ledger_entries=ledger_entries,
                                  ledger_path=self.ledger_path)

    def test_an_unarmed_ledger_is_not_a_weakening(self):
        # Not yet armed: absence of the attribute is not evidence of anything,
        # so append_only is never even consulted.
        with mock.patch.object(integrity, "append_only", return_value=False):
            self.assertEqual(self.reasons([]), [])

    def test_an_armed_ledger_that_lost_the_attribute_is_a_weakening(self):
        with mock.patch.object(integrity, "append_only", return_value=False):
            reasons = self.reasons([{"kind": "armed"}])
        self.assertTrue(any("ledger" in r for r in reasons))

    def test_a_filesystem_that_cannot_answer_is_not_a_weakening(self):
        # None, not False: /var on tmpfs is not tampering.
        with mock.patch.object(integrity, "append_only", return_value=None):
            self.assertEqual(self.reasons([{"kind": "armed"}]), [])

    def test_an_armed_ledger_still_append_only_is_not_a_weakening(self):
        with mock.patch.object(integrity, "append_only", return_value=True):
            self.assertEqual(self.reasons([{"kind": "armed"}]), [])

    def test_no_ledger_path_skips_the_check_entirely(self):
        # The default: callers that do not pass ledger_path get the old
        # behaviour, untouched by whatever append_only would have said.
        with mock.patch.object(integrity, "append_only", return_value=False):
            reasons = integrity.weakened(self.hosts, [], self.policy,
                                         self.unit, self.source,
                                         ledger_entries=[{"kind": "armed"}])
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
