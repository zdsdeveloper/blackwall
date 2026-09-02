"""The only way in.

The blocklist is root-owned and append-only, so the operator cannot edit it
directly -- every change comes through here. That is the whole point: it lets the
daemon enforce "adding is instant, removing is slow" as a property of the system
rather than a convention someone has to keep.
"""

import json
import os
import socket
import time

from . import ledger
from .blocklist import InvalidDomain


def handle(nw, request):
    cmd = request.get("cmd")
    if cmd == "add":
        raw = request.get("domain")
        if not isinstance(raw, str) or not raw.strip():
            return {"ok": False, "error": "add requires a domain"}
        try:
            return {"ok": True, "domain": nw.add(raw)}
        except InvalidDomain as exc:
            return {"ok": False, "error": "not a domain: %s" % exc}
    if cmd == "list":
        return {"ok": True, "domains": nw.domains()}
    if cmd == "status":
        reply = {"ok": True}
        reply.update(nw.status())
        return reply
    if cmd == "enforce":
        result = nw.enforce()
        if request.get("close_window"):
            nw.close_window()
        return {"ok": True, "result": result}
    return {"ok": False, "error": "unknown command: %r" % (cmd,)}


def _enforce_quietly(nw):
    """The backstop.

    Every module guards its own reads, and four times now a different exception
    type has slipped past a guard written for the one before it. Those guards
    are the first line and they keep earning their place; this is the line that
    does not need to know which exception comes next. A cycle that fails is
    retried on the following one, because a daemon that will not stay up is a
    wall that is not up.

    Exception, not BaseException: a shutdown signal must still stop the daemon.

    The counter is the other half of the backstop: swallowing the exception is
    what keeps the daemon alive, and nothing but this count would tell the
    operator that it has been alive and not enforcing.
    """
    try:
        result = nw.enforce()
    except Exception as exc:
        nw.enforce_failures += 1
        # The transition into failure, then every hundredth. This runs after
        # every connection on a 0666 socket, so a connect/disconnect loop would
        # otherwise drive unbounded appends into root-owned /var precisely while
        # enforcement is broken.
        if nw.enforce_failures == 1 or nw.enforce_failures % 100 == 0:
            try:
                ledger.record(
                    nw.paths.ledger,
                    "enforce-failed",
                    error=repr(exc)[:200],
                    failures=nw.enforce_failures,
                )
            except Exception:
                pass
        return {"changed": False, "verdict": None, "targets": []}
    nw.enforce_failures = 0
    return result


MAX_REQUEST_BYTES = 65536


def _reply(conn, payload):
    """Write one reply. A peer that has gone must not take the daemon with it.

    The socket is world-writable by design -- anyone may add a domain -- so a
    client that connects and vanishes is an ordinary event, not an attack. It
    has to cost nothing.
    """
    try:
        conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    except OSError:
        pass


REQUEST_DEADLINE_SECONDS = 5


def _read_request(conn):
    """Read one newline-terminated request within a single overall deadline.

    A per-read timeout is not enough: a peer dripping one byte at a time under
    the limit would hold this single-threaded loop for as long as it liked, and
    nothing is enforced while a connection is open.
    """
    deadline = time.monotonic() + REQUEST_DEADLINE_SECONDS
    chunks = []
    total = 0
    while total < MAX_REQUEST_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            conn.settimeout(remaining)
            chunk = conn.recv(4096)
        except OSError:
            return None
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if b"\n" in chunk:
            break
    if not chunks:
        return None
    return b"".join(chunks)


def serve_connection(nw, conn):
    """Handle one client. Never raises -- nothing a client does may reach the
    accept loop."""
    try:
        raw = _read_request(conn)
        if raw is None:
            return
        try:
            request = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            _reply(conn, {"ok": False, "error": "malformed request"})
            return
        try:
            reply = handle(nw, request)
        except Exception:
            reply = {"ok": False, "error": "internal error"}
        _reply(conn, reply)
    except Exception:
        pass


def _serve_once(nw, server, last, interval):
    """One turn of the accept loop. Returns the time enforcement last ran.

    Extracted so the loop body can be driven without a real socket, and so
    there is exactly one place where the periodic check could be skipped --
    and no path that skips it.
    """
    conn = None
    try:
        conn, _ = server.accept()
    except TimeoutError:
        pass
    except OSError:
        # ECONNABORTED, EMFILE and the rest. One lost connection is not a
        # reason to stop enforcing, so this must fall through to the periodic
        # check below rather than restarting the loop -- and it pauses, because
        # an error that does not clear would otherwise spin here at full speed
        # and starve the very repair it is skipping.
        time.sleep(0.1)
    if conn is not None:
        with conn:
            serve_connection(nw, conn)
        _enforce_quietly(nw)
        return time.monotonic()
    if time.monotonic() - last >= interval:
        _enforce_quietly(nw)
        return time.monotonic()
    return last


def serve(nw, interval=30):
    # Before the socket, deliberately. Enforcement does not depend on the
    # control channel and must not be hostage to it: if makedirs, bind or chmod
    # fails, the managed files have already been repaired once.
    _enforce_quietly(nw)
    path = nw.paths.socket
    os.makedirs(os.path.dirname(path) or "/", mode=0o755, exist_ok=True)
    if os.path.exists(path):
        os.unlink(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    # Anyone on this machine may add a domain. Nobody, including this user, may
    # take one away.
    os.chmod(path, 0o666)
    server.listen(8)
    server.settimeout(interval)
    last = time.monotonic()
    while True:
        last = _serve_once(nw, server, last, interval)
