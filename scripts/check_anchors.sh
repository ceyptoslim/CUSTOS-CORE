#!/usr/bin/env bash
# Append-only check against an anchor record.
#
# Rule: every run digest named in the anchor must still be present and identical.
# A run that is not in the anchor is allowed, because new observation sets are
# added over time and are anchored at the next epoch. Nothing else is allowed to
# move.
#
# Usage: check_anchors.sh <anchor-record.json> <root>
# Exit:  0 unchanged, 1 drift or a missing anchored run, 2 usage/parse error.
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: $0 <anchor-record.json> <root>" >&2; exit 2; }
record="$1"; root="$2"
[ -f "$record" ] || { echo "anchor record not found: $record" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
status=0

while IFS=$'\t' read -r name expected; do
    [ -n "$name" ] || continue
    dir="$root/$name"
    if [ ! -d "$dir" ]; then
        echo "MISSING  $name  anchored at epoch $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["epoch"])' "$record") but absent from the tree"
        status=1
        continue
    fi
    actual="$("$here/anchor_digest.sh" per-run "$dir")"
    if [ "$actual" != "$expected" ]; then
        echo "CHANGED  $name"
        echo "         anchored $expected"
        echo "         actual   $actual"
        status=1
    else
        echo "ok       $name"
    fi
done < <(python3 - "$record" <<'PY'
import json, sys
rec = json.load(open(sys.argv[1]))
for name, digest in rec["run_digests"].items():
    print(f"{name}\t{digest}")
PY
)

anchored="$(python3 -c 'import json,sys;print("\n".join(json.load(open(sys.argv[1]))["run_digests"]))' "$record")"
for d in "$root"/run-*/; do
    [ -d "$d" ] || continue
    name="$(basename "$d")"
    if ! printf '%s\n' "$anchored" | grep -qx "$name"; then
        echo "new      $name  not in this epoch, allowed until the next anchor"
    fi
done

exit "$status"
