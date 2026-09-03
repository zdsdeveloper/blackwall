import socket
import unittest
from blackwall_netwatch import probe


def answers(*addresses):
    """A getaddrinfo-shaped reply carrying these addresses."""
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
             (a, 0)) for a in addresses]


class TestClassify(unittest.TestCase):
    def test_the_sinks_netwatch_writes_are_sunk(self):
        self.assertEqual(probe.classify(["0.0.0.0"]), probe.SUNK)
        self.assertEqual(probe.classify(["::"]), probe.SUNK)

    def test_the_long_form_of_the_v6_sink_is_the_same_address(self):
        self.assertEqual(probe.classify(["0:0:0:0:0:0:0:0"]), probe.SUNK)

    def test_loopback_counts_as_sunk(self):
        # A hosts file that sinks to 127.0.0.1 is a working block, and calling
        # it a leak would be a false alarm about something that works.
        self.assertEqual(probe.classify(["127.0.0.1"]), probe.SUNK)
        self.assertEqual(probe.classify(["::1"]), probe.SUNK)

    def test_a_real_address_is_a_leak(self):
        self.assertEqual(probe.classify(["93.184.216.34"]), probe.LEAKING)

    def test_one_real_address_among_sinks_is_still_a_leak(self):
        # The whole point: anything that can route to the site is a route to
        # the site, however many dead ends sit beside it.
        self.assertEqual(
            probe.classify(["0.0.0.0", "0.0.0.0", "93.184.216.34"]),
            probe.LEAKING)

    def test_nothing_at_all_is_unresolved(self):
        self.assertEqual(probe.classify([]), probe.UNRESOLVED)

    def test_blank_entries_do_not_count_as_answers(self):
        self.assertEqual(probe.classify(["", None]), probe.UNRESOLVED)

    def test_something_that_is_not_an_address_is_treated_as_real(self):
        # Guessing "sink" here would hide a leak behind a parse failure.
        self.assertEqual(probe.classify(["not-an-address"]), probe.LEAKING)

    def test_a_non_list_does_not_raise(self):
        self.assertEqual(probe.classify(None), probe.UNKNOWN)
        self.assertEqual(probe.classify(7), probe.UNKNOWN)


class TestProbe(unittest.TestCase):
    def test_a_sunk_name(self):
        self.assertEqual(
            probe.probe("x.com", resolver=lambda *a, **k: answers("0.0.0.0")),
            probe.SUNK)

    def test_a_leaking_name(self):
        self.assertEqual(
            probe.probe("x.com", resolver=lambda *a, **k: answers("1.2.3.4")),
            probe.LEAKING)

    def test_nxdomain_is_unresolved_not_a_failure(self):
        def boom(*a, **k):
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        self.assertEqual(probe.probe("x.com", resolver=boom), probe.UNRESOLVED)

    def test_a_resolver_that_is_simply_broken_is_unknown(self):
        # Not knowing must not look like a finding in either direction.
        def boom(*a, **k):
            raise OSError("resolver unavailable")
        self.assertEqual(probe.probe("x.com", resolver=boom), probe.UNKNOWN)

    def test_a_name_the_stub_rejects_is_unknown(self):
        def boom(*a, **k):
            raise UnicodeError("label too long")
        self.assertEqual(probe.probe("x" * 300, resolver=boom), probe.UNKNOWN)

    def test_a_malformed_reply_does_not_raise(self):
        self.assertEqual(
            probe.probe("x.com", resolver=lambda *a, **k: [("nonsense",)]),
            probe.UNKNOWN)

    def test_an_empty_reply_is_unresolved(self):
        self.assertEqual(probe.probe("x.com", resolver=lambda *a, **k: []),
                         probe.UNRESOLVED)


class TestProbeAll(unittest.TestCase):
    def test_every_domain_asked_for_appears_in_the_result(self):
        out = probe.probe_all(["a.com", "b.com"],
                              resolver=lambda *a, **k: answers("0.0.0.0"))
        self.assertEqual(sorted(out), ["a.com", "b.com"])

    def test_states_are_per_domain(self):
        def resolver(name, *a, **k):
            return answers("0.0.0.0") if name == "a.com" else answers("1.2.3.4")
        out = probe.probe_all(["a.com", "b.com"], resolver=resolver)
        self.assertEqual(out["a.com"], probe.SUNK)
        self.assertEqual(out["b.com"], probe.LEAKING)

    def test_no_domains_is_an_empty_result_not_a_crash(self):
        self.assertEqual(probe.probe_all([]), {})

    def test_blank_domains_are_skipped(self):
        self.assertEqual(probe.probe_all(["", None]), {})

    def test_one_domain_raising_does_not_lose_the_others(self):
        def resolver(name, *a, **k):
            if name == "bad.com":
                raise RuntimeError("something unforeseen")
            return answers("0.0.0.0")
        out = probe.probe_all(["good.com", "bad.com"], resolver=resolver)
        self.assertEqual(out["good.com"], probe.SUNK)
        self.assertEqual(out["bad.com"], probe.UNKNOWN)

    def test_a_hung_resolver_does_not_hang_the_caller(self):
        # The reason there is a deadline at all: enforcement calls into this,
        # and a wall that stops being repaired because a nameserver is wedged
        # would be a poor trade for a readout.
        import threading
        release = threading.Event()

        def resolver(*a, **k):
            release.wait(30)
            return answers("0.0.0.0")

        try:
            out = probe.probe_all(["slow.com"], resolver=resolver, deadline=0.2)
            self.assertEqual(out["slow.com"], probe.UNKNOWN)
        finally:
            release.set()


class TestSummarise(unittest.TestCase):
    def test_counts_by_state(self):
        out = probe.summarise({"a": probe.SUNK, "b": probe.SUNK,
                               "c": probe.LEAKING})
        self.assertEqual(out[probe.SUNK], 2)
        self.assertEqual(out[probe.LEAKING], 1)
        self.assertEqual(out[probe.UNRESOLVED], 0)

    def test_an_unexpected_state_lands_in_unknown(self):
        self.assertEqual(probe.summarise({"a": "banana"})[probe.UNKNOWN], 1)

    def test_a_non_dict_does_not_raise(self):
        self.assertEqual(probe.summarise(None)[probe.SUNK], 0)


class TestLeaking(unittest.TestCase):
    def test_names_a_real_address_came_back_for(self):
        self.assertEqual(
            probe.leaking({"b.com": probe.LEAKING, "a.com": probe.LEAKING,
                           "c.com": probe.SUNK}),
            ["a.com", "b.com"])

    def test_nothing_leaking_is_empty(self):
        self.assertEqual(probe.leaking({"a.com": probe.SUNK}), [])

    def test_a_non_dict_does_not_raise(self):
        self.assertEqual(probe.leaking(None), [])


if __name__ == "__main__":
    unittest.main()
