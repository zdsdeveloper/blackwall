import os
import tempfile
import unittest
from blackwall_netwatch import ledger


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "ledger.jsonl")

    def test_record_returns_entry_with_kind_and_timestamp(self):
        entry = ledger.record(self.path, "added", domain="a.com")
        self.assertEqual(entry["kind"], "added")
        self.assertEqual(entry["domain"], "a.com")
        self.assertIn("at", entry)

    def test_records_append_and_read_back_in_order(self):
        ledger.record(self.path, "added", domain="a.com")
        ledger.record(self.path, "breach", target="hosts")
        entries = ledger.read(self.path)
        self.assertEqual([e["kind"] for e in entries], ["added", "breach"])

    def test_read_missing_file_is_empty(self):
        self.assertEqual(ledger.read(self.path), [])

    def test_read_skips_a_corrupt_line_without_losing_the_rest(self):
        ledger.record(self.path, "added", domain="a.com")
        with open(self.path, "a") as f:
            f.write("{ truncated\n")
        ledger.record(self.path, "added", domain="b.com")
        self.assertEqual(len(ledger.read(self.path)), 2)

    def test_file_is_created_root_readable_only_for_write(self):
        ledger.record(self.path, "added", domain="a.com")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o644)

    def test_truncated_multibyte_sequence_does_not_raise(self):
        # A killed process can cut a UTF-8 character in half at EOF. That must
        # cost the damaged entry, never the call.
        ledger.record(self.path, "added", domain="a.com")
        with open(self.path, "ab") as f:
            f.write(b'{"kind": "added", "domain": "caf\xc3')
        entries = ledger.read(self.path)
        self.assertEqual([e["kind"] for e in entries], ["added"])

    def test_valid_json_that_is_not_an_object_is_skipped(self):
        ledger.record(self.path, "added", domain="a.com")
        with open(self.path, "a") as f:
            f.write("[1, 2]\n")
            f.write('"text"\n')
            f.write("3\n")
        entries = ledger.read(self.path)
        self.assertEqual(len(entries), 1)
        self.assertTrue(all(isinstance(e, dict) for e in entries))

    def test_mode_is_guaranteed_regardless_of_umask(self):
        old = os.umask(0o077)
        try:
            path = os.path.join(self.dir, "restrictive.jsonl")
            ledger.record(path, "added", domain="a.com")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)
        finally:
            os.umask(old)

    def test_a_line_containing_a_nul_byte_costs_only_that_line(self):
        ledger.record(self.path, "added", domain="a.com")
        with open(self.path, "ab") as f:
            f.write(b'{"kind": "x"}\x00\n')
        self.assertEqual(len(ledger.read(self.path)), 1)


if __name__ == "__main__":
    unittest.main()
