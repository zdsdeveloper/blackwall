"""netwatchctl, exercised in-process.

The script lives outside the package (bin/, no __init__.py) and normally talks
to the daemon over a real socket -- exactly what this suite is not allowed to
touch. Loaded as a module with its `call` function stubbed out, its argument
parsing and its formatting of a reply are testable without a daemon, a socket
or a subprocess.
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock


def _load():
    # The script has no .py suffix, so spec_from_file_location cannot infer a
    # loader for it by extension alone -- the loader has to be named outright.
    path = os.path.join(os.path.dirname(__file__), "..", "bin", "netwatchctl")
    loader = importlib.machinery.SourceFileLoader("netwatchctl_cli", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


CLI = _load()


def run(argv, reply):
    """Drive CLI.main() with `call` stubbed to return (or compute) `reply`,
    and return whatever it printed. `reply` may be a dict, reused for every
    call, or a callable taking the request and returning one."""
    fn = reply if callable(reply) else (lambda request: reply)
    out = io.StringIO()
    with mock.patch.object(CLI, "call", side_effect=fn), \
         mock.patch.object(sys, "argv", ["netwatchctl"] + argv), \
         redirect_stdout(out):
        CLI.main()
    return out.getvalue()


STATUS_REPLY = {
    "ok": True,
    "domains": 2,
    "domains_list": ["a.com", "b.com"],
    "blocked_live": ["a.com"],
    "breaches": 1,
    "enforce_failures": 0,
    "unacknowledged": 0,
    "weakened": [],
    "doh_locked": True,
    "unit_intact": True,
    "ledger_sealed": None,
    "interval_seconds": 30,
}


class TestStatusJSON(unittest.TestCase):
    def test_json_emits_one_parseable_object_with_every_field(self):
        text = run(["status", "--json"], STATUS_REPLY)
        lines = [line for line in text.split("\n") if line != ""]
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        for key in STATUS_REPLY:
            self.assertIn(key, parsed)
        self.assertEqual(parsed, STATUS_REPLY)

    def test_json_null_survives_as_json_null_not_python_none_text(self):
        text = run(["status", "--json"], STATUS_REPLY)
        self.assertIn('"ledger_sealed": null', text)

    def test_plain_status_output_is_unchanged_by_the_flags_existence(self):
        text = run(["status"], STATUS_REPLY)
        self.assertEqual(text, (
            "domains  2\n"
            "breaches 1\n"
            "failures 0\n"
            "unacked  0\n"
        ))

    def test_weakened_reasons_still_print_in_plain_mode(self):
        reply = dict(STATUS_REPLY, weakened=["hosts: 1 of 4 sink lines missing"])
        text = run(["status"], reply)
        self.assertIn("WEAK     hosts: 1 of 4 sink lines missing\n", text)


class TestLogCLI(unittest.TestCase):
    def test_prints_the_entries_as_one_json_array(self):
        entries = [{"at": 1.0, "kind": "added", "domain": "a.com"}]
        text = run(["log"], {"ok": True, "entries": entries})
        self.assertEqual(json.loads(text), entries)

    def test_defaults_to_a_limit_of_forty(self):
        requests = []
        run(["log"], lambda request: requests.append(request) or
            {"ok": True, "entries": []})
        self.assertEqual(requests, [{"cmd": "log", "limit": 40}])

    def test_limit_flag_is_passed_through(self):
        requests = []
        run(["log", "--limit", "5"], lambda request: requests.append(request) or
            {"ok": True, "entries": []})
        self.assertEqual(requests, [{"cmd": "log", "limit": 5}])

    def test_a_refusal_exits_with_the_error(self):
        with self.assertRaises(SystemExit) as ctx:
            run(["log"], {"ok": False, "error": "no ledger"})
        self.assertEqual(str(ctx.exception), "no ledger")


if __name__ == "__main__":
    unittest.main()


class TestReadReply(unittest.TestCase):
    """Reading one newline-terminated frame off the socket.

    A single recv() is not a read. A stream socket hands back whatever has
    arrived and the caller gets the rest by asking again, so the old
    `s.recv(65536)` was correct only while every reply happened to fit in one
    buffer and arrive in one piece. It stopped being correct the moment the
    blocklist grew: at 1328 domains the status reply carries domains_list,
    blocked_live and the probe results, comes to roughly 80KB, and arrives in
    two chunks. The client parsed the first fragment, failed, and reported
    that the daemon had sent something unreadable -- while the daemon was
    answering perfectly.

    A socketpair, not the daemon's socket: this exercises the framing without
    touching anything outside the test.
    """

    def frame(self, payload):
        import socket as _socket
        a, b = _socket.socketpair()
        with a, b:
            b.sendall(payload)
            b.shutdown(_socket.SHUT_WR)
            return CLI._read_reply(a)

    def test_a_small_reply_still_works(self):
        self.assertEqual(json.loads(self.frame(b'{"ok": true}\n'))["ok"], True)

    def test_a_reply_larger_than_one_buffer_is_read_whole(self):
        # The regression. Comfortably more than the 65536 the client used to
        # read, and more than one recv will return.
        big = {"ok": True, "domains_list": ["d%05d.example" % i
                                            for i in range(6000)]}
        payload = (json.dumps(big) + "\n").encode("utf-8")
        self.assertGreater(len(payload), 65536)
        got = json.loads(self.frame(payload))
        self.assertEqual(len(got["domains_list"]), 6000)

    def test_it_stops_at_the_frame_rather_than_waiting_for_the_peer(self):
        # The newline ends the reply. Waiting for EOF instead would hang
        # against a daemon that keeps the connection open.
        import socket as _socket
        a, b = _socket.socketpair()
        with a, b:
            b.sendall(b'{"ok": true}\n')
            # b is deliberately left open.
            self.assertEqual(json.loads(CLI._read_reply(a))["ok"], True)

    def test_a_peer_that_hangs_up_early_does_not_hang_the_client(self):
        # Whatever arrived is returned and the JSON parse decides. Blocking
        # for ever on a truncated frame would be worse than a clear failure.
        got = self.frame(b'{"ok": tr')
        self.assertEqual(got, '{"ok": tr')
