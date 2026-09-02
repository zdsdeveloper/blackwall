"""The blocklist.

Normalisation matters more than it looks. The operator will paste whole URLs,
mixed case, and trailing dots, and a domain that does not normalise to the same
string every time is a hole in the wall. This is the only place in NetWatch that
is allowed to transform a domain.
"""

import re

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class InvalidDomain(ValueError):
    pass


def normalize(raw):
    d = raw.strip().lower()
    if "://" in d:
        d = d.split("://", 1)[1]
    d = d.split("/", 1)[0]
    d = d.split("?", 1)[0]
    if "@" in d:
        d = d.split("@", 1)[1]
    d = d.split(":", 1)[0]
    d = d.rstrip(".")
    # Stored apex-only; hosts rendering puts the www back. Keeping both forms in
    # the list would mean two entries to remove and one of them forgotten.
    if d.startswith("www."):
        d = d[4:]
    if not d or len(d) > 253:
        raise InvalidDomain(raw)
    labels = d.split(".")
    if len(labels) < 2:
        raise InvalidDomain(raw)
    for label in labels:
        if not _LABEL.match(label):
            raise InvalidDomain(raw)
    return d


def parse(text):
    out = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        out.add(normalize(line))
    return sorted(out)
