import os
import tempfile
import unittest
from blackwall_netwatch import session


def fake_proc(entries):
    """entries: {pid: (comm, environ_bytes)}"""
    d = tempfile.mkdtemp()
    for pid, (comm, environ) in entries.items():
        p = os.path.join(d, str(pid))
        os.makedirs(p)
        with open(os.path.join(p, "comm"), "w") as f:
            f.write(comm + "\n")
        with open(os.path.join(p, "cmdline"), "wb") as f:
            f.write(b"quickshell\x00-p\x00/usr/share/omarchy/shell\x00")
        with open(os.path.join(p, "environ"), "wb") as f:
            f.write(environ)
    return d


ENV = b"HOME=/home/zds\x00XDG_RUNTIME_DIR=/run/user/1000\x00LANG=C\x00"


class TestFindShellPid(unittest.TestCase):
    def test_finds_the_quickshell_process(self):
        proc = fake_proc({1214: ("quickshell", ENV)})
        self.assertEqual(session.find_shell_pid(proc), 1214)

    def test_returns_none_when_no_shell_is_running(self):
        proc = fake_proc({7: ("bash", ENV)})
        self.assertIsNone(session.find_shell_pid(proc))

    def test_missing_proc_is_none_not_a_crash(self):
        self.assertIsNone(session.find_shell_pid("/nonexistent"))


class TestRuntimeDir(unittest.TestCase):
    def test_reads_it_out_of_environ(self):
        proc = fake_proc({1214: ("quickshell", ENV)})
        self.assertEqual(session.runtime_dir_of(1214, proc), "/run/user/1000")

    def test_absent_variable_is_none(self):
        proc = fake_proc({1214: ("quickshell", b"HOME=/home/zds\x00")})
        self.assertIsNone(session.runtime_dir_of(1214, proc))

    def test_unreadable_environ_is_none_not_a_crash(self):
        self.assertIsNone(session.runtime_dir_of(99999, "/nonexistent"))


class TestNotify(unittest.TestCase):
    def test_builds_the_expected_command(self):
        proc = fake_proc({1214: ("quickshell", ENV)})
        seen = {}

        def runner(argv, **kwargs):
            seen["argv"] = argv
            seen["env"] = kwargs.get("env")
            class R:
                returncode = 0
            return R()

        self.assertTrue(session.notify("engage", ["1200"], proc_dir=proc, runner=runner))
        self.assertEqual(seen["argv"][:5],
                         ["qs", "ipc", "--pid", "1214", "call"])
        self.assertEqual(seen["argv"][5:], ["blackwall", "engage", "1200"])
        self.assertEqual(seen["env"]["XDG_RUNTIME_DIR"], "/run/user/1000")

    def test_no_session_is_false_not_a_crash(self):
        # Logged out: there is nothing to lock, and the breach stays
        # unacknowledged so the plugin picks it up at next start.
        proc = fake_proc({7: ("bash", ENV)})
        self.assertFalse(session.notify("engage", ["1200"], proc_dir=proc,
                                        runner=lambda *a, **k: None))

    def test_a_failing_runner_is_false_not_a_crash(self):
        proc = fake_proc({1214: ("quickshell", ENV)})

        def runner(argv, **kwargs):
            raise OSError("qs not found")

        self.assertFalse(session.notify("engage", ["1200"], proc_dir=proc, runner=runner))

    def test_a_nonzero_exit_is_false(self):
        proc = fake_proc({1214: ("quickshell", ENV)})

        def runner(argv, **kwargs):
            class R:
                returncode = 1
            return R()

        self.assertFalse(session.notify("engage", ["1200"], proc_dir=proc, runner=runner))


if __name__ == "__main__":
    unittest.main()
