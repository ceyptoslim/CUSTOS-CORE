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

## Superseded values

Two aggregates were published before this form was pinned and are withdrawn: `81d4308d…`, computed
over the whole directory with a different path form, and `8aa5eb1f…`, computed with no trailing
newline. Neither was anchored. The canonical aggregate at `f06571b` is `96219e94…`, reproducible
with the command above.
