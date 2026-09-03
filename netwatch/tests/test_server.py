import dataclasses
import json
import os
import tempfile
import time
import unittest
from blackwall_netwatch.daemon import NetWatch, Paths
from blackwall_netwatch.server import handle
from blackwall_netwatch import daemon, ladder, ledger, server


UNIT = "[Service]\nExecStart=/usr/local/bin/blackwall-netwatch\n"


def paths_in(d):
    """Paths under `d`, with the daemon's own unit installed and intact.

    The unit files are written here, not in each setUp: an intact wall is the
    precondition these tests assume, and without them a test about the socket
    would also be asserting over a weakened unit.
    """
    paths = Paths(
        blocklist=os.path.join(d, "blocklist"),
        ledger=os.path.join(d, "ledger.jsonl"),
        hosts=os.path.join(d, "hosts"),
        zen_policy=os.path.join(d, "zen", "policies", "policies.json"),
        zen_package_policy=os.path.join(d, "dist.json"),
        window_marker=os.path.join(d, "pacman-window"),
        pacman_lock=os.path.join(d, "db.lck"),
        unit_file=os.path.join(d, "blackwall-netwatch.service"),
        unit_source=os.path.join(d, "unit-source.service"),
        socket=os.path.join(d, "netwatch.sock"),
    )
    for path in (paths.unit_file, paths.unit_source):
        with open(path, "w") as f:
            f.write(UNIT)
    return paths


def quiet_notifier(method, args=()):
    """Never the real one. session.notify reads the live /proc and shells out
    to the session's IPC, and an escalation out of a test would lock the screen
    of whoever is sitting at the machine running it."""
    return False


class TestHandle(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "hosts"), "w") as f:
            f.write("127.0.0.1 localhost\n")
        # flusher stubbed for the same reason TestServeConnection stubs it: run
        # as root -- entirely plausible for a root daemon -- the enforce tests
        # below would otherwise shell out to the live resolvectl.
        self.proc = os.path.join(self.dir, "proc")
        os.makedirs(self.proc)
        self.nw = NetWatch(
            paths_in(self.dir), flusher=lambda: None, proc_dir=self.proc,
            notifier=quiet_notifier)

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

    def test_enforce_with_close_window_drops_the_marker_for_root(self):
        # The hook used to rm this itself; a failed or undelivered enforce then
        # left changed files with no window open and the next cycle called a
        # routine upgrade a breach. Only a completed enforce may close it.
        with open(self.nw.paths.window_marker, "w") as f:
            f.write("")
        reply = handle(
            self.nw, {"cmd": "enforce", "close_window": True}, peer_is_root=True)
        self.assertTrue(reply["ok"])
        self.assertFalse(os.path.exists(self.nw.paths.window_marker))

    def test_close_window_is_refused_to_an_unprivileged_peer(self):
        # The socket is 0666 so anyone may ADD. Dropping the marker is a
        # different privilege: a local user closing the window in a loop during
        # a pacman -Syu would make every replaced file read as tampering.
        with open(self.nw.paths.window_marker, "w") as f:
            f.write("")
        reply = handle(self.nw, {"cmd": "enforce", "close_window": True})
        self.assertFalse(reply["ok"])
        self.assertIn("root", reply["error"])
        self.assertTrue(os.path.exists(self.nw.paths.window_marker))

    def test_enforce_without_the_flag_leaves_the_marker(self):
        with open(self.nw.paths.window_marker, "w") as f:
            f.write("")
        # And the lock, so the window belongs to a transaction that still
        # exists: enforce() now reaps a window with nothing running behind it.
        with open(self.nw.paths.pacman_lock, "w") as f:
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

    def test_a_full_blocklist_is_refused_not_raised(self):
        # The cap is reached by lowering it rather than by writing 50000 real
        # domains: what is being tested is the refusal, not the number. An
        # exception escaping here would reach serve_connection's generic guard
        # and tell the operator "internal error".
        original = daemon.MAX_DOMAINS
        daemon.MAX_DOMAINS = 0
        try:
            reply = handle(self.nw, {"cmd": "add", "domain": "a.com"})
        finally:
            daemon.MAX_DOMAINS = original
        self.assertFalse(reply["ok"])
        self.assertIn("full", reply["error"])


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


