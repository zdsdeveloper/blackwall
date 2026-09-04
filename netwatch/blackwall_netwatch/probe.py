"""Resolution probes: does the machine actually sink these names?

Everything else in NetWatch checks a file. `integrity.missing_sinks` reads
/etc/hosts and reports which sink lines are absent, which answers "does the
blocklist say this domain is blocked". That is a claim about a file. It is not
the same claim as "when something on this machine asks for that name, it does
not get the real address", and the gap between those two is where a block
actually fails:

  * nsswitch.conf ordering that puts a resolver ahead of `files`
  * a DNS-over-HTTPS resolver in an application, bypassing the stub entirely
  * a systemd-resolved cache still holding the real address
  * a container or namespace with its own /etc/hosts

A probe asks the question the file cannot answer. It resolves the name through
the system resolver -- the same path any program on the machine takes -- and
looks at what comes back.

It resolves. It does not connect, and it never speaks HTTP: the point is to
learn where the name points, and opening a socket to a site NetWatch exists to
block would be a strange way to check that it is blocked.

One consequence is worth stating plainly, because it is the argument against
doing this at all: if a name is genuinely no longer sunk, the probe that
discovers this is itself a DNS query for that name, leaving the machine. That
is the one case where the query escapes -- when the block has already failed
and the leak is real. A working wall answers every probe out of /etc/hosts and
nothing goes anywhere.
"""

import concurrent.futures
import ipaddress
import socket


# Every answer was a sink or a loopback address: nothing can reach the site.
SUNK = "sunk"
# At least one real address came back. The block is not working for this name.
LEAKING = "leaking"
# The name did not resolve at all. Also unreachable, but by a different route,
# and worth telling apart from a sink: an NXDOMAIN means something other than
# our hosts entry is answering.
UNRESOLVED = "unresolved"
# The probe could not be run or did not finish. Not a finding either way.
UNKNOWN = "unknown"

# How long the whole sweep may take. Enforcement calls into this, and a wall
# that stops being repaired because a nameserver is hanging would be a poor
# trade for a readout.
DEADLINE_SECONDS = 4.0

WORKERS = 8


def _is_sink(address):
    """True if this address cannot reach anything.

    Both sinks NetWatch writes are unspecified addresses (0.0.0.0 and ::).
    Loopback counts too: a machine whose hosts file sinks to 127.0.0.1 -- a
    common convention, and one an operator may have had in place before
    NetWatch -- is just as blocked, and calling that a leak would be a false
    alarm about a working block.
    """
    try:
        addr = ipaddress.ip_address(address)
    except ValueError:
        # Something that is not an address at all cannot be shown to be a
        # sink, and guessing in the permissive direction here would hide a
        # leak. Treated as real.
        return False
    return addr.is_unspecified or addr.is_loopback


def classify(addresses):
    """Turn a list of address strings into one of the four states.

    Never raises: a probe is a readout, and a readout that can take the daemon
    down is worse than no readout.
    """
    try:
        found = [a for a in addresses if a]
    except TypeError:
        return UNKNOWN
    if not found:
        return UNRESOLVED
    # One real address among ten sinks is still a route to the site.
    return SUNK if all(_is_sink(a) for a in found) else LEAKING


def probe(domain, resolver=None):
    """Resolve one name and classify what came back.

    `resolver` takes the shape of socket.getaddrinfo so tests can hand in
    answers without touching the network.
    """
    if resolver is None:
        resolver = socket.getaddrinfo
    try:
        infos = resolver(domain, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # The name does not resolve. That is an answer, not a failure.
        return UNRESOLVED
    except (OSError, UnicodeError, ValueError):
        # Resolver unavailable, name too long for the stub, anything else the
        # C library objects to. Not a finding: we simply do not know.
        return UNKNOWN

    addresses = []
    try:
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                addresses.append(sockaddr[0])
    except (TypeError, IndexError):
        return UNKNOWN
    return classify(addresses)


def probe_all(domains, resolver=None, workers=WORKERS,
              deadline=DEADLINE_SECONDS, pool=None):
    """Probe every name, bounded in wall-clock time.

    Returns {domain: state} covering every domain asked for. Anything that has
    not answered by the deadline is UNKNOWN rather than missing, so a caller
    can always index the result and a slow nameserver reads as "not known"
    instead of silently shrinking the report.

    `pool` lets a long-running caller supply one executor and keep it. That
    matters more than it looks. The deadline bounds how long this blocks, but
    it does not stop the lookups underneath it: shutdown(wait=False) does not
    interrupt a thread already inside getaddrinfo, and cancel_futures only
    drops work that has not started. Measured with a resolver that never
    answers, a fresh pool per sweep left eight threads behind every time --
    forty-eight after six sweeps, and they only went when the resolver
    unblocked. Sweeps are five minutes apart and a stalled lookup normally
    gives up in well under that, so it takes a resolver wedged for longer than
    the interval to accumulate; but nothing bounded it, and "nothing bounds
    it" is not a property this daemon should have anywhere.

    With one pool the count is capped at `workers` for the life of the
    process. Wedged lookups occupy slots rather than spawning more, later
    sweeps queue behind them and time out into UNKNOWN, and an all-UNKNOWN
    sweep is what NetWatch.sweep counts as a failure -- so the resource stays
    bounded and the symptom stays visible.
    """
    names = [d for d in domains if d]
    results = {d: UNKNOWN for d in names}
    if not names:
        return results

    own = pool is None
    if own:
        count = max(1, min(int(workers), len(names)))
        try:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=count)
        except (OSError, ValueError):
            # Out of threads. Everything stays UNKNOWN, which is true.
            return results

    pending = {}
    try:
        try:
            pending = {pool.submit(probe, d, resolver): d for d in names}
        except RuntimeError:
            # A shut-down or exhausted pool. Everything stays UNKNOWN.
            return results
        try:
            for future in concurrent.futures.as_completed(pending,
                                                          timeout=deadline):
                domain = pending[future]
                try:
                    results[domain] = future.result()
                except Exception:
                    results[domain] = UNKNOWN
        except concurrent.futures.TimeoutError:
            # Whatever did land is already in `results`; the rest stay UNKNOWN.
            pass
    finally:
        # Drop whatever has not started yet either way: past the deadline
        # nobody is going to read the answer, and on a shared pool it would
        # otherwise sit in the queue ahead of the next sweep's work.
        for future in pending:
            future.cancel()
        if own:
            # Never block the enforcement loop waiting for a hung lookup.
            pool.shutdown(wait=False, cancel_futures=True)

    return results


def summarise(results):
    """Counts by state, for a caller that wants the shape rather than the list."""
    out = {SUNK: 0, LEAKING: 0, UNRESOLVED: 0, UNKNOWN: 0}
    if not isinstance(results, dict):
        return out
    for state in results.values():
        if state in out:
            out[state] += 1
        else:
            out[UNKNOWN] += 1
    return out


def leaking(results):
    """The names a probe found a real address for, sorted."""
    if not isinstance(results, dict):
        return []
    return sorted(d for d, state in results.items() if state == LEAKING)
