#!/usr/bin/env python3
"""Offline custody verifier: walk a store copy against an external anchor log.

Answers the question the internal chain cannot answer: is the copy I am
holding the whole store, or a consistent subset of it? Reads two files, writes
nothing, touches no network, and trusts neither the deployment nor this
repository.

    python scripts/verify_custody.py --records store.json --anchors anchors.json

Propositions (see docs/design/chain-head-custody.md):
  P1 record-chain internal consistency, recomputed from the copy
  P2 every anchored head matches the recomputed hash at that length
  P3 anchor-chain integrity (epochs, prev links, anchor hashes)
  P4 store completeness against the anchors (truncation detection)
  P5/P6 policy-commit integrity and citation membership, when present

Exit codes: 0 ESTABLISHED, 1 CANNOT ESTABLISH, 2 CONTRADICTION, 3 usage error.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from custos.custody import (  # noqa: E402
    CANNOT_ESTABLISH,
    CONTRADICTION,
    ESTABLISHED,
    verify_custody,
)

EXIT = {ESTABLISHED: 0, CANNOT_ESTABLISH: 1, CONTRADICTION: 2}


def _load(path: str, key: str) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get(key, [])
    if not isinstance(data, list):
        raise SystemExit(f"{path}: expected a JSON list, or an object under '{key}'")
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify a CUSTOS audit store copy against an external anchor log."
    )
    ap.add_argument(
        "--records",
        required=True,
        help="store copy as JSON: a list, or {'records': [...]}",
    )
    ap.add_argument(
        "--anchors",
        required=True,
        help="external anchor log as JSON: a list, or {'anchors': [...]}",
    )
    ap.add_argument(
        "--tokens",
        help="directory of RFC 3161 token files (.tsr); reported, not verified here",
    )
    ap.add_argument("--json", action="store_true", help="emit the raw result as JSON")
    args = ap.parse_args(argv)

    records = _load(args.records, "records")
    anchors = _load(args.anchors, "anchors")
    result = verify_custody(records, anchors)
    verdicts = result["verdicts"]
    overall = result["overall"]

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print(f"records: {len(records)}   anchors: {len(anchors)}")
        for name in sorted(verdicts):
            print(f"  {name:38s} {verdicts[name]}")
        print(f"  {'OVERALL':38s} {overall}")
        for key in sorted(result.get("detail", {})):
            print(f"  {key}: {result['detail'][key]}")

    if args.tokens:
        if os.path.isdir(args.tokens):
            found = sorted(f for f in os.listdir(args.tokens) if f.endswith(".tsr"))
        else:
            found = []
        print(
            f"tsa tokens: {len(found)} (verify each with: openssl ts -verify "
            "-data anchor.json -in token.tsr -CAfile tsa.pem)"
        )

    return EXIT[overall]


if __name__ == "__main__":
    sys.exit(main())
