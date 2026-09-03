"""Reaching the user's shell from a root daemon.

This looked like it needed a privilege bridge -- a root-written file the plugin
watches, or a relay service in the session. It does not: root bypasses the
permission bits on the session's runtime directory, so the daemon can speak the
IPC the plugin already exposes. Verified on this machine before it was designed
around.

The target is found by pid rather than by display, so a different uid, a
restarted shell or a changed display does not break it.
"""

import os
import subprocess

PROC_DIR = "/proc"

SHELL_MARKER = "/usr/share/omarchy/shell"
SHELL_COMMS = ("quickshell", "qs")

IPC_TARGET = "blackwall"

TIMEOUT_SECONDS = 5


def _read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def find_shell_pid(proc_dir=PROC_DIR):
    """The pid of the Quickshell process running the Omarchy shell, if any."""
    try:
        entries = os.listdir(proc_dir)
    except (OSError, ValueError):
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        comm = _read_bytes(os.path.join(proc_dir, entry, "comm"))
        if comm is None or comm.decode("utf-8", "replace").strip() not in SHELL_COMMS:
            continue
        cmdline = _read_bytes(os.path.join(proc_dir, entry, "cmdline")) or b""
        if SHELL_MARKER.encode("utf-8") in cmdline:
            return int(entry)
    return None


def runtime_dir_of(pid, proc_dir=PROC_DIR):
    """XDG_RUNTIME_DIR as that process sees it."""
    raw = _read_bytes(os.path.join(proc_dir, str(pid), "environ"))
    if raw is None:
        return None
    for item in raw.split(b"\x00"):
        if item.startswith(b"XDG_RUNTIME_DIR="):
            return item.split(b"=", 1)[1].decode("utf-8", "replace")
    return None


def notify(method, args=(), proc_dir=PROC_DIR, runner=subprocess.run):
    """Call a method on the plugin's IPC. True if it landed.

    False is an ordinary outcome, not an error: when nobody is logged in there
    is no screen to lock, and the breach simply stays unacknowledged until the
    plugin asks about it at next start.
    """
    pid = find_shell_pid(proc_dir)
    if pid is None:
        return False
    runtime = runtime_dir_of(pid, proc_dir)
    if runtime is None:
        return False
    argv = ["qs", "ipc", "--pid", str(pid), "call", IPC_TARGET, method]
    argv.extend(str(a) for a in args)
    env = dict(os.environ)
    env["XDG_RUNTIME_DIR"] = runtime
    try:
        result = runner(
            argv,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except Exception:
        return False
    return getattr(result, "returncode", 1) == 0
