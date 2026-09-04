import json
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


class TestReadCache(unittest.TestCase):
    """Repeated reads are cached on the file's size and mtime.

    `read` is called from nine places, one of them status, which a panel polls
    every two seconds -- and the ledger is append-only by design, so the cost
    of re-parsing it rises for ever. At 2660 entries a status call was already
    spending 58ms re-reading a history that had not changed.

    The danger of caching this is far worse than the cost of not: the ladder
    decides whether to lock the screen from these entries, so a stale read is
    a wrong decision about someone's session. Every test below is about the
    cache noticing a change.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "ledger.jsonl")
        ledger.forget()

    def tearDown(self):
        ledger.forget()

    def test_a_second_read_agrees_with_the_first(self):
        ledger.record(self.path, "added", domain="a.com")
        first = ledger.read(self.path)
        self.assertEqual(ledger.read(self.path), first)

    def test_an_append_is_seen(self):
        # The one that matters. A cache that missed this would let the ladder
        # act on a history that is missing the breach that just happened.
        ledger.record(self.path, "added", domain="a.com")
        self.assertEqual(len(ledger.read(self.path)), 1)
        ledger.record(self.path, "breach", reasons=["unit: masked"])
        after = ledger.read(self.path)
        self.assertEqual(len(after), 2)
        self.assertEqual(after[-1]["kind"], "breach")

    def test_many_appends_are_each_seen(self):
        for i in range(12):
            ledger.record(self.path, "added", domain="d%d.com" % i)
            self.assertEqual(len(ledger.read(self.path)), i + 1)

    def test_a_file_rewritten_smaller_is_seen(self):
        # Not reachable while the ledger is append-only, but a cache keyed on
        # a file must notice the file being replaced.
        for i in range(5):
            ledger.record(self.path, "added", domain="d%d.com" % i)
        self.assertEqual(len(ledger.read(self.path)), 5)
        with open(self.path, "w") as f:
            f.write(json.dumps({"kind": "ack", "at": 1}) + "\n")
        self.assertEqual(len(ledger.read(self.path)), 1)

    def test_the_caller_cannot_poison_the_cache(self):
        # Callers filter and slice what they get. Handing out the cached list
        # itself would let one of them change what every later reader sees.
        ledger.record(self.path, "added", domain="a.com")
        got = ledger.read(self.path)
        got.append({"kind": "forged"})
        self.assertEqual(len(ledger.read(self.path)), 1)

    def test_a_missing_file_is_still_empty(self):
        self.assertEqual(ledger.read(os.path.join(self.dir, "nope.jsonl")), [])

    def test_a_missing_file_that_appears_is_seen(self):
        missing = os.path.join(self.dir, "later.jsonl")
        self.assertEqual(ledger.read(missing), [])
        ledger.record(missing, "added", domain="a.com")
        self.assertEqual(len(ledger.read(missing)), 1)
