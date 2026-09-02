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
                conn.settimeout(5)
                try:
                    data = conn.recv(65536).decode("utf-8")
                    request = json.loads(data)
                except (ValueError, UnicodeDecodeError):
                    reply = {"ok": False, "error": "malformed request"}
                except socket.timeout:
                    reply = None
                else:
                    try:
                        reply = handle(nw, request)
                    except Exception:
                        reply = {"ok": False, "error": "internal error"}
                if reply is not None:
                    conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
            _enforce_quietly(nw)
            last = time.monotonic()
        elif time.monotonic() - last >= interval:
            _enforce_quietly(nw)
            last = time.monotonic()
