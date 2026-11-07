# Idempotent decision replay and caller-supplied correlation

Status: proposed rule for item 2 of issue 113. No implementation yet. The rule
is written first because the implementation has to conform to something a reader
can check, and because two of the choices below would be fail-open if they were
made by whoever writes the code at the end of a long day.

## The defect this addresses

A request that times out and is retried currently produces a second decision and
a second record. Nothing in the ledger distinguishes that retry from a genuine
second attempt by the same caller. This is not an execution bug: the gate made
two decisions and recorded both correctly. It is a record-ambiguity defect, and
the record is the product.

## Vocabulary

- **Replay**: return a decision that was already recorded for this attempt.
- **Re-evaluate**: make a fresh decision now, and record it.
- **Attempt**: two requests are the same attempt only if their request digests
  match. Everything follows from that.

## The key

A caller-supplied `Idempotency-Key` header, opaque to the gate, printable ASCII,
bounded in length. Scope is the tuple `(tenant, endpoint, key)`, so the same key
on a different endpoint or tenant is a different attempt.

The gate binds `key -> {request_digest, decision, record_hash, policy_digest,
created_at}`. The binding is written in the same operation as the audit record,
never before it and never after: a binding without a record would replay a
decision that cannot be pointed at.

## Request digest

A canonical serialization of the request body (sorted keys, no insignificant
whitespace) hashed with SHA-256, in the same style as the audit content hash.
Without a canonical form, two byte-different encodings of the same payload would
be treated as two attempts and the key would buy nothing.

## The rule

| state | action | record |
|---|---|---|
| key absent | decide normally | one record |
| key unseen | decide, then bind | one record |
| key seen, same digest, original DENY | replay the denial | no new record |
| key seen, same digest, original ALLOW or AUDIT, policy digest unchanged | replay | no new record |
| key seen, same digest, original ALLOW or AUDIT, policy digest changed | re-evaluate | new record, marked re-evaluated |
| key seen, different digest | refuse with a conflict status | no record, no decision |

A replayed response says so. It carries `replay: true` and the hash of the record
it is replaying, because a caller who cannot tell a replay from a fresh decision
has gained nothing.

## Why a DENY replays unconditionally, and why that is a limitation

A replayed denial cannot authorize anything, so replaying it can never let an
effect through. It can, however, be stale: if the policy has since loosened, a
replayed denial refuses something that would now be allowed. That is the
fail-closed direction and the right one to fail in, so the denial is replayed and
the original policy digest is named in the response. The caller's recovery is a
new key, deliberately, rather than the gate silently deciding that a refusal was
out of date.

## Why an ALLOW does not replay across a policy change

An approval minted under an earlier policy, replayed after the policy tightened,
is a fail-open wearing a convenience label. It would certify, in a record, an
authorization that no rule currently in force grants. So the gate re-evaluates
and records a new decision, and the response names both policy digests so the
discrepancy is visible rather than smoothed.

## Why key reuse with a different payload is refused

Returning a decision about payload A to a request carrying payload B is the exact
confusion this rule exists to prevent. Refusing costs a caller one clear error and
one new key; replaying costs the ledger its meaning.

## Durability, and the honest limit

Replay protection is worth what the key store is worth. If the store is per
process, two replicas will happily replay and re-decide the same attempt, exactly
as the in-process rate limiter lets quotas drift across replicas. So:

- the store lives in the configured audit backend, with a unique constraint on
  `(tenant, endpoint, key)`, so a concurrent duplicate loses the race at the
  database rather than in application logic;
- an in-memory store is permitted in development and refused in production, in
  the same spirit as the existing refusal to start with a development secret;
- the response states which store answered, so a caller is never guessing
  whether the protection was real.

Default window: one day, configurable. The window is bounded by record retention,
which does not exist yet, so this rule depends on the retention work rather than
pretending to stand alone. When a key ages out, the attempt becomes fresh again,
and that is a property of the window, not a defect: it should be stated wherever
the window is configured.

## Caller-supplied correlation

The second half of the issue is adjacent and separate. A caller-supplied
`X-Request-ID` is recorded as `caller_request_id`, kept distinct from the
server-generated `trace_id`, with both covered by the record hash under a new
record binding version. Old records keep verifying at their own version.

What that supports is narrow and worth stating plainly: the record shows that
**the gate was told** this identifier. It does not show that the identifier is
the request. A caller who asserts a false id produces a record that faithfully
reports a false assertion, which is still useful, because the discrepancy between
what the caller claimed and what the record holds is checkable. It is not
authentication, and no document should describe it as such.