class _CtxConn(_FakeConn):
    """A fake connection usable in `with conn:`, as a real socket is."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _BrokenConn(_FakeConn):
    def sendall(self, data):
        raise BrokenPipeError("peer went away")


class _ExplodingReplyConn(_FakeConn):
    """A connection whose reply write fails in a way _reply does not absorb.

    _reply swallows OSError, which is the ordinary hang-up. This is the other
    kind: anything else from the socket layer escapes it and unwinds
    serve_connection, which is exactly the path that used to lose the answer to
    "did this request change what is enforced?".
    """

    def sendall(self, data):
        raise RuntimeError("the socket layer came apart")


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


class TestPeerIsRoot(unittest.TestCase):
    def test_a_connection_without_getsockopt_is_not_root(self):
        # Fails closed: anything that cannot prove it is root is not, and the
        # check must never raise into the connection handler to say so.
        self.assertFalse(server._peer_is_root(_FakeConn([])))


class _Sentinel(Exception):
    """Raised once the listener has given out everything it was going to.

    It no longer *escapes* _serve_once -- the accept guard is deliberately
    broad enough to catch MemoryError, so it catches this too -- so the drive
    stops on the listener's `done` flag instead. The exception is kept only so
    that a listener asked for more than it has does something loud.
    """


class _FailingListener:
    """A listening socket whose accept() always fails."""

    def __init__(self, error, limit):
        self.error = error
        self.limit = limit
        self.accepts = 0
        self.done = False

    def accept(self):
        self.accepts += 1
        if self.accepts > self.limit:
            self.done = True
            raise _Sentinel()
        raise self.error


class _ClosingBadlyConn(_FakeConn):
    """A connection whose close() raises, as EBADF does.

    `with conn:` sat outside every guard in the loop body, so this was one
    syscall away from killing the daemon -- the sixth instance of this
    project's recurring class.
    """

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self):
        raise OSError("EBADF")


class _OneConnectionListener:
    """Hands out one connection, then raises the sentinel."""

    def __init__(self, conn):
        self.conn = conn
        self.accepts = 0
        self.done = False

    def accept(self):
        self.accepts += 1
        if self.accepts > 1:
            self.done = True
            raise _Sentinel()
        return self.conn, None


class _Counting:
    """A NetWatch stand-in that counts enforcements."""

    def __init__(self, paths):
        self.paths = paths
        self.enforce_failures = 0
        self.calls = 0

    def enforce(self):
        self.calls += 1
        return {"changed": False, "verdict": None, "targets": []}


class TestAcceptLoopKeepsEnforcing(unittest.TestCase):
    """Drives _serve_once rather than serve().

    serve() is an unbounded loop that binds a real socket, and the loop body is
    the whole of what needs testing here, so it is extracted and driven
    directly -- no sockets, no sentinel needed inside the daemon itself.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = paths_in(self.dir)

    def _drive(self, listener, nw, iterations):
        last = time.monotonic()
        for _ in range(iterations):
            # interval=0: every non-connection turn is due for enforcement,
            # so "did it reach the periodic branch" needs no waiting.
            last = server._serve_once(nw, listener, last, 0)
            if listener.done:
                break

    def test_a_persistent_accept_error_still_reaches_the_periodic_enforce(self):
        # EMFILE need not clear. Restarting the loop on the error path would
        # have jumped straight back to accept() and never enforced again -- a
        # live daemon that has stopped repairing, which is the failure this
        # whole wave is about.
        nw = _Counting(self.paths)
        started = time.monotonic()
        self._drive(_FailingListener(OSError("EMFILE"), limit=3), nw, 5)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(nw.calls, 1)
        # And it paused instead of spinning at full speed through the failures.
        self.assertGreaterEqual(elapsed, 0.25)
        self.assertLess(elapsed, 2.0)

    def test_the_timeout_path_still_reaches_the_periodic_enforce(self):
        nw = _Counting(self.paths)
        self._drive(_FailingListener(TimeoutError("timed out"), limit=3), nw, 5)
        self.assertGreaterEqual(nw.calls, 1)

    def test_a_connection_whose_close_raises_does_not_stop_the_loop(self):
        nw = _Counting(self.paths)
        conn = _ClosingBadlyConn([b'{"cmd": "status"}\n'])
        self._drive(_OneConnectionListener(conn), nw, 3)
        # The post-connection enforcement still ran, and the next turn was
        # reached at all -- the sentinel is what ends the drive.
        self.assertGreaterEqual(nw.calls, 1)


class TestServeConnection(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "hosts"), "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.proc = os.path.join(self.dir, "proc")
        os.makedirs(self.proc)
        self.nw = NetWatch(
            paths_in(self.dir), flusher=lambda: None, proc_dir=self.proc,
            notifier=quiet_notifier)

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

    def test_add_and_enforce_report_that_state_may_have_changed(self):
        # The accept loop uses this to decide whether the connection has earned
        # an enforcement; see TestServeOnceEnforcementBudget for why.
        for request in (b'{"cmd": "add", "domain": "a.com"}\n',
                        b'{"cmd": "enforce"}\n'):
            self.assertTrue(
                server.serve_connection(self.nw, _FakeConn([request])), request)

    def test_an_add_whose_reply_fails_still_earns_its_enforcement(self):
        # The flag used to be derived after the reply was written, so a client
        # that vanished between its add and the answer took the flag down with
        # it: the accept loop skipped the immediate enforcement and the newly
        # blocked domain stayed reachable until the next periodic cycle. The
        # add itself had already succeeded. Over-enforcing costs one repair
        # cycle; not enforcing after a real add is the wall silently down.
        conn = _ExplodingReplyConn([b'{"cmd": "add", "domain": "a.com"}\n'])
        self.assertTrue(server.serve_connection(self.nw, conn))
        self.assertEqual(self.nw.domains(), ["a.com"])

    def test_reads_and_failures_report_no_change(self):
        # Including the two ways a connection produces no request at all: a
        # bare connect loop is the cheapest thing an unprivileged user can do.
        for chunks in ([b'{"cmd": "list"}\n'],
                       [b'{"cmd": "status"}\n'],
                       [b"{ not json\n"],
                       []):
            self.assertFalse(
                server.serve_connection(self.nw, _FakeConn(chunks)), chunks)


