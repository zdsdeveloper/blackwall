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
SINK = "0.0.0.0"


def render(domains):
    lines = [BEGIN]
    for d in domains:
        lines.append("%s %s" % (SINK, d))
        lines.append("%s www.%s" % (SINK, d))
    lines.append(END)
    return "\n".join(lines)


def splice(current, block):
    if BEGIN in current and END in current:
        head = current.split(BEGIN, 1)[0]
        tail = current.split(END, 1)[1]
        return head.rstrip("\n") + "\n\n" + block + "\n" + tail.lstrip("\n")
    return current.rstrip("\n") + "\n\n" + block + "\n"


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
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return True
