"""The only way in.

The blocklist is root-owned and append-only, so the operator cannot edit it
directly -- every change comes through here. That is the whole point: it lets the
daemon enforce "adding is instant, removing is slow" as a property of the system
rather than a convention someone has to keep.
"""

import hashlib
import hmac
import json
import os
import socket
import struct
import time

from . import ladder, ledger
from .blocklist import InvalidDomain
from .daemon import DEFAULT_INTERVAL_SECONDS, BlocklistFull


def handle(nw, request, peer_is_root=False):
    cmd = request.get("cmd")
    if cmd == "add":
        raw = request.get("domain")
        if not isinstance(raw, str) or not raw.strip():
            return {"ok": False, "error": "add requires a domain"}
        try:
            return {"ok": True, "domain": nw.add(raw)}
        except InvalidDomain as exc:
            return {"ok": False, "error": "not a domain: %s" % exc}
        except BlocklistFull:
            # A refusal, not a crash: the cap exists to stop a local user
            # filling the list, and the honest answer to the operator who hits
            # it is that the list is full.
            return {"ok": False, "error": "blocklist is full"}
    if cmd == "list":
        return {"ok": True, "domains": nw.domains()}
    if cmd == "status":
        reply = {"ok": True}
        reply.update(nw.status())
        return reply
    if cmd == "log":
        # Read-only and unprivileged, like status and list. The ledger is
        # world-readable already; this is just a structured view of it for a
        # panel to draw, not a new way to learn anything -- which is exactly
        # why token_hash is stripped below rather than passed through. It is
        # a hash, not a token, but a display surface has no reason to carry
        # even that.
        limit = request.get("limit", 40)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            limit = 40
        entries = ledger.read(nw.paths.ledger)[-limit:] if limit else []
        return {"ok": True,
                "entries": [{k: v for k, v in entry.items() if k != "token_hash"}
                           for entry in entries]}
    if cmd == "enforce":
        close = bool(request.get("close_window"))
        if close and not peer_is_root:
            return {"ok": False,
                    "error": "closing a transaction window requires root"}
        result = nw.enforce()
        if close:
            nw.close_window()
        return {"ok": True, "result": result}
    if cmd == "ack":
        # Unprivileged by design -- the plugin runs as the operator -- but not
        # unauthenticated. The token was handed to the plugin over the session
        # IPC, which a process spamming this socket cannot read. Only its hash
        # lives in the ledger, which is world-readable, so reading the ledger
        # yields nothing that can be presented back here.
        #
        # Answered against the delivery rather than the breach: a breach that
        # never reached a screen has no token behind it, and there is nothing
        # for anyone to acknowledge until it does.
        token = request.get("token")
        expected = ladder.pending_delivery(ledger.read(nw.paths.ledger))
        if not expected or not isinstance(token, str) or not token:
            return {"ok": False, "error": "no acknowledgement is pending"}
        offered = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(offered, expected):
            return {"ok": False, "error": "no acknowledgement is pending"}
        ledger.record(nw.paths.ledger, "ack", token_hash=expected)
        return {"ok": True}
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


def _peer_is_root(conn):
    """Only root may close a transaction window.

    The socket is 0666 so that anyone may ADD a domain -- that asymmetry is the
    whole design. Closing the pacman window is a different privilege: a local
    user able to drop the marker at will could make every file a genuine system
    upgrade replaces read as tampering.
    """
    try:
        raw = conn.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", raw)
        return uid == 0
    except (OSError, AttributeError, struct.error):
        return False


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


# Commands whose handling could have changed what is enforced. Everything else
# is a read, and a read gives the caller no reason to re-run enforcement.
MUTATING_COMMANDS = ("add", "enforce")

# The floor between two enforcement cycles triggered by a request.
#
# The socket is 0666 by design -- anyone local may add a domain -- and `enforce`
# is on that list. Without a floor, a process asking to enforce in a loop drives
# a full cycle every time round: reading /etc/hosts, checking the unit and the
# policy, and rewriting 5312 sink lines for 1328 domains. That is a local
# unprivileged process pegging the daemon indefinitely, and a buggy script does
# it as readily as a hostile one.
#
# A second is short enough that adding a domain still takes effect at once in
# any normal use, and long enough that a spin loop costs one cycle a second
# instead of thousands. Anything a burst outruns is picked up by the periodic
# cycle regardless: the blocklist is written before enforcement is asked for,
# so the change is never lost, only applied on the next pass.
MIN_MUTATION_INTERVAL_SECONDS = 1.0