class TestServeOnceEnforcementBudget(unittest.TestCase):
    """Enforcing after every connection let a connect loop peg a core.

    The socket is 0666 by design, so `while true; do socat - UNIX-CONNECT:...;
    done` is something any local user can run, and it drove full-speed
    enforcement forever.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "hosts"), "w") as f:
            f.write("127.0.0.1 localhost\n")
        proc = os.path.join(self.dir, "proc")
        os.makedirs(proc)
        self.nw = NetWatch(
            paths_in(self.dir), flusher=lambda: None, proc_dir=proc,
            notifier=quiet_notifier)
        self.calls = []
        self.original = server._enforce_quietly
        server._enforce_quietly = lambda nw: self.calls.append(1)
        self.addCleanup(self._restore)

    def _restore(self):
        server._enforce_quietly = self.original

    def _turn(self, request):
        # A long interval, just reset: the periodic branch is not due, so any
        # enforcement on this turn came from the connection itself.
        last = time.monotonic()
        listener = _OneConnectionListener(_CtxConn([request]))
        return last, server._serve_once(self.nw, listener, last, 3600)

    def test_a_read_only_connection_does_not_trigger_enforcement(self):
        last, returned = self._turn(b'{"cmd": "status"}\n')
        self.assertEqual(self.calls, [])
        # And the periodic clock was not reset by it, so a flood of reads
        # cannot postpone the next scheduled enforcement either.
        self.assertEqual(returned, last)

    def test_a_mutating_connection_triggers_enforcement(self):
        _, returned = self._turn(b'{"cmd": "add", "domain": "a.com"}\n')
        self.assertEqual(len(self.calls), 1)
        self.assertIsNotNone(returned)


class TestAck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = paths_in(self.dir)
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        for path in (self.paths.unit_file, self.paths.unit_source):
            with open(path, "w") as f:
                f.write("[Service]\n")
        self.nw = NetWatch(self.paths, flusher=lambda: None,
                           notifier=lambda m, a=(): True)

    def test_ack_records_an_entry(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        reply = handle(self.nw, {"cmd": "ack", "token": "aaa"})
        self.assertTrue(reply["ok"])
        self.assertIn("ack", [e["kind"] for e in ledger.read(self.paths.ledger)])

    def test_ack_clears_the_unacknowledged_count(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        self.assertEqual(handle(self.nw, {"cmd": "status"})["unacknowledged"], 1)
        handle(self.nw, {"cmd": "ack", "token": "aaa"})
        self.assertEqual(handle(self.nw, {"cmd": "status"})["unacknowledged"], 0)

    def test_ack_needs_no_root(self):
        # The plugin runs as the operator, not as root.
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        self.assertTrue(
            handle(self.nw, {"cmd": "ack", "token": "aaa"}, peer_is_root=False)["ok"])

    def test_ack_without_a_token_is_refused(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        self.assertFalse(handle(self.nw, {"cmd": "ack"})["ok"])

    def test_ack_with_the_wrong_token_is_refused(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        self.assertFalse(handle(self.nw, {"cmd": "ack", "token": "zzz"})["ok"])

    def test_ack_with_the_right_token_is_accepted(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        self.assertTrue(handle(self.nw, {"cmd": "ack", "token": "aaa"})["ok"])

    def test_a_token_cannot_be_replayed(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        handle(self.nw, {"cmd": "ack", "token": "aaa"})
        self.assertFalse(handle(self.nw, {"cmd": "ack", "token": "aaa"})["ok"])

    def test_spamming_ack_cannot_hold_the_ladder_down(self):
        # The bypass this task exists to close: a shell loop with no token.
        for _ in range(20):
            handle(self.nw, {"cmd": "ack"})
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="bbb")
        entries = ledger.read(self.paths.ledger)
        self.assertEqual(ladder.rung(entries), ladder.LOCK)

    def test_status_reports_weakening(self):
        self.nw.add("a.com")
        self.nw.enforce()
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.assertTrue(handle(self.nw, {"cmd": "status"})["weakened"])

    def test_status_reports_no_weakening_when_intact(self):
        self.nw.add("a.com")
        self.nw.enforce()
        self.assertEqual(handle(self.nw, {"cmd": "status"})["weakened"], [])

    def test_ack_is_not_a_mutating_command(self):
        # It changes the ladder, not the wall; it must not force an enforcement.
        conn = _FakeConn([b'{"cmd": "ack"}\n'])
        self.assertFalse(server.serve_connection(self.nw, conn))


if __name__ == "__main__":
    unittest.main()
