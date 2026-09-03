import unittest
from blackwall_netwatch import ladder

NOW = 1_000_000.0


def e(kind, at):
    return {"kind": kind, "at": at}


class TestUnacknowledged(unittest.TestCase):
    def test_none_when_empty(self):
        self.assertEqual(ladder.unacknowledged([], now=NOW), 0)

    def test_counts_breaches_in_the_window(self):
        entries = [e("breach", NOW - 60), e("breach", NOW - 30)]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 2)

    def test_ignores_breaches_older_than_the_window(self):
        entries = [e("breach", NOW - ladder.WINDOW_SECONDS - 1), e("breach", NOW - 5)]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 1)

    def test_an_ack_clears_everything_before_it(self):
        entries = [e("breach", NOW - 300), e("ack", NOW - 200), e("breach", NOW - 100)]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 1)

    def test_other_kinds_do_not_count(self):
        entries = [e("drift", NOW - 10), e("applied", NOW - 9), e("repair", NOW - 8),
                   e("init", NOW - 7)]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 0)

    def test_an_entry_without_a_timestamp_is_skipped_not_fatal(self):
        self.assertEqual(ladder.unacknowledged([{"kind": "breach"}], now=NOW), 0)


class TestRung(unittest.TestCase):
    def test_first_breach_challenges(self):
        self.assertEqual(ladder.rung([e("breach", NOW)], now=NOW), ladder.CHALLENGE)

    def test_second_breach_locks(self):
        entries = [e("breach", NOW - 60), e("breach", NOW)]
        self.assertEqual(ladder.rung(entries, now=NOW), ladder.LOCK)

    def test_third_also_locks(self):
        entries = [e("breach", NOW - 90), e("breach", NOW - 60), e("breach", NOW)]
        self.assertEqual(ladder.rung(entries, now=NOW), ladder.LOCK)

    def test_an_ack_between_them_drops_back_to_challenge(self):
        # Answering rung 1 is what clears it. Ignoring it is not.
        entries = [e("breach", NOW - 300), e("ack", NOW - 200), e("breach", NOW)]
        self.assertEqual(ladder.rung(entries, now=NOW), ladder.CHALLENGE)

    def test_a_breach_outside_the_window_does_not_stack(self):
        entries = [e("breach", NOW - ladder.WINDOW_SECONDS - 1), e("breach", NOW)]
        self.assertEqual(ladder.rung(entries, now=NOW), ladder.CHALLENGE)


if __name__ == "__main__":
    unittest.main()
