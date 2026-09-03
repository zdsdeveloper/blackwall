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
