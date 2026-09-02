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
        return {"ok": True, "result": nw.enforce()}
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
    """
    try:
        return nw.enforce()
    except Exception as exc:
        try:
            ledger.record(nw.paths.ledger, "enforce-failed", error=repr(exc)[:200])
        except Exception:
            pass
        return {"changed": False, "verdict": None, "targets": []}


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


def _read_request(conn):
    """Read one newline-terminated request, or None if the peer sent nothing.

    Read until the newline rather than trusting a single recv: a request that
    spans two reads is a valid request, and answering it "malformed" would be
    our bug, not the client's.
    """
    chunks = []
    total = 0
    while total < MAX_REQUEST_BYTES:
        try:
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
        conn.settimeout(5)
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


def serve(nw, interval=30):
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
    _enforce_quietly(nw)
    last = time.monotonic()
    while True:
        try:
            conn, _ = server.accept()
        except socket.timeout:
            conn = None
        if conn is not None:
            with conn:
                serve_connection(nw, conn)
            _enforce_quietly(nw)
            last = time.monotonic()
        elif time.monotonic() - last >= interval:
            _enforce_quietly(nw)
            last = time.monotonic()
