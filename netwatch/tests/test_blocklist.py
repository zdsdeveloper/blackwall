import unittest
from blackwall_netwatch.blocklist import normalize, parse, parse_lines, InvalidDomain


class TestNormalize(unittest.TestCase):
    def test_strips_scheme_path_query_and_case(self):
        self.assertEqual(normalize("https://WWW.Example.COM/a/b?q=1"), "example.com")

    def test_strips_port_userinfo_and_trailing_dot(self):
        self.assertEqual(normalize("user@Example.com.:8443"), "example.com")

    def test_keeps_non_www_subdomains(self):
        self.assertEqual(normalize("cdn.example.com"), "cdn.example.com")

    def test_rejects_bare_label(self):
        with self.assertRaises(InvalidDomain):
            normalize("localhost")

    def test_rejects_empty(self):
        with self.assertRaises(InvalidDomain):
            normalize("   ")

    def test_rejects_bad_characters(self):
        with self.assertRaises(InvalidDomain):
            normalize("exa_mple.com")


class TestParse(unittest.TestCase):
    def test_ignores_comments_and_blanks_dedupes_and_sorts(self):
        text = "\n".join([
            "# a comment",
            "",
            "https://www.B.com/",
            "a.com   # trailing comment",
            "b.com",
        ])
        self.assertEqual(parse(text), ["a.com", "b.com"])


class TestParseIsNotFatal(unittest.TestCase):
    def test_one_bad_line_does_not_lose_the_good_ones(self):
        # The blocklist is append-only once armed, so appending junk is the one
        # write that still succeeds. If that could abort the parse, it would be
        # enough to take the wall down.
        self.assertEqual(parse("a.com\nlocalhost\nb.com\n"), ["a.com", "b.com"])

    def test_parse_never_raises_on_garbage(self):
        self.assertEqual(parse("!!!\n\n@@@\n"), [])

    def test_parse_lines_reports_what_it_dropped(self):
        domains, rejected = parse_lines("a.com\nlocalhost\n")
        self.assertEqual(domains, ["a.com"])
        self.assertEqual(rejected, ["localhost"])

    def test_parse_lines_rejects_are_in_file_order(self):
        _, rejected = parse_lines("zzz\na.com\naaa\n")
        self.assertEqual(rejected, ["zzz", "aaa"])

    def test_normalize_still_raises_so_add_can_reject_at_the_door(self):
        with self.assertRaises(InvalidDomain):
            normalize("localhost")


if __name__ == "__main__":
    unittest.main()
