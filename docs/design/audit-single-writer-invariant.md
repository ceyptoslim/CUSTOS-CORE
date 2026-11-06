# The audit chain is single-writer, and the store now enforces it

Status: implementation note. The constraint described here is enforced in
`custos/audit.py` and covered by `tests/test_audit_single_writer.py`.

## The state before this change

The chain was single-writer by convention. Nothing enforced it, and the failure
it permitted was demonstrated against a SQLite store rather than argued:

1. Two processes each construct a chain against the same store before either
   appends. The constructor loads existing records, so both hold the same head.
2. Company A appends. Company B appends. Each computes `previous_hash` from the
   head it loaded, so the store receives two records naming the same parent.
3. Both processes verify green, because each walks only the list it holds in
   memory. Neither is ever told it forked the chain.
4. A later reader loading the whole store reports `Chain broken at record 2:
   previous_hash mismatch`. That is the same message genuine tampering produces,
   so the record has stopped being able to distinguish an accident from an edit.

Step 4 is the damage. It is not that the fork existed, it is that the evidence
could no longer say which story was true.

## What changed

`previous_hash` carries a unique index in both durable backends. A given
predecessor may be claimed exactly once, so:

- A second writer that appends against a stale head is refused by the store, and
  the refusal is translated into `ChainForkError` naming the cause and the
  recovery: reload the chain and append again. The process that would have
  caused the fork is still running and can still be told why.
- A store that already contains a fork fails to open at all, because creating
  the index fails and that failure is reported as a fork rather than a schema
  error. The store is preserved for investigation instead of being extended.
- Sequential writers are unaffected. Constructing a chain after another has
  appended loads the newer head, which is the ordinary path.

PostgreSQL reports the duplicate through its driver rather than sqlite3, so that
backend translates the driver's duplicate-key error into the same exception and
leaves every other database error to propagate unchanged.

## What this does not fix

- **Concurrent appends within one process** are already serialised by the chain
  lock, so this changes nothing there.
- **A writer with store access can still rewrite the entire chain** consistently,
  recomputing every hash, and verification will pass. The index does not address
  that at all. It is the boundary described in `chain-head-custody.md`, and
  external head anchoring is what addresses it, not a constraint.
- **Truncation is still invisible.** Dropping the newest records leaves a
  consistent prefix that verifies. Measured, not assumed: a six-record chain
  truncated to four returns `(True, 'OK')`. External anchoring again, same
  mechanism.
- **The recovery is manual.** A refused writer must be restarted or reloaded by
  whatever supervises it. The software reports the condition; supervising the
  process is an operational responsibility, which is why the single-replica
  refusal in `single-replica-constraint.md` refuses the topology rather than
  hoping this constraint is never reached.

## Why a constraint rather than a check

A check in the append path would only hold while every writer is this code. The
index holds against a writer that bypasses the application entirely, including a
migration script, a second service written against the same table, or a person
at a SQL prompt. The test that pins this asserts the raw-SQL insert is refused,
which is the difference between a guard and a construction.
