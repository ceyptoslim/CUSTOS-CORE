# Binding version 2: the commitment form on the record, and version dispatch

Status: implemented on the emitter, the verifier, both backends and the retention
store. Version 1 records keep verifying byte-identically.

## Why a version bump and not a new field

Two facts needed to travel with a record, and both change what its hash means.

The first is which form the `content_hash` digest is in. A record whose content
was stored with a per-record salt and a record whose content was never stored
both carry 64 hex characters, and without a marker a reader holding an export
cannot tell "this cannot be recomputed because it was purged" from "this does not
match the content". Those are different findings and collapsing them is the
defect class this project keeps finding: an anomaly sharing its signature with
the benign case, or in this case with the attack.

The second is what happens to a record claiming a version this build does not
implement. Before this change, an unknown version hashed with the current field
list, mismatched, and reported:

    Record 0 hash invalid -- tampering detected

A legitimate future record, a tombstone written by a later writer, and an edited
record therefore shared one signature. The version dispatch is what separates
them, and it has to ship with the marker rather than after it: a marker inside the
preimage without a bump makes two incompatible meanings share version number 1.

## What version 2 binds

Version 2 is the version 1 preimage by byte-for-byte extension, never a
reordering:

| field | v1 | v2 |
| --- | --- | --- |
| timestamp, client_id, action, triggered_rule, reason, content_hash, previous_hash | yes | yes |
| policy_digest, tenant_id (when set) | yes | yes |
| binding: "vN" | yes | yes |
| trace_id (when set) | yes | yes |
| commitment | no | yes, always |

`commitment` is present even when the answer is `none`, so a version 2 record
states what it holds instead of leaving absence to be read as any of the four
forms. The four:

- `none`: the content was never stored by this service. A bare digest of the
  request, no commitment claim.
- `unsalted-v0`: stored without a salt. Reproducible by anyone holding the body,
  which is the enumeration exposure a salt exists to remove.
- `salted-v1`: stored with a per-record CSPRNG salt in the side store. Not
  reproducible from the body alone except by guessing the salt.
- `purged-v1`: this digest's content was deleted and attested. Cannot be
  recomputed by design, and the form says so rather than leaving a reader to
  conclude the content was tampered with.

An unrecognised form is refused at the emitter instead of recorded, because a
typo'd marker produces a record that looks classifiable and is misclassified,
which is worse than a record that says it does not know.

## Migration note for readers of version 1

1. A version 1 record verifies at version 1 forever. Nothing recomputes it as
   version 2, and no stored row is rewritten: rewriting a chained preimage
   destroys the property the chain exists for.
2. A version 1 record has **no** commitment form. That is not `none` in the sense
   of "the service decided not to store it", it is NOT RECORDED. Reporting it as
   `none` would attribute a decision to a writer that never made one. Tooling
   written against version 2 must render a version 1 record's form as unknown or
   absent, not as a form.
3. Tooling that recomputes version 1 hashes keeps working unchanged, because the
   version 1 field list did not move.
4. A verifier must dispatch on `binding_version` before hashing. Hashing an
   unimplemented version with the current field list produces a false tampering
   finding, which is exactly the failure this version removes.
5. A version 2 row relabelled as version 1 is detected: the preimage loses
   `commitment`, so the stored hash no longer matches. Editing the version field
   is an edit.
6. Any figure that spans both versions has to say which it means. A count of
   "records with no stored content" that folds version 1 records in is
   understating, and one that calls them all identified is overstating.

## What this does not do

- It does not make a salt's absence detectable from the record alone. The record
  says which form was used; it cannot prove the salt existed or was destroyed.
- It does not reach a copy of the side store taken before a purge. The purge
  drill measures that limit; this marker only makes the state describable.
- It does not change the version 0 records from before any binding existed. They
  still verify at version 0 with the original field list.
- It does not implement version 3 or any later version, and it will refuse them
  by name rather than guessing. That refusal is a statement about this build, not
  about the record.
