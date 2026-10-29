# Sabotage Class `trace-binding` — Pre-Registered Experiment Design

**Status:** FROZEN. This file is hash-pinned in `.github/workflows/ci-red-proof.yml` and verified
with `sha256sum -c` before the class runs. It is written before the first execution of the class and
must not be edited afterwards. Corrections belong in a new design, not an edited one.

**Class id:** `006-weaken-trace-binding`

## What is under test

The claim: the request-correlation identifier is covered by the same integrity evidence as the
record it correlates (EABC `docs/002`, "Intrinsically Bound"), and a record cannot be relabelled to
escape that binding.

The mechanism, in `custos/audit.py::preimage_fields`:

```python
binding_version = _field(record, "binding_version") or 0
if binding_version >= 1:
    fields["binding"] = f"v{binding_version}"
    trace_id = _field(record, "trace_id")
    if trace_id:
        fields["trace_id"] = trace_id
```

Two properties live here. The **marker** (`binding`) makes the version itself tamper-evident, so a
record cannot be downgraded to the legacy preimage to drop its trace identifier. The **identifier**
(`trace_id`) is what makes correlation provable from the artifact instead of merely stored beside it.

## Injected modification class

One deletion, the minimal natural regression: remove the `trace_id` block, **leaving the marker in
place**. This is the refactor that is easy to write and hard to notice — a future contributor tidies
the "unused" field out of the preimage, the marker still says `v1`, and every record still looks
correctly bound.

Deliberately *not* weakened: the marker, the merge of `_field` lookups, the legacy path, the
custody re-walk delegation. One vector, so the observed failure set is interpretable rather than
entangled.

## Expected suite outcome (named in advance)

The suite MUST go RED, and the failing assertions MUST be exactly these two:

1. `tests/test_audit_trace_binding.py::test_mutating_trace_id_breaks_verification`
2. `tests/test_audit_trace_binding.py::test_dropping_trace_id_breaks_verification`

Any additional failure is **observed, not pre-registered**, and is reported as such. Any *missing*
failure from this list means the class did not execute as designed and the run is recorded
**FAULTY-GREEN** regardless of exit code.

## Predicted non-failures (stated before the run)

For transparency, this class is expected to leave these passing, and that is the point:

- `test_relabelling_binding_version_breaks_verification` — the marker survives the weakening, so
  downgrade still breaks the hash. This isolates the identifier from the version marker.
- `test_legacy_record_still_verifies`, `test_mixed_chain_verifies_legacy_then_bound` — the legacy
  path is untouched.
- `test_sqlite_round_trip_preserves_citation_and_binding` — persistence is orthogonal.

## Faulty-green position

If CI reports the suite GREEN under this patch, the finding is: the trace-binding control is
decorative — `trace_id` can sit outside the integrity preimage while every test still passes. That
outcome is worth more than a pass, and it is reported as **FAULTY-GREEN**, not as a failed run.

## Blindness — disclosed, weaker than 003

The same author wrote the implementation (`#72`), the tests, and this design. The pre-registration
therefore constrains *this* run's interpretation but does not substitute for review by someone who
did not write the code. The specific resulting risk: the tests were written to the implementation's
own vocabulary, so they may assert the mechanism rather than the property.

Partial external grounding: the requirement was named by a third party in the EABC specification
(`docs/002`, intrinsic binding), not self-generated. The class tests conformance to a written
external requirement, which is stronger than testing a claim invented alongside its own test.

## What this class does NOT prove

- It does not prove the preimage is complete — only that this one field is bound.
- It does not prove the external re-walk consumes the binding correctly; the custody re-walk
  delegation is covered by unit tests, not by this class.
- It does not prove that a *reviewer* would catch the weakening. CI catches it; the human question
  is separate and unanswered.