def serve_connection(nw, conn):
    """Handle one client. Never raises -- nothing a client does may reach the
    accept loop.

    Returns True when the request could have changed enforced state, so the
    accept loop knows whether this connection has earned an enforcement. A
    dropped or malformed connection has not: the socket is 0666, so a bare
    connect loop would otherwise run enforcement at full speed forever.
    """
    mutated = False
    try:
        raw = _read_request(conn)
        if raw is None:
            return False
        # The read left whatever was still on its deadline as the socket
        # timeout. A client that dribbled its request for nearly the whole five
        # seconds would otherwise get a millisecond to accept the reply, and a
        # long `list` would truncate. The reply gets its own full budget.
        conn.settimeout(REQUEST_DEADLINE_SECONDS)
        try:
            request = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            _reply(conn, {"ok": False, "error": "malformed request"})
            return False
        # Decided from the request, and decided here -- before handling and
        # before the reply, the two steps that can throw. Derived after them, a
        # client that hung up mid-reply took the answer down with it: the outer
        # guard returned False, the accept loop skipped the enforcement, and a
        # domain the operator had just added stayed unblocked until the next
        # periodic cycle.
        #
        # Asked of the request, not the reply: a refused add still went through
        # handle(), and the cost of an unnecessary enforcement is one repair
        # cycle, while the cost of a missed one is the wall silently down.
        # The command itself, not just whether it mutates: `add` changes state
        # and must apply at once, while `enforce` only asks for a re-check and
        # can be asked for in a loop by anyone local. They are rate-limited
        # differently in _serve_once.
        asked = request.get("cmd") if isinstance(request, dict) else None
        mutated = asked if asked in MUTATING_COMMANDS else None
        try:
            reply = handle(nw, request, _peer_is_root(conn))
        except Exception:
            reply = {"ok": False, "error": "internal error"}
        _reply(conn, reply)
    except Exception:
        pass
    return mutated


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
    except Exception:
        # ECONNABORTED, EMFILE and the rest -- and MemoryError, which is not an
        # OSError and killed this loop outright. One lost connection is not a
        # reason to stop enforcing, so this must fall through to the periodic
        # check below rather than restarting the loop -- and it pauses, because
        # an error that does not clear would otherwise spin here at full speed
        # and starve the very repair it is skipping.
        time.sleep(0.1)
    if conn is not None:
        mutated = None
        try:
            with conn:
                mutated = serve_connection(nw, conn)
        except OSError:
            # socket.close() raises -- EBADF is reachable -- and it sits
            # outside serve_connection's own guard. Hanging up on a client is
            # not a reason to stop enforcing.
            pass
        # Enforcing after every connection let a connect/disconnect loop on a
        # 0666 socket peg a core indefinitely. Enforce when the request could
        # have changed something -- but no more often than the floor, or
        # `enforce` in a loop does the same thing through the front door -- or
        # when the interval was due anyway.
        since = time.monotonic() - last
        # `add` changed the blocklist, so the managed files are wrong until a
        # cycle runs: no floor, exactly as before. `enforce` asks for a
        # re-check and nothing is pending on it, so it waits out the floor --
        # which is what stops a local process asking for one in a loop from
        # driving the daemon at full speed through the front door.
        if (mutated == "add"
                or (mutated == "enforce" and since >= MIN_MUTATION_INTERVAL_SECONDS)
                or since >= interval):
            _enforce_quietly(nw)
            return time.monotonic()
        return last
    if time.monotonic() - last >= interval:
        _enforce_quietly(nw)
        return time.monotonic()
    return last


def serve(nw, interval=DEFAULT_INTERVAL_SECONDS):
    # Before the socket, deliberately. Enforcement does not depend on the
    # control channel and must not be hostage to it: if makedirs or bind fails,
    # the managed files have already been repaired once.
    _enforce_quietly(nw)
    path = nw.paths.socket
    os.makedirs(os.path.dirname(path) or "/", mode=0o755, exist_ok=True)
    # Unconditional and guarded rather than exists()-then-unlink: between the
    # two calls the path can vanish, and the unlink that then raises would kill
    # startup -- a daemon that does not come up is a wall that is not up.
    try:
        os.unlink(path)
    except OSError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # umask around bind rather than chmod after it. Anyone on this machine may
    # add a domain; nobody, including this user, may take one away -- and that
    # 0666 has to be true from the instant the socket exists, with no window at
    # the umask-derived mode and no path-based chmod to follow a symlink.
    # 0o111 clears only the execute bits, which a socket has no use for,
    # leaving mode 0666.
    previous = os.umask(0o111)
    try:
        server.bind(path)
    finally:
        os.umask(previous)
    server.listen(8)
    server.settimeout(interval)
    last = time.monotonic()
    while True:
        last = _serve_once(nw, server, last, interval)
