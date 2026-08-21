"""Repair control characters injected into source by shell heredocs.

A heredoc that passes ``\\b`` through an unquoted context turns it into a
literal backspace byte (0x08). Inside a regex the result is silently wrong and
invisible to ``grep``, ``sed`` and ``cat`` -- the terminal simply does not draw
it. Two live regexes in this project were broken that way:

* ``residual_text`` never split on ``w/``
* the provider's daily-quota detector never matched ``\\bTPD\\b`` or ``\\bRPD\\b``

Both looked correct in every inspection. This script finds and repairs them,
and ``tests/test_core.py`` now fails if one ever comes back.
"""
from __future__ import annotations

import os
import subprocess
import sys

REPAIRS = {
    0x08: b"\\b",   # backspace  <- \b
    0x0C: b"\\f",   # form feed  <- \f
    0x0B: b"\\v",   # vert tab   <- \v
    0x07: b"\\a",   # bell       <- \a
    0x1B: b"\\x1b",
}

#: Bytes that are legitimate in a source file.
ALLOWED = {0x09, 0x0A, 0x0D}


def offenders(data: bytes):
    return [(i, b) for i, b in enumerate(data)
            if b < 0x20 and b not in ALLOWED]


def repair(path: str, apply: bool = True) -> int:
    with open(path, "rb") as fh:
        data = fh.read()
    hits = offenders(data)
    if not hits:
        return 0
    out = bytearray()
    for b in data:
        if b < 0x20 and b not in ALLOWED:
            out.extend(REPAIRS.get(b, b""))
        else:
            out.append(b)
    if apply:
        with open(path, "wb") as fh:
            fh.write(bytes(out))
    return len(hits)


def tracked_sources():
    try:
        out = subprocess.run(["git", "ls-files", "*.py"],
                             capture_output=True, text=True, check=True).stdout
        return [p for p in out.split() if os.path.exists(p)]
    except Exception:
        found = []
        for root, _dirs, files in os.walk("caliper"):
            found += [os.path.join(root, f) for f in files if f.endswith(".py")]
        return found


def main(argv) -> int:
    check_only = "--check" in argv
    total = 0
    for path in tracked_sources():
        n = repair(path, apply=not check_only)
        if n:
            total += n
            print("  {:<40} {} control char(s)".format(path, n))
    if total == 0:
        print("  clean: no control characters in any tracked source")
        return 0
    print("  {} occurrence(s) {}".format(
        total, "found" if check_only else "repaired"))
    return 1 if check_only else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
