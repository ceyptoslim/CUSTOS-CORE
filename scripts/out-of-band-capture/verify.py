#!/usr/bin/env python3
"""Recompute the self-hash of a capture transcript.

The transcript states the sha256 of everything written before the "## Self-hash"
line. This recomputes it, so a reader does not have to trust the file's own claim.

    python3 verify.py out-of-band-<stamp>-<role>.txt
"""
import hashlib
import sys

def main(path: str) -> int:
    raw = open(path, "rb").read()
    marker = b"## Self-hash\n"
    idx = raw.rfind(marker)
    if idx < 0:
        print("FAIL: no self-hash section found", file=sys.stderr)
        return 2
    head = raw[:idx]
    stated = None
    for line in raw[idx:].decode("utf-8", "replace").splitlines():
        if line.startswith("sha256(before this line): "):
            stated = line.split(": ", 1)[1].strip()
    if not stated:
        print("FAIL: self-hash section present but no hash line", file=sys.stderr)
        return 2
    actual = hashlib.sha256(head).hexdigest()
    ok = actual == stated
    print(f"stated: {stated}")
    print(f"actual: {actual}")
    print("RESULT:", "MATCH" if ok else "MISMATCH")
    return 0 if ok else 1

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 verify.py <transcript>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
