Status registered: item 1 and item 5 are closed, and item 1 is closed by measurement rather than by document. Items 2, 3 and 7 stand exactly where the last round left them. The drill exists as a run record with commands and outputs, not as a summary, and it contains a phase that argues against us.

1. On the omission, and on the measurement that follows from it.

The correction is accepted and item 4's phrasing closes without an edit. I will add only this: the residual you named is now measured rather than argued. In the drill, a four-record chain had its last row deleted in the store and then verified on the remaining three. It returned (True, 'OK'). Restoring an older dump produces the identical shape, because an older dump is a shorter consistent chain. So "a shorter honest-looking chain verifies green" is no longer a caution inside a design document; it is a line in a run record with the command above it and the output below it.

That leaves external head anchoring as the only mechanism separating complete from short, and it closes the same gap for a whole-chain rewrite by a store-privileged writer. Neither is a pilot-entry gate here, and I am not going to describe the product in a way that implies completeness. Tamper-evident remains a property of the chain.

2. On Tier 1: the splice is withdrawn, and I am taking commitment separation, with the salt form already agreed.

Your arithmetic is right and it is the same arithmetic that killed the fork. If a tombstone replaces a purged record's content, the tombstone's hash is not the purged record's hash, and the successor's previous_hash points at a hash that no longer exists in the chain. That is a splice, and a splice is a silent fork with a different cause.

So item 3 uses commitment separation, instantiated as the per-record CSPRNG salt in a side store, plus the marker, plus the control inheritance, which is the fourth form we already settled. The record hash commits to a salted content digest. The digest stays in the preimage, the content lives outside it, and purging removes the content and destroys the salt. The chain then still verifies from genesis and the unique index is never stressed, which was your stated advantage for the attestation form and it holds for this one too.

One correction to your cost paragraph, and it matters for a PII pilot. You wrote that commitment separation leaves "the retained digest is still a hash of the removed content", a residual disclosure the operator must decide about. With the salt, the retained digest is a hash of salted content whose salt no longer exists, so a reader holding the digest cannot confirm a guess about the content it was taken from. A digest of an email address is a brute-forceable identifier in a way a digest of that address under 32 destroyed random bytes is not. The purge therefore deletes linkability rather than deleting a hash, which is the property Tier 1 exists for.

The bound on that sentence, stated before it is relied on: if any backup retains the salt, linkability returns, and a purge that reaches the content store but not the side store is not a purge. That is a run, not a policy sentence, and it is why the closing artifact has to include the run.

What survives from your other form is kept deliberately: the purge event is visible, because an attestation record is appended at the head naming the purged record ids, the time and the operator. Appending is not splicing. So the shape is commitment separation as the mechanism, an appended record as the event. The cost you attached to the attestation form is accepted as well: after a purge the content is verifiable by nobody, including an auditor who later needs it, and a retained verifiable copy would not be a deletion.

3. On the in-memory residual: closed, and it was already true.

The startup path names the backend before anything is served, in two lines. The first is a topology summary carrying audit_backend and audit_durability as durable or ephemeral. The second is emitted by the persistence check and carries audit_backend, audit_durable, audit_store_source and environment, where audit_store_source is DATABASE_URL, AUDIT_DB_PATH or none, so a reader is told which variable is in force rather than left to infer it. /v1/info carries audit_backend and audit_durable on the served surface. Production on an ephemeral chain refuses to start, and it refuses for two distinct reasons: no store configured, versus a store configured whose variable was read after the chain was built. In the second case the message does not tell the operator to set a variable they have already set, it says the configuration was read too late.

Both are in the drill transcript verbatim, phases 1 and 7.

One honest limit on this answer, because you will look for it: /v1/info names the backend but not the store source, which appears in the startup line and in the refusal. If your view is that the API surface is the only surface a reader has, that is a one-line addition and I will make it next.

4. On bypass: accepted, and the instrument is half present already.

The relocation is right and item 7's measurement section will read operator-measured, gate cannot report it. On your consequence, one clarification that changes how much is missing. The executor can compute a bypass rate today from the gate's record hash alone, because the hash is a decision identifier that already exists and can be logged next to the effect. What it cannot do from the hash alone is join a request that never reached the gate to the caller's own identity for that request, because nothing on the caller's side carries a value the gate also recorded. That is exactly what the caller-supplied id supplies, and it is why it is instrumentation and not only attestation semantics. So the first instrument exists and the second is specified rather than built, and item 7 stays defined and not measured until a deployment produces the numbers.

5. Where the package actually stands.

Item 5, closed by construction: the single-writer constraint is in both durable backends, and the drilled database shows it live, an index on the coalesced tenant id and previous_hash.

Item 1, closed by measurement: a production process wrote two decisions through the served evaluation path into PostgreSQL, a fresh process read them back and verified from the all-zero genesis, a dump was taken, the dump was restored into a fresh database and verified to the same digests, the restored store then accepted two more records chaining onto the recovered head, a shortened copy verified, and production with no store refused to serve. Seven phases, each a separate process.

Item 2, written rule merged, field not built. Binding version 2 is the version 1 preimage byte for byte with the caller field appended, an extension rather than a reordering, and the absent value stays distinguishable from an empty one because an empty or whitespace-only value is refused at the boundary rather than recorded.

Item 3, not started, and the sequencing is unchanged: unknown-version dispatch first, then the commitment marker, then the purge path, then the export and backup run. The measurement behind that ordering: a record claiming an unknown binding version currently fails verification as "hash invalid, tampering detected", so a legitimate future tombstone would read as an attack. Dispatch needs its own refusal reason before a purge path can exist.

Item 7, defined and not measured.

Item 4a, unchanged and pinned: eighteen action references at commit shas and none floating.

6. On the pattern you named.

Two anomalies were fixed the same way in one round, and it is worth stating as the rule rather than as two incidents: an unknown version and a forked chain were both indistinguishable from tampering because both were routed into the tampering message. Neither needed a tighter check. Each needed its own refusal reason. A shared error path degrades the evidence, because the signature of the accident becomes the signature of the attack.

I am not asking to move the verdict. I am returning item 1 closed and item 3 next, and when item 3 returns it will carry the run rather than the policy: the chosen form, the export, the backup, and a seeded-PII purge that leaves the chain verifying green from genesis.
