import os
import tempfile
import unittest
from blackwall_netwatch import hosts

STOCK = "# Static table lookup for hostnames.\n127.0.0.1 localhost\n::1 localhost\n"


class TestRender(unittest.TestCase):
    def test_renders_apex_and_www_between_markers(self):
        out = hosts.render(["a.com"])
        self.assertTrue(out.startswith(hosts.BEGIN))
        self.assertTrue(out.rstrip().endswith(hosts.END))
        self.assertIn("0.0.0.0 a.com", out)
        self.assertIn("0.0.0.0 www.a.com", out)

    def test_empty_list_still_renders_markers(self):
        out = hosts.render([])
        self.assertIn(hosts.BEGIN, out)
        self.assertIn(hosts.END, out)


class TestSplice(unittest.TestCase):
    def test_appends_when_absent_and_preserves_existing(self):
        out = hosts.splice(STOCK, hosts.render(["a.com"]))
        self.assertIn("127.0.0.1 localhost", out)
        self.assertIn("0.0.0.0 a.com", out)

    def test_is_idempotent(self):
        once = hosts.splice(STOCK, hosts.render(["a.com"]))
        twice = hosts.splice(once, hosts.render(["a.com"]))
        self.assertEqual(once, twice)

    def test_replaces_region_without_touching_surroundings(self):
        once = hosts.splice(STOCK, hosts.render(["a.com"]))
        updated = hosts.splice(once, hosts.render(["b.com"]))
        self.assertNotIn("a.com", updated)
        self.assertIn("0.0.0.0 b.com", updated)
        self.assertIn("127.0.0.1 localhost", updated)

    def test_preserves_trailing_content_after_region(self):
        with_tail = hosts.splice(STOCK, hosts.render(["a.com"])) + "10.0.0.1 later\n"
        updated = hosts.splice(with_tail, hosts.render(["b.com"]))
        self.assertIn("10.0.0.1 later", updated)


class TestApply(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "hosts")
        with open(self.path, "w") as f:
            f.write(STOCK)

    def test_writes_and_reports_change_then_reports_no_change(self):
        self.assertTrue(hosts.apply(self.path, ["a.com"]))
        self.assertFalse(hosts.apply(self.path, ["a.com"]))
        with open(self.path) as f:
            self.assertIn("0.0.0.0 a.com", f.read())

    def test_preserves_mode(self):
        os.chmod(self.path, 0o644)
        hosts.apply(self.path, ["a.com"])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o644)

    def test_leaves_no_temp_files_behind(self):
        hosts.apply(self.path, ["a.com"])
        self.assertEqual(os.listdir(self.dir), ["hosts"])


if __name__ == "__main__":
    unittest.main()
