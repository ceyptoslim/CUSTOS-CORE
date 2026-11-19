# Anchoring the frozen observation sets

**The gap this closes.** `tests/test_frozen_manifests.py` fails a pull request that edits, adds
or deletes a file inside a frozen run directory. It cannot fail one that edits the file *and* its
manifest line together, because the manifest travels in the same pull request. That is adequate
against accidents, which is the class of defect it was written for, and useless against a
deliberate rewrite. The only thing that closes it is a digest held somewhere this repository's
write access cannot reach.

## What is hashed, and what is not

Only the frozen directories: `docs/red-proof-records/run-*/`, each as one digest, with that run's
`MANIFEST.md` inside its own digest because the manifest is the file that defines the pins.

The living documents in the same parent directory are excluded on purpose. `PIN-GAPS.md`,
`ARTIFACT-CHECK-2026-11-17.md`, `COUNT-BASIS-506.md` and `custody-attack-staleness.md` are meant
to be updated. A digest over the whole directory breaks on the next honest edit, which is exactly
what happened twice in the week this scheme was written.

## The canonical form

Pinned in `scripts/anchor_digest.sh` and nowhere else, so the procedure is executable rather than
described:

- one line per file: `<sha256 of the bytes>  <path relative to the run directory>`
- exactly two spaces between digest and path, no `./` prefix
- lines sorted bytewise (`LC_ALL=C`) after hashing
- LF line endings, one trailing newline at the end of the stream
- the digest is `sha256` of that text

`.gitattributes` sets `-text` on `docs/red-proof-records/run-*/**`. Without it a clone with
end-of-line conversion would change frozen bytes and break every digest in every manifest.

Reproduce the aggregate:

```
scripts/anchor_digest.sh aggregate docs/red-proof-records
```

## The record

One JSON object per epoch, carrying the fields the custody anchors already use:

| Field | Meaning |
|---|---|
| `epoch` | monotonically increasing; epoch 0 is the first |
| `prev_anchor_hash` | sha256 of the previous record, empty at epoch 0 |
| `source_commit` | the commit whose tree was hashed |
| `scheme` | script path, sha256 of the script, and the canonical form in one line |
| `run_digests` | run directory name to digest |
| `aggregate` | sha256 over the sorted `<digest>  <run-name>` lines |

Epoch 0 is `docs/design/anchor-epoch-0.json`, a reference copy so CI can enforce the rule without
network access. The authoritative copy belongs in the anchor repository, outside any account or
token that can write here.

## The rule

Every run digest named in the current anchor must still be present and identical. A run that is
not in the anchor is allowed, because new observation sets are added over time and are anchored at
the next epoch. Nothing else may move.

**Containment, not only linkage.** Walking `prev_anchor_hash` back to epoch 0 proves the records
were chained in order. It does not prove what each one says: whoever holds the write token can
append an epoch that links correctly and carries a tampered run digest, and then the tip agrees
with the rewritten tree and every check passes. So each epoch must also contain every digest
anchored at every earlier epoch, unchanged. A dropped or altered digest fails the walk with the
epoch and the run named, and the same rule runs in the anchor repository's own workflow, template
at `docs/design/anchor-repo/verify-anchors.yml`, so a bad append is flagged where it lands rather
than only by a later reader.

```
scripts/check_anchors.sh docs/design/anchor-epoch-0.json docs/red-proof-records
```

Exit 0 unchanged, 1 for a changed or missing anchored run, 2 for a usage or parse error. Changing
`anchor_digest.sh` itself is a scheme change and requires a new epoch, which
`tests/test_anchor_digest.py` enforces by comparing the record's pinned script digest against the
script in the tree.

## Where the anchor lives

A separate public repository, `custos-anchors`, with a protected default branch, force-pushes and
deletions disabled, written only by a fine-grained token scoped to that repository with contents
write, held as a secret available to the anchoring workflow alone. A second account or
organisation for the anchor repository is stronger than a second token on the same account and is
cheap now, awkward later.

## What this establishes, and what it does not

It makes a rewrite of a frozen set visible to anyone holding the anchor, because the rewritten
tree no longer matches a record the repository cannot alter. It does not show that what was
anchored is what executed on a runner, it is not third-party corroboration of the observation
sets, and it does not move `custody_verified` off False.

## What earns the external label

The label is earned by two conditions, not by where a file happens to sit and not by a flag:

1. The record was fetched from the anchor repository's fixed address, and the caller states that
   address with `--chain-source`.
2. Its `prev_anchor_hash` chain walks back to epoch 0 without a break, and the record checked is
   the chain tip.