## Schema decision for the caller-supplied identifier

A caller-supplied identifier is a schema decision before it is a header parse,
because what enters the hash preimage decides what the record can attest. This is
the decision, and it is the thing code has to conform to.

- **Field.** `caller_request_id`, nullable, at most 255 printable ASCII
  characters, opaque to the gate. The gate validates length and character class
  because the value enters a hash preimage, and imposes no other meaning.
- **Position.** The version 3 preimage is the version 2 preimage, byte for byte
  and in the same field order, with `caller_request_id` appended at the end. An
  extension rather than a reordering, because a reordering would silently
  invalidate every tool that recomputes earlier hashes. A verification
  implementation that has to special-case field order is a bug in the
  implementation, not in the format.
- **Renumbered once, deliberately.** This field was planned as version 2 and is
  now version 3. Version 2 landed first and it is the commitment form
  (`docs/design/binding-version-2.md`): the marker that says whether a record's
  `content_hash` is a bare digest, a salted one, or one whose content was purged.
  That could not wait behind this field, because retention cannot be built on
  digests a reader cannot classify, and because two independent features cannot
  share a version number without giving two incompatible meanings one name. So
  the order is version 2 = commitment form, version 3 = caller id, and each one
  appends to the last rather than reorganising it.
- **Absent is not empty.** No header means the field is null. An empty or
  whitespace-only header is refused at the API boundary with a client error and
  is never recorded, so absent cannot be forged by sending nothing. An
  over-length value is refused rather than truncated: a sliced identifier would
  be a different string from the one the caller asserted, and the record would
  then be a faithful account of something nobody said.
- **Two identifiers, never merged.** `trace_id` stays server-generated and
  `caller_request_id` stays caller-asserted, and both are inside the hash. The
  temptation is one correlation field that either party can populate. That field
  would make the record ambiguous about who asserted what, which is the one
  property worth protecting here.

## Migration note for readers of binding version 1

Six statements, each of which a report can get wrong:

1. Version 1 records keep verifying at version 1 indefinitely. Verification
   dispatches on `binding_version`, and the current layout is never assumed.
2. A version 1 record has no `caller_request_id`. That means not recorded, not
   absent in the sense of nothing supplied. The distinction is unrecoverable
   after the fact, which is why the next statement matters.
3. Any figure computed across both versions says so. Counting version 1 records
   as "no caller id supplied" would understate what callers did, and counting
   them as "unidentified" would overstate it.
4. Tooling refuses to verify a record at a version it does not implement, in
   either direction, and names the version it found. It fails loudly rather than
   passing a hash that happens to match, because a coincidence here would be
   indistinguishable from verification, and it reports the version rather than
   "tampering detected", because a legitimate future record and an edited one
   must not share a signature.
5. For version 1 records, the only correlation available is the server trace id,
   and it is navigable backwards from the record, not forwards from a caller.
   A support question of the form "what happened to my request" is not answerable
   from a version 1 chain without the record.
6. Existing rows are not migrated, and recomputing old hashes under the new
   version is forbidden. Rewriting the preimage of a chained record would destroy
   the property the chain exists to provide, and no schema change is worth that.

## What this rule does not do

- It does not prevent two different attempts, under two different keys, from
  producing two effects.
- It does not make retries safe at the effect layer. Idempotency at the gate
  bounds duplicate decisions, not duplicate commits; that belongs to the
  executor and its own guarantees.
- It does not establish caller identity.
- It does not survive a lost key store as though nothing happened. A lost store
  silently ends the window, which is why the store's durability is part of the
  claim rather than an implementation detail.

## Acceptance conditions

The rule is implemented when each of these can fail, not merely pass:

1. A repeated request with the same key and digest yields exactly one record.
2. A replayed denial yields exactly one record.
3. An approval replayed after a policy change yields a second record marked
   re-evaluated, and names both policy digests.
4. A key reused with a different payload is refused, and creates neither a
   decision nor a record.
5. A restart with a durable store preserves the binding; a restart with the
   in-memory store loses it, and the response said which one was in use.
6. Removing the digest comparison makes a majority of the above fail. If it does
   not, the digest is decorative and the rule is not implemented.

## Open questions for the owner

- Window default and whether it is per tenant.
- Whether the conflict status is the right answer to reuse with a different
  payload, or whether a new decision under the same key should instead be
  recorded with both attempts linked.
- Whether the binding belongs in the audit backend or in a store the operator
  chooses independently of where records live.
