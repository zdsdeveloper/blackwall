import json
import os
import tempfile
import unittest
from blackwall_netwatch import zenpolicy

PACKAGE = {"DisableAppUpdate": True, "DefaultSerialGuardSetting": 3}


class TestReadPackagePolicies(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "policies.json")

    def test_reads_policies_key(self):
        with open(self.path, "w") as f:
            json.dump({"policies": PACKAGE}, f)
        self.assertEqual(zenpolicy.read_package_policies(self.path), PACKAGE)

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(zenpolicy.read_package_policies(self.path), {})

    def test_malformed_file_is_empty_not_an_error(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(zenpolicy.read_package_policies(self.path), {})


class TestRender(unittest.TestCase):
    def test_locks_doh_off(self):
        got = json.loads(zenpolicy.render({}))["policies"]["DNSOverHTTPS"]
        self.assertEqual(got, {"Enabled": False, "Locked": True})

    def test_carries_forward_package_policies(self):
        got = json.loads(zenpolicy.render(PACKAGE))["policies"]
        self.assertTrue(got["DisableAppUpdate"])
        self.assertEqual(got["DefaultSerialGuardSetting"], 3)

    def test_our_policy_wins_over_a_conflicting_package_value(self):
        hostile = {"DNSOverHTTPS": {"Enabled": True, "Locked": False}}
        got = json.loads(zenpolicy.render(hostile))["policies"]["DNSOverHTTPS"]
        self.assertEqual(got, {"Enabled": False, "Locked": True})


class TestApply(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "policies.json")

    def test_creates_then_reports_no_further_change(self):
        self.assertTrue(zenpolicy.apply(self.path, PACKAGE))
        self.assertFalse(zenpolicy.apply(self.path, PACKAGE))

    def test_creates_parent_directories(self):
        nested = os.path.join(self.dir, "zen", "policies", "policies.json")
        self.assertTrue(zenpolicy.apply(nested, {}))
        self.assertTrue(os.path.exists(nested))

    def test_repairs_a_tampered_file(self):
        zenpolicy.apply(self.path, PACKAGE)
        with open(self.path, "w") as f:
            f.write('{"policies": {}}')
        self.assertTrue(zenpolicy.apply(self.path, PACKAGE))
        got = json.loads(open(self.path).read())["policies"]["DNSOverHTTPS"]
        self.assertEqual(got, {"Enabled": False, "Locked": True})


if __name__ == "__main__":
    unittest.main()
