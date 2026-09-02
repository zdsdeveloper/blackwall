import dataclasses
import json
import os
import tempfile
import time
import unittest
from blackwall_netwatch.daemon import NetWatch, Paths
from blackwall_netwatch.server import handle
from blackwall_netwatch import ledger, server


def paths_in(d):
    return Paths(
        blocklist=os.path.join(d, "blocklist"),
        ledger=os.path.join(d, "ledger.jsonl"),
        hosts=os.path.join(d, "hosts"),
        zen_policy=os.path.join(d, "zen", "policies", "policies.json"),
        zen_package_policy=os.path.join(d, "dist.json"),
        window_marker=os.path.join(d, "pacman-window"),
        pacman_lock=os.path.join(d, "db.lck"),
        socket=os.path.join(d, "netwatch.sock"),
    )


class TestHandle(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "hosts"), "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.nw = NetWatch(paths_in(self.dir))

    def test_add_returns_the_normalised_domain(self):
        reply = handle(self.nw, {"cmd": "add", "domain": "https://WWW.A.com/"})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["domain"], "a.com")

    def test_add_rejects_garbage_with_a_message(self):
        reply = handle(self.nw, {"cmd": "add", "domain": "localhost"})
        self.assertFalse(reply["ok"])
        self.assertIn("localhost", reply["error"])

    def test_list_returns_domains(self):
        handle(self.nw, {"cmd": "add", "domain": "a.com"})
        self.assertEqual(handle(self.nw, {"cmd": "list"})["domains"], ["a.com"])

    def test_status_reports_counts(self):
        self.assertEqual(handle(self.nw, {"cmd": "status"})["domains"], 0)

    def test_enforce_repairs_and_reports(self):
        # The pacman hook calls this inside its window; without it the repair
        # would land after the window closed and read as tampering.
        handle(self.nw, {"cmd": "add", "domain": "a.com"})
        reply = handle(self.nw, {"cmd": "enforce"})
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["result"]["changed"])

    def test_enforce_with_close_window_drops_the_marker(self):
        # The hook used to rm this itself; a failed or undelivered enforce then
        # left changed files with no window open and the next cycle called a
        # routine upgrade a breach. Only a completed enforce may close it.
        with open(self.nw.paths.window_marker, "w") as f:
            f.write("")
        handle(self.nw, {"cmd": "enforce", "close_window": True})
        self.assertFalse(os.path.exists(self.nw.paths.window_marker))

    def test_enforce_without_the_flag_leaves_the_marker(self):
        with open(self.nw.paths.window_marker, "w") as f:
            f.write("")
        handle(self.nw, {"cmd": "enforce"})
        self.assertTrue(os.path.exists(self.nw.paths.window_marker))

    def test_remove_is_not_a_command(self):
        reply = handle(self.nw, {"cmd": "remove", "domain": "a.com"})
        self.assertFalse(reply["ok"])

    def test_unknown_command_is_refused_not_crashing(self):
        reply = handle(self.nw, {"cmd": "nonsense"})
        self.assertFalse(reply["ok"])

    def test_malformed_request_is_refused(self):
        self.assertFalse(handle(self.nw, {})["ok"])
        self.assertFalse(handle(self.nw, {"cmd": "add"})["ok"])


class _Exploding:
    def __init__(self, paths):
        self.paths = paths
        self.enforce_failures = 0

    def enforce(self):
        raise RuntimeError("boom")


class _Flaky(_Exploding):
    """Fails until told otherwise."""

    def __init__(self, paths):
        _Exploding.__init__(self, paths)
        self.failing = True

    def enforce(self):
        if self.failing:
            raise RuntimeError("boom")
        return {"changed": False, "verdict": None, "targets": []}


