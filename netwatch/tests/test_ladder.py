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


class TestGracedStarts(unittest.TestCase):
    """A graced start is on the ladder but not on the screen.

    Two properties, deliberately pinned apart so a later change cannot collapse
    them back into one: the grace decides whether a weakening is shown, never
    whether it counts.
    """

    def test_a_graced_start_counts_toward_the_rung(self):
        # The grace buys silence about a weakening, not forgiveness for it. The
        # operator chose this explicitly, including that it can mean a lock with
        # no challenge shown first.
        entries = [e("graced", NOW - 60), e("breach", NOW)]
        self.assertEqual(ladder.rung(entries, now=NOW), ladder.LOCK)

    def test_a_graced_start_alone_is_one_not_two(self):
        self.assertEqual(ladder.unacknowledged([e("graced", NOW)], now=NOW), 1)

    def test_an_ack_clears_a_graced_start_too(self):
        entries = [e("graced", NOW - 60), {"kind": "ack", "at": NOW}]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 0)

    def test_a_graced_start_is_never_delivered(self):
        # The other half, and the reason the kind exists at all: a daemon
        # coming up mid-transaction must not put a challenge on screen for
        # part-written files. Counted, and still not shown.
        self.assertFalse(ladder.needs_delivery([e("graced", NOW)]))
        self.assertIsNone(ladder.pending_delivery([e("graced", NOW)]))


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


class TestDelivery(unittest.TestCase):
    def test_a_breach_with_no_delivery_needs_one(self):
        self.assertTrue(ladder.needs_delivery([e("breach", NOW)]))

    def test_a_delivered_breach_does_not_need_another(self):
        entries = [e("breach", NOW - 10),
                   {"kind": "delivered", "at": NOW, "token_hash": "aa"}]
        self.assertFalse(ladder.needs_delivery(entries))

    def test_a_new_breach_after_a_delivery_needs_one(self):
        entries = [e("breach", NOW - 20),
                   {"kind": "delivered", "at": NOW - 10, "token_hash": "aa"},
                   e("breach", NOW)]
        self.assertTrue(ladder.needs_delivery(entries))

    def test_nothing_pending_needs_nothing(self):
        self.assertFalse(ladder.needs_delivery([]))
        self.assertFalse(ladder.needs_delivery([e("drift", NOW)]))

    def test_an_acknowledged_breach_needs_nothing(self):
        entries = [e("breach", NOW - 20),
                   {"kind": "delivered", "at": NOW - 10, "token_hash": "aa"},
                   {"kind": "ack", "at": NOW, "token_hash": "aa"}]
        self.assertFalse(ladder.needs_delivery(entries))

    def test_pending_delivery_is_the_latest_undelivered_hash(self):
        entries = [{"kind": "delivered", "at": NOW - 10, "token_hash": "aa"},
                   {"kind": "delivered", "at": NOW, "token_hash": "bb"}]
        self.assertEqual(ladder.pending_delivery(entries), "bb")

    def test_a_delivery_after_an_ack_is_pending_again(self):
        # Restored coverage: the delivery/ack/delivery cycle has to hand back
        # the NEW hash, or a second challenge could be answered with the token
        # from the first.
        entries = [{"kind": "delivered", "at": NOW - 20, "token_hash": "aa"},
                   {"kind": "ack", "at": NOW - 10, "token_hash": "aa"},
                   {"kind": "delivered", "at": NOW, "token_hash": "cc"}]
        self.assertEqual(ladder.pending_delivery(entries), "cc")

    def test_pending_delivery_is_cleared_by_an_ack(self):
        entries = [{"kind": "delivered", "at": NOW - 10, "token_hash": "aa"},
                   {"kind": "ack", "at": NOW, "token_hash": "aa"}]
        self.assertIsNone(ladder.pending_delivery(entries))

    def test_a_delivery_without_a_token_hash_yields_none(self):
        # Nothing can be presented against it, and it must not crash the
        # lookup either.
        self.assertIsNone(ladder.pending_delivery([{"kind": "delivered", "at": NOW}]))

    def test_a_non_dict_entry_is_skipped(self):
        # A truncated or hand-written ledger line must not take either lookup
        # down with it.
        self.assertIsNone(ladder.pending_delivery(["junk", 3, None]))
        self.assertFalse(ladder.needs_delivery(["junk", 3, None]))


if __name__ == "__main__":
    unittest.main()
