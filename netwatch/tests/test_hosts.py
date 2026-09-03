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


class TestExpectedLines(unittest.TestCase):
    def test_four_lines_per_domain_in_render_order(self):
        self.assertEqual(hosts.expected_lines(["a.com"]), [
            "0.0.0.0 a.com", ":: a.com",
            "0.0.0.0 www.a.com", ":: www.a.com",
        ])

    def test_render_contains_exactly_the_expected_lines(self):
        rendered = hosts.render(["a.com", "b.com"])
        for line in hosts.expected_lines(["a.com", "b.com"]):
            self.assertIn(line, rendered)


class TestRegionLines(unittest.TestCase):
    def test_returns_only_what_is_inside_the_markers(self):
        text = hosts.splice(STOCK, hosts.render(["a.com"]))
        inside = hosts.region_lines(text)
        self.assertIn("0.0.0.0 a.com", inside)
        self.assertNotIn("127.0.0.1 localhost", inside)

    def test_absent_region_is_empty_not_an_error(self):
        self.assertEqual(hosts.region_lines(STOCK), [])


class TestSpliceKeepsPosition(unittest.TestCase):
    def test_an_entry_added_after_the_region_stays_after_it(self):
        once = hosts.splice(STOCK, hosts.render(["a.com"]))
        edited = once + "10.0.0.9 later\n"
        out = hosts.splice(edited, hosts.render(["a.com"]))
        self.assertLess(out.index(hosts.END), out.index("10.0.0.9 later"))

    def test_an_unrelated_edit_after_the_region_changes_nothing_else(self):
        once = hosts.splice(STOCK, hosts.render(["a.com"]))
        edited = once + "10.0.0.9 later\n"
        self.assertEqual(hosts.splice(edited, hosts.render(["a.com"])), edited)

    def test_still_idempotent(self):
        once = hosts.splice(STOCK, hosts.render(["a.com"]))
        self.assertEqual(hosts.splice(once, hosts.render(["a.com"])), once)

    def test_appends_when_absent(self):
        out = hosts.splice(STOCK, hosts.render(["a.com"]))
        self.assertIn("127.0.0.1 localhost", out)
        self.assertIn("0.0.0.0 a.com", out)


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

    def test_invalid_utf8_does_not_raise_and_the_region_is_still_written(self):
        # hosts.apply is the FIRST call in enforce(), so a single stray byte in
        # /etc/hosts raising here would mean nothing is ever enforced again --
        # no hosts region, no DoH lock -- while the service still looks healthy.
        with open(self.path, "ab") as f:
            f.write(b"10.0.0.9 caf\xe9-box\n")
        self.assertTrue(hosts.apply(self.path, ["a.com"]))
        with open(self.path, encoding="utf-8", errors="replace") as f:
            self.assertIn("0.0.0.0 a.com", f.read())

    def test_a_missing_file_is_created_not_an_error(self):
        # Refusing to act because the file we are meant to own is not there
        # would be the same silent no-enforcement failure.
        missing = os.path.join(self.dir, "hosts-gone")
        self.assertTrue(hosts.apply(missing, ["a.com"]))
        with open(missing) as f:
            self.assertIn("0.0.0.0 a.com", f.read())


class TestSpliceMalformed(unittest.TestCase):
    def test_dangling_begin_does_not_eat_surrounding_entries(self):
        # The bug this guards: a stray marker used to make everything between it
        # and the next END vanish, operator entries included.
        corrupt = STOCK + hosts.BEGIN + "\n10.0.0.9 keepme\n"
        out = hosts.splice(corrupt, hosts.render(["a.com"]))
        self.assertIn("10.0.0.9 keepme", out)
        self.assertIn("127.0.0.1 localhost", out)
        self.assertEqual(out.count(hosts.BEGIN), 1)

    def test_dangling_end_costs_only_its_own_line(self):
        corrupt = STOCK + hosts.END + "\n10.0.0.9 keepme\n"
        out = hosts.splice(corrupt, hosts.render(["a.com"]))
        self.assertIn("10.0.0.9 keepme", out)
        self.assertEqual(out.count(hosts.END), 1)

    def test_end_before_begin_does_not_double_the_markers(self):
        corrupt = STOCK + hosts.END + "\n" + hosts.BEGIN + "\n"
        out = hosts.splice(corrupt, hosts.render(["a.com"]))
        self.assertEqual(out.count(hosts.BEGIN), 1)
        self.assertEqual(out.count(hosts.END), 1)

    def test_marker_text_inside_a_comment_is_not_a_marker(self):
        noise = "# see " + hosts.BEGIN + " for details\n" + STOCK
        out = hosts.splice(noise, hosts.render(["a.com"]))
        self.assertIn("# see", out)
        self.assertIn("127.0.0.1 localhost", out)

    def test_malformed_input_still_settles_to_idempotent(self):
        corrupt = STOCK + hosts.BEGIN + "\n10.0.0.9 keepme\n"
        once = hosts.splice(corrupt, hosts.render(["a.com"]))
        twice = hosts.splice(once, hosts.render(["a.com"]))
        self.assertEqual(once, twice)


class TestRenderBothFamilies(unittest.TestCase):
    def test_emits_an_ipv6_sink_beside_every_ipv4_sink(self):
        out = hosts.render(["a.com"])
        for host in ("a.com", "www.a.com"):
            self.assertIn("0.0.0.0 " + host, out)
            self.assertIn(":: " + host, out)


if __name__ == "__main__":
    unittest.main()
