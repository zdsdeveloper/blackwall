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


def expected_lines(domains):
    """Every line the managed region must contain, in render order.

    The single definition of what "blocked" looks like on disk. The renderer
    writes these and the integrity check looks for them; if the two ever
    disagreed, the wall would report itself intact while missing entries.
    """
    lines = []
    for d in domains:
        for host in (d, "www." + d):
            lines.append("%s %s" % (SINK4, host))
            lines.append("%s %s" % (SINK6, host))
    return lines


def render(domains):
    return "\n".join([BEGIN] + expected_lines(domains) + [END])


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


def region_lines(current):
    """The lines inside the markers, or empty if there is no complete region."""
    lines = current.splitlines()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == BEGIN:
            start = i
        elif stripped == END and start is not None:
            return lines[start + 1:i]
    return []


def splice(current, block):
    """Replace the managed region in place, leaving everything else where it is.

    In place matters: rebuilding the file with the region at the end moved any
    line written after it, so an ordinary edit to /etc/hosts produced a diff and
    read as tampering. The replacement is done line-for-line rather than by
    rejoining text with a forced blank-line separator, so whatever spacing
    already surrounded the region -- none, one blank line, whatever the
    operator left -- comes out unchanged when the region's content hasn't.
    """
    lines = current.splitlines()
    doomed = _doomed_lines(lines)
    if not doomed:
        if lines:
            return "\n".join(lines) + "\n\n" + block + "\n"
        return block + "\n"
    at = min(doomed)
    insert = sum(1 for i in range(at) if i not in doomed)
    kept = [line for i, line in enumerate(lines) if i not in doomed]
    new_lines = kept[:insert] + block.split("\n") + kept[insert:]
    return "\n".join(new_lines) + "\n"


def apply(path, domains):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            current = f.read()
        mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        # A missing hosts file is an empty one. Refusing to act because the file
        # we are meant to own is not there would mean never enforcing again.
        current = ""
        mode = 0o644
    desired = splice(current, render(domains))
    if desired == current:
        return False
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".netwatch-", suffix=".tmp")
    try:
        # utf-8 explicitly: `current` was read with errors="replace", so it can
        # carry U+FFFD, which a non-utf-8 locale encoding would refuse to write.
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(desired)
            # On the descriptor we already hold, not on the path: a path-based
            # chmod is a second lookup that a symlink planted in between could
            # redirect. Before the fsync, so the mode is durable with the data.
            os.fchmod(f.fileno(), mode)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, path)
        # O_DIRECTORY: without it this would silently fsync a regular file if
        # `directory` ever turned out not to be one, and the rename would not
        # actually be on disk.
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        # Guarded in its own right: an unlink that raises here would replace the
        # real failure with a stray OSError about a temp file nobody asked
        # about, and the reason enforcement broke would be lost.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True
