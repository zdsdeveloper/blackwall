"""The blocklist.

Normalisation matters more than it looks. The operator will paste whole URLs,
mixed case, and trailing dots, and a domain that does not normalise to the same
string every time is a hole in the wall. This is the only place in NetWatch that
is allowed to transform a domain.
"""

import hashlib
import re

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class InvalidDomain(ValueError):
    pass


# The one exception.
#
# There is no removal. Nothing in NetWatch takes a domain off the wall, and
# there is no command, flag or file that could be made to. This is not that: it
# is a single decision, made deliberately by the operator on 2026-09-21 about a
# single domain that turned out to be a storefront for ordinary games as well
# as the thing it was listed for, and fixed here in the program rather than
# offered as a way of making more.
#
# It is the only one there will ever be. The test suite holds this set to at
# most one entry: it may go back to empty, and it may never grow.
#
# Held as a digest rather than a name because this repository is public and the
# list is not. It matches the apex exactly and nothing beneath it -- every
# subdomain on the list stays exactly where it is.
RELEASED = frozenset({
    "f21ea0f474a85c35c4911149e2dc1687728d745a924596fafe02467ac9563471",
})


class Released(InvalidDomain):
    """Refused by add(): the one domain the wall has let go."""


def is_released(domain):
    return hashlib.sha256(domain.encode("utf-8")).hexdigest() in RELEASED


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
    # while, not if: "www.www.example.com" would otherwise normalise to
    # "www.example.com" and leave the apex unblocked.
    while d.startswith("www."):
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


def parse_lines(text):
    domains = set()
    rejected = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        try:
            domain = normalize(stripped)
        except InvalidDomain:
            rejected.append(stripped)
            continue
        # Still in the file -- it is append-only, and its history is not ours
        # to rewrite -- but no longer on the wall.
        if not is_released(domain):
            domains.add(domain)
    return sorted(domains), rejected


def parse(text):
    domains, _ = parse_lines(text)
    return domains