class TestEnforceBackstop(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = paths_in(self.dir)

    def test_no_exception_escapes_the_backstop(self):
        result = server._enforce_quietly(_Exploding(self.paths))
        self.assertFalse(result["changed"])
        self.assertIsNone(result["verdict"])
        self.assertEqual(result["targets"], [])

    def test_the_failure_is_recorded(self):
        server._enforce_quietly(_Exploding(self.paths))
        kinds = [e["kind"] for e in ledger.read(self.paths.ledger)]
        self.assertIn("enforce-failed", kinds)

    def test_a_ledger_that_also_fails_still_does_not_raise(self):
        broken = dataclasses.replace(
            self.paths, ledger="/nonexistent-directory/ledger.jsonl")
        result = server._enforce_quietly(_Exploding(broken))
        self.assertFalse(result["changed"])

    def test_the_failure_count_rises_and_clears(self):
        # The only signal that the daemon is up and not enforcing.
        nw = _Flaky(self.paths)
        server._enforce_quietly(nw)
        self.assertEqual(nw.enforce_failures, 1)
        nw.failing = False
        server._enforce_quietly(nw)
        self.assertEqual(nw.enforce_failures, 0)

    def test_repeated_failures_are_recorded_once_not_once_each(self):
        # _enforce_quietly runs after every connection on a 0666 socket, so one
        # line per failure lets any local user drive unbounded appends into
        # root-owned /var precisely while enforcement is broken.
        nw = _Exploding(self.paths)
        for _ in range(5):
            server._enforce_quietly(nw)
        failed = [e for e in ledger.read(self.paths.ledger)
                  if e.get("kind") == "enforce-failed"]
        self.assertEqual(len(failed), 1)


class _FakeConn:
    """Drives serve_connection without a socket: scripted reads, captured writes."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = b""

    def settimeout(self, seconds):
        pass

    def recv(self, size):
        return self.chunks.pop(0) if self.chunks else b""

    def sendall(self, data):
        self.sent += data


class _BrokenConn(_FakeConn):
    def sendall(self, data):
        raise BrokenPipeError("peer went away")


class _DrippingConn:
    """A peer that keeps sending, slowly, and never sends a newline.

    The old loop bounded each individual recv and nothing else, so this pattern
    held the single-threaded accept loop for as long as the peer cared to keep
    it -- and nothing is enforced while a connection is open.
    """

    def __init__(self, per_recv):
        self.per_recv = per_recv
        self.timeout = None
        self.recv_calls = 0

    def settimeout(self, seconds):
        self.timeout = seconds

    def recv(self, size):
        self.recv_calls += 1
        budget = self.per_recv if self.timeout is None else self.timeout
        time.sleep(min(self.per_recv, budget))
        if self.timeout is not None and self.per_recv > self.timeout:
            raise TimeoutError("timed out")
        return b"x"


class TestReadRequestDeadline(unittest.TestCase):
    def test_a_dripping_peer_is_cut_off_at_the_deadline(self):
        conn = _DrippingConn(per_recv=0.01)
        original = server.REQUEST_DEADLINE_SECONDS
        server.REQUEST_DEADLINE_SECONDS = 0.05
        try:
            started = time.monotonic()
            self.assertIsNone(server._read_request(conn))
            elapsed = time.monotonic() - started
        finally:
            server.REQUEST_DEADLINE_SECONDS = original
        self.assertLess(elapsed, 1.0)
        # Cut off by the clock, not by the byte cap: the cap alone would have
        # let this run for 65536 reads at whatever pace the peer chose.
        self.assertLess(conn.recv_calls, 100)


class TestServeConnection(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "hosts"), "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.nw = NetWatch(paths_in(self.dir), flusher=lambda: None)

    def test_a_peer_that_hangs_up_mid_reply_does_not_raise(self):
        # The socket is 0666 by design, so connect-then-disconnect is ordinary.
        # Before this guard it was a two-syscall kill for the whole daemon.
        server.serve_connection(self.nw, _BrokenConn([b'{"cmd": "status"}\n']))

    def test_a_request_split_across_reads_is_understood(self):
        conn = _FakeConn([b'{"cmd": "sta', b'tus"}\n'])
        server.serve_connection(self.nw, conn)
        self.assertTrue(json.loads(conn.sent.decode("utf-8"))["ok"])

    def test_a_client_that_sends_nothing_gets_no_reply(self):
        conn = _FakeConn([])
        server.serve_connection(self.nw, conn)
        self.assertEqual(conn.sent, b"")

    def test_malformed_json_is_refused_not_fatal(self):
        conn = _FakeConn([b"{ not json\n"])
        server.serve_connection(self.nw, conn)
        self.assertFalse(json.loads(conn.sent.decode("utf-8"))["ok"])

    def test_an_oversized_request_is_bounded(self):
        flood = [b"x" * 4096] * 40
        conn = _FakeConn(flood)
        server.serve_connection(self.nw, conn)
        self.assertFalse(json.loads(conn.sent.decode("utf-8"))["ok"])


if __name__ == "__main__":
    unittest.main()