Three labels, and no fourth. `in-tree reference copy, not independent` when the record is inside
this checkout. `external path, chain not verified` when the record sits outside the checkout but
either condition is missing, which includes a path supplied by hand and a chain whose source was
not stated. `external anchor, chain verified to epoch 0` only when both hold. A path chosen by an
operator proves nothing about who published it, so it cannot earn the claim on its own.

A chain that does not verify exits 2 rather than degrading to a weaker label, and a record that is
not the tip exits 2 as well, because checking an old record against a newer chain would report
agreement with a state nobody is claiming.

**Until the external repository exists, nothing here is external anchoring.** The check reads
`docs/design/anchor-epoch-0.json`, a reference copy that a pull request can edit along with
everything else, so what CI enforces today is the append-only rule against accidents. Every run
prints the record it compared against and labels it `in-tree reference copy, not independent`, so
a green run cannot be read as an external verification. When the anchor repository is live the
check is given `--origin external`, and an unreadable or missing anchor then exits 2 rather than
falling back to the copy, because an unreachable anchor is not a pass.

## Scheme stability

A digest is only citable if two people on different machines get the same number, so each thing
that could vary was checked rather than assumed:

| Source of variance | Behaviour |
|---|---|
| Locale | Every sort runs under `LC_ALL=C`. Measured: `C`, `C.UTF-8` and `en_US.UTF-8` all produce `96219e94…`. |
| `find` ordering | Irrelevant, output is sorted before hashing. |
| Symlinks | Refused, exit 3, before any digest reaches stdout. `find -type f` skips a symlink while a path resolver follows it, so the two answers differ by exactly that file. |
| File modes | Not hashed. Measured: `chmod 600` leaves the digest unchanged. |
| Line endings | `.gitattributes` sets `-text` on the frozen paths, so no checkout converts bytes. |
| Filenames containing newlines | Unsupported, and no frozen record has one. |
| `sha256` implementation | `sha256sum` when present, `shasum -a 256` otherwise, resolved once at startup. Measured: both produce `96219e94…` on the same tree. With neither present the script exits 4 and prints nothing, so nobody quotes a number from a machine that could not compute it. |
| Tool versions | `sort`, `cut`, `sed` from coreutils, plus `python3` for `anchor-hash` and `record`. The record must contain no floats, because float formatting can differ between Python versions; epoch is an integer and every other field is a string. |
| Empty run directory | Degenerate, yields the empty-stream digest. The manifest guard fails such a directory first, since every file present must be pinned. |

## Changing the scheme

After the first anchor, a change to `anchor_digest.sh` costs a new epoch. The rule: write the new
epoch, and in its commit message put one line naming the script digest it replaces, so the change
is visible to anyone holding the previous tip without them having to diff the script. Before the
first anchor the same information goes in the amendment table below, and epoch 0 is simply
rewritten.

## Scheme change log

Changes after the first anchor, each one an epoch of its own:

| Epoch | Script digest | Replaced | Reason |
|---|---|---|---|
| 1 | `019bc008…` | `1257fc26…` | The script called `sha256sum` unconditionally, so on macOS, which ships `shasum` and not `sha256sum`, it exited 127 and printed nothing. A reader there could not reproduce the number at all. The canonical form is untouched: the aggregate is still `96219e94…`, and only the tool that computes the hash changed. |

The writer anchors a scheme change even when every digest is identical, because a record pins the script: a new script under an old anchor would claim a reproducibility nobody can check.

## Amended before publication

`docs/design/anchor-epoch-0.json` was amended twice on 2026-11-19, before any record was published
anywhere. Every run digest and the aggregate are unchanged throughout, because the canonical form
did not change: the aggregate stayed `96219e94…`. Only the recorded script digest and therefore the
record's own anchor hash moved.

| Amendment | Script digest | Anchor hash of epoch 0 |
|---|---|---|
| as first written | `0ac9b319…` | `7c6a991e…` |
| gained `anchor-hash` and the chain labels | `6b7dd37f…` | `cf1661db…` |
| refused symlinks and moved the check ahead of hashing | `1257fc26…` | `1c650575…` |

After the first anchor the same edit would appear as a broken chain and a changed anchor hash,
which is the point.

## Superseded values

Two aggregates were published before this form was pinned and are withdrawn: `81d4308d…`, computed
over the whole directory with a different path form, and `8aa5eb1f…`, computed with no trailing
newline. Neither was anchored. The canonical aggregate at `f06571b` is `96219e94…`, reproducible
with the command above.
