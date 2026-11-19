#!/usr/bin/env bash
# Canonical digest for the frozen observation sets.
#
# The canonical form is fixed here and nowhere else, so that a number can always
# be reproduced from the script rather than from prose describing it:
#
#   * one line per file: "<sha256 of the bytes>  <path relative to the directory>"
#   * exactly two spaces between digest and path
#   * no "./" prefix on the path
#   * lines sorted bytewise (LC_ALL=C) after hashing
#   * LF line endings, one trailing newline at the end of the stream
#
# Usage:
#   anchor_digest.sh per-run   <run-dir>            -> one digest
#   anchor_digest.sh listing   <root>               -> "<digest>  <run-name>" per run
#   anchor_digest.sh aggregate <root>               -> one digest over the listing
#   anchor_digest.sh record    <root> <commit> <epoch> <prev-anchor-hash>
#   anchor_digest.sh anchor-hash <record.json>      -> the record's own hash
#
# anchor-hash is sha256 over the record serialised with sorted keys, no spaces,
# one trailing newline. The chain in check_anchors.sh links records by it.
#
# Paths containing newlines are not supported; no frozen record has one, and the
# guard fails loudly rather than silently hashing something else.
set -euo pipefail

canonical_lines() {
    local dir="$1"
    ( cd "$dir" && find . -type f | LC_ALL=C sort | while IFS= read -r f; do
        printf '%s  %s\n' "$(sha256sum -- "$f" | cut -d' ' -f1)" "${f#./}"
    done ) | LC_ALL=C sort
}

anchor_hash() {
    python3 - "$1" <<'PYEOF'
import hashlib, json, sys
rec = json.load(open(sys.argv[1]))
body = json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n"
print(hashlib.sha256(body.encode()).hexdigest())
PYEOF
}

per_run() {
    canonical_lines "$1" | sha256sum | cut -d' ' -f1
}

listing() {
    local root="$1" d name
    for d in "$root"/run-*/; do
        [ -d "$d" ] || continue
        name="$(basename "$d")"
        printf '%s  %s\n' "$(per_run "$d")" "$name"
    done | LC_ALL=C sort -k2,2
}

aggregate() {
    listing "$1" | sha256sum | cut -d' ' -f1
}

record() {
    local root="$1" commit="$2" epoch="$3" prev="$4" script_sha
    script_sha="$(sha256sum -- "$0" | cut -d' ' -f1)"
    printf '{\n'
    printf '  "epoch": %s,\n' "$epoch"
    printf '  "prev_anchor_hash": %s,\n' "$(printf '%s' "$prev" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
    printf '  "source_commit": "%s",\n' "$commit"
    printf '  "scheme": {\n'
    printf '    "script": "scripts/anchor_digest.sh",\n'
    printf '    "script_sha256": "%s",\n' "$script_sha"
    printf '    "canonical_form": "sha256 over sorted \\"<sha256>  <relpath>\\" lines, LC_ALL=C, LF, two spaces, trailing newline"\n'
    printf '  },\n'
    printf '  "run_digests": {\n'
    listing "$root" | while IFS= read -r line; do
        printf '    "%s": "%s",\n' "$(printf '%s' "$line" | sed 's/^[0-9a-f]*  //')" "$(printf '%s' "$line" | cut -d' ' -f1)"
    done | sed '$ s/,$//'
    printf '  },\n'
    printf '  "aggregate": "%s"\n' "$(aggregate "$root")"
    printf '}\n'
}

case "${1:-}" in
    per-run)   [ $# -eq 2 ] || { echo "usage: $0 per-run <run-dir>" >&2; exit 2; }; per_run "$2" ;;
    listing)   [ $# -eq 2 ] || { echo "usage: $0 listing <root>" >&2; exit 2; }; listing "$2" ;;
    aggregate) [ $# -eq 2 ] || { echo "usage: $0 aggregate <root>" >&2; exit 2; }; aggregate "$2" ;;
    record)    [ $# -eq 5 ] || { echo "usage: $0 record <root> <commit> <epoch> <prev-anchor-hash>" >&2; exit 2; }; record "$2" "$3" "$4" "$5" ;;
    anchor-hash) [ $# -eq 2 ] || { echo "usage: $0 anchor-hash <record.json>" >&2; exit 2; }; anchor_hash "$2" ;;
    *) echo "usage: $0 {per-run|listing|aggregate|record|anchor-hash} ..." >&2; exit 2 ;;
esac
