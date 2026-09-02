import unittest
from blackwall_netwatch.blocklist import normalize, parse, InvalidDomain


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


if __name__ == "__main__":
    unittest.main()
