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


if __name__ == "__main__":
    unittest.main()
