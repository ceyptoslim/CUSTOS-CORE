#!/usr/bin/env bash
# Append-only check against an anchor record.
#
# Rule: every run digest named in the anchor must still be present and identical.
# A run that is not in the anchor is allowed, because new observation sets are
# added over time and are anchored at the next epoch. Nothing else is allowed to
# move.
#
# Usage: check_anchors.sh <anchor-record.json> <root> [--origin in-tree|external]
# Exit:  0 unchanged, 1 drift or a missing anchored run, 2 usage/parse error or an
#        external anchor that could not be read (fail closed).
#
# Every run prints which record it compared against, because a green run against
# the in-tree reference copy is not an external verification and must never read
# as one.
set -euo pipefail

[ $# -ge 2 ] || { echo "usage: $0 <anchor-record.json> <root> [--origin in-tree|external]" >&2; exit 2; }
record="$1"; root="$2"; shift 2
origin=""
while [ $# -gt 0 ]; do
    case "$1" in
        --origin) origin="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
# Canonicalise so a relative path and an absolute path to the same file are
# classified the same way. A record that does not exist keeps its raw path.
if [ -f "$record" ]; then
    record_abs="$(cd "$(dirname "$record")" && pwd)/$(basename "$record")"
else
    record_abs="$record"
fi
if [ -z "$origin" ]; then
    case "$record_abs" in
        "$repo_root"/*) origin="in-tree" ;;
        *) origin="external" ;;
    esac
fi
case "$origin" in
    in-tree|external) ;;
    *) echo "unknown origin: $origin" >&2; exit 2 ;;
esac
if [ ! -f "$record" ]; then
    if [ "$origin" = "external" ]; then
        echo "FAIL     external anchor unreadable: $record" >&2
        echo "         refusing to fall back to the in-tree copy; an unreachable anchor is not a pass" >&2
    else
        echo "anchor record not found: $record" >&2
    fi
    exit 2
fi
if [ "$origin" = "in-tree" ]; then
    echo "source   $record (in-tree reference copy, not independent)"
else
    echo "source   $record (external anchor)"
fi

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
