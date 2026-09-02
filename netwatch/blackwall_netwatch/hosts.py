"""The managed region of /etc/hosts.

Everything between the markers belongs to NetWatch and is rewritten wholesale.
Everything outside them is the operator's and is never touched -- /etc/hosts is
a file other things legitimately edit.
"""

import os
import tempfile

BEGIN = "# >>> blackwall-netwatch (managed) >>>"
END = "# <<< blackwall-netwatch (managed) <<<"

# 0.0.0.0 rather than 127.0.0.1: nothing is listening, so the connection fails
# immediately instead of hitting whatever happens to be on the loopback.
SINK4 = "0.0.0.0"
# :: for IPv6, so AAAA resolution doesn't bypass the block.
SINK6 = "::"


def render(domains):
    lines = [BEGIN]
    for d in domains:
        for host in (d, "www." + d):
            lines.append("%s %s" % (SINK4, host))
            lines.append("%s %s" % (SINK6, host))
    lines.append(END)
    return "\n".join(lines)


def _doomed_lines(lines):
    """Indices belonging to complete BEGIN..END regions, plus dangling markers.

    Substring matching was the original approach and it could delete an
    operator's own entries: a stray BEGIN above a real region made everything
    between the two disappear on the following write. A marker is a whole line
    or it is not a marker, and an unmatched one costs only itself.
    """
    doomed = set()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == BEGIN:
            if start is not None:
                doomed.add(start)
            start = i
        elif stripped == END:
            if start is not None:
                doomed.update(range(start, i + 1))
                start = None
            else:
                doomed.add(i)
    if start is not None:
        doomed.add(start)
    return doomed


def strip_region(current):
    lines = current.splitlines()
    doomed = _doomed_lines(lines)
    return "\n".join(line for i, line in enumerate(lines) if i not in doomed)


def splice(current, block):
    base = strip_region(current).rstrip("\n")
    if not base:
        return block + "\n"
    return base + "\n\n" + block + "\n"


def apply(path, domains):
    with open(path) as f:
        current = f.read()
    desired = splice(current, render(domains))
    if desired == current:
        return False
    directory = os.path.dirname(path) or "."
    mode = os.stat(path).st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".netwatch-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(desired)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.rename(tmp, path)
        dir_fd = os.open(directory, os.O_RDONLY | os.O_CLOEXEC)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return True
