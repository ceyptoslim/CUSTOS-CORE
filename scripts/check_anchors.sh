#!/usr/bin/env bash
# Append-only check against an anchor record.
#
# Rule: every run digest named in the anchor must still be present and identical.
# Across a chain, every digest anchored at an earlier epoch must survive unchanged
# into every later epoch, so a correctly linked append cannot carry a tampered one.
# A run that is not in the anchor is allowed, because new observation sets are
# added over time and are anchored at the next epoch. Nothing else is allowed to
# move.
#
# Usage: check_anchors.sh <anchor-record.json> <root> [--origin in-tree|external]
#                                 [--chain <dir-of-records>] [--chain-source <where>]
# Exit:  0 unchanged, 1 drift or a missing anchored run, 2 usage/parse error or an
#        external anchor that could not be read (fail closed).
#
# Every run prints which record it compared against, because a green run against
# the in-tree reference copy is not an external verification and must never read
# as one.
set -euo pipefail

[ $# -ge 2 ] || { echo "usage: $0 <anchor-record.json> <root> [--origin in-tree|external]" >&2; exit 2; }
record="$1"; root="$2"; shift 2
origin=""; chain_dir=""; chain_source=""
while [ $# -gt 0 ]; do
    case "$1" in
        --origin) origin="${2:-}"; shift 2 ;;
        --chain) chain_dir="${2:-}"; shift 2 ;;
        --chain-source) chain_source="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
here="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$here/.." && pwd)"
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
# The label is earned, not inferred from where the file happens to sit. An
# external path alone proves nothing about who published it, so it reads as an
# unverified external path until the record's own chain is walked back to epoch 0
# and the caller states where the records came from.
label="in-tree reference copy, not independent"
if [ "$origin" = "external" ]; then
    label="external path, chain not verified"
fi
chain_tip=""
if [ -n "$chain_dir" ]; then
    [ -d "$chain_dir" ] || { echo "FAIL     chain directory not found: $chain_dir" >&2; exit 2; }
    if ! chain_tip="$(python3 - "$chain_dir" <<'PYEOF'
import glob, hashlib, json, os, sys
def h(rec):
    return hashlib.sha256((json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
files = sorted(glob.glob(os.path.join(sys.argv[1], "*.json")))
if not files:
    sys.exit("no records in the chain directory")
recs = [json.load(open(f)) for f in files]
recs.sort(key=lambda r: r["epoch"])
epochs = [r["epoch"] for r in recs]
if epochs != list(range(len(recs))):
    sys.exit(f"epochs are not contiguous from 0: {epochs}")
if recs[0]["prev_anchor_hash"] != "":
    sys.exit("epoch 0 carries a prev_anchor_hash, so the chain does not start here")
for i in range(1, len(recs)):
    if recs[i]["prev_anchor_hash"] != h(recs[i - 1]):
        sys.exit(f"epoch {recs[i]['epoch']} does not link to epoch {recs[i-1]['epoch']}")
    # Containment: a link alone is not enough. Whoever holds the write token can
    # append an epoch that links correctly and still carries a tampered run
    # digest, which would make the tip agree with a rewritten tree. Every digest
    # anchored earlier must therefore survive unchanged into every later epoch.
    prev, cur = recs[i - 1]["run_digests"], recs[i]["run_digests"]
    for name, digest in prev.items():
        if name not in cur:
            sys.exit(f"epoch {recs[i]['epoch']} drops anchored run {name}")
        if cur[name] != digest:
            sys.exit(f"epoch {recs[i]['epoch']} changes anchored run {name}: "
                     f"{digest[:12]} became {cur[name][:12]}")
print(f"{recs[-1]['epoch']} {h(recs[-1])} {len(recs)}")
PYEOF
)"; then
        echo "FAIL     anchor chain does not verify" >&2
        exit 2
    fi
    tip_epoch="${chain_tip%% *}"; rest="${chain_tip#* }"
    tip_hash="${rest%% *}"; tip_count="${rest##* }"
    record_hash="$("$here/anchor_digest.sh" anchor-hash "$record")"
    if [ "$record_hash" != "$tip_hash" ]; then
        echo "FAIL     the record checked is not the chain tip (tip is epoch $tip_epoch)" >&2
        exit 2
    fi
    if [ -n "$chain_source" ] && [ "$origin" = "external" ]; then
        label="external anchor, chain verified to epoch 0"
    fi
    echo "chain    $tip_count record(s), epochs 0 to $tip_epoch linked, tip $tip_hash"
    echo "chain-source ${chain_source:-not stated}"
fi
echo "source   $record ($label)"

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
