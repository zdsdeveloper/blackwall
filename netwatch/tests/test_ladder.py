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

    def test_a_future_dated_breach_does_not_count(self):
        # Clock skew and NTP corrections happen. A negative age satisfies an
        # upper bound alone and would hold the ladder at lock-eligible for ever.
        self.assertEqual(ladder.unacknowledged([e("breach", NOW + 3600)], now=NOW), 0)

    def test_a_non_dict_entry_is_skipped_not_fatal(self):
        entries = ["junk", 3, None, e("breach", NOW)]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 1)

    def test_a_boolean_timestamp_is_skipped(self):
        self.assertEqual(ladder.unacknowledged([{"kind": "breach", "at": True}], now=NOW), 0)

    def test_an_ack_without_a_timestamp_still_clears(self):
        # An acknowledgement clears what came before it whether or not the entry
        # carrying it survived intact.
        entries = [e("breach", NOW - 100), {"kind": "ack"}, e("breach", NOW)]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 1)


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

    def test_a_future_dated_breach_does_not_stack_into_a_lock(self):
        entries = [e("breach", NOW + 3600), e("breach", NOW)]
        self.assertEqual(ladder.rung(entries, now=NOW), ladder.CHALLENGE)


class TestPendingToken(unittest.TestCase):
    def test_none_when_no_breach(self):
        self.assertIsNone(ladder.pending_token([]))

    def test_the_token_of_the_latest_unacknowledged_breach(self):
        entries = [{"kind": "breach", "at": NOW - 10, "token": "aaa"},
                   {"kind": "breach", "at": NOW, "token": "bbb"}]
        self.assertEqual(ladder.pending_token(entries), "bbb")

    def test_none_once_acknowledged(self):
        entries = [{"kind": "breach", "at": NOW - 10, "token": "aaa"},
                   {"kind": "ack", "at": NOW, "token": "aaa"}]
        self.assertIsNone(ladder.pending_token(entries))

    def test_a_breach_after_an_ack_is_pending_again(self):
        entries = [{"kind": "breach", "at": NOW - 20, "token": "aaa"},
                   {"kind": "ack", "at": NOW - 10, "token": "aaa"},
                   {"kind": "breach", "at": NOW, "token": "ccc"}]
        self.assertEqual(ladder.pending_token(entries), "ccc")

    def test_a_breach_without_a_token_yields_none(self):
        # Breaches recorded before this task carry no token; they cannot be
        # acknowledged, and must not crash the lookup either.
        self.assertIsNone(ladder.pending_token([{"kind": "breach", "at": NOW}]))

    def test_a_non_dict_entry_is_skipped(self):
        self.assertIsNone(ladder.pending_token(["junk", 3, None]))


if __name__ == "__main__":
    unittest.main()
