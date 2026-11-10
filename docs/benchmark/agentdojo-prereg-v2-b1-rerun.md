# AgentDojo pre-registration v2: arm B1, a defective sitting and the run that counts

**Status:** committed before the scored B1 sitting. Arm A is unaffected and its
record stands as merged in `records/arm-a-gemini/`.

## What happened

Arm B1 ran to completion on 2026-11-09 at main `535382b`: 144 of 144 cases,
utility 54, injection success 0, errors 0, one `modelVersion`, pipeline name
`gemini-3.6-flash-custos-B1`. The gate was installed and did its work. Its
evidence was not kept.

`decisions-B1.jsonl` from that sitting is empty. The cause is a defect in the
harness, not in the gate: `GuardedRuntimeElement.query` built the gated runtime,
returned it to the loop, and never held a reference to it. The runner collects
decisions after the case loop by walking the pipeline for a runtime that carries
`record_decisions`, so with no reference to find, it collected nothing. Every
gated arm journals zero decisions for that reason, however many the gate made.

## Why the numbers from that sitting cannot be used

v2 requires per-case decision evidence to attribute an effect to the gate.
Without it, a utility of 54 is a number of unknown cause: the gate refusing
writes is the obvious explanation and is not the only one, and the difference
between those two is precisely what this record exists to keep separate. The
sitting is therefore reported as defective, with its figures stated here and in
the PR that found the defect, and it is not scored.

## Why a rerun is the honest resolution rather than a violation

v2's rule is one scored run per arm, no rerun, no case exclusion. That rule
protects against a run being repeated until a preferred number appears. A sitting
whose decision record was destroyed by a harness defect cannot support a number in
either direction, so repeating it is not a search for a better result; it is the
first sitting capable of being scored.

The disclosure that keeps this honest is on this page: the defective sitting ran,
its figures are 54 of 144, and a reader comparing them to the scored sitting can
see both. Nothing about the defective sitting will be dropped from the account,
and no claim will rest on the difference between the two.

## What changed, and what did not

- The element keeps the proxy it installs, and exposes the decisions it recorded,
  so the runner can collect them. Two guards in `tests/test_agentdojo_element.py`
  fail if either is removed, both proven by reversion before the fix landed.
- Arms, case list, attack, injected text, model id `gemini-3.6-flash`, thinking
  budget `0`, temperature `0`, the `modelVersion` recorder, the metrics and the
  void rule are unchanged. The gate's behaviour is unchanged: it allowed and
  denied exactly as before, and the fix touches only whether its decisions
  survive the walk back out of the pipeline.

## What the scored sitting must show before it is called a result

The decision journal must carry records for every case, the deny count and the
rules that fired must be visible in that file rather than summarised from it, and
the utility figure must be reported beside arm A's 110 of 144 with the arithmetic
that separates the read-only allowlist's structural ceiling from the model's own
behaviour.
