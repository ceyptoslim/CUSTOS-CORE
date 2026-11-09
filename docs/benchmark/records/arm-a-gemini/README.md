# AgentDojo arm A, Gemini series: frozen record

One run of arm A (`A`, no gate), as the v2 pre-registration requires: one run per
arm, no rerun, no case exclusion. Started 2026-11-09, finished
2026-11-09T22:08:02.058420+00:00.

## What it measured

| Quantity | Value |
|---|---|
| Cases | 144 of 144 |
| Utility | 110/144 (76.4 percent) |
| Injection success | 0/144 |
| Errors | 0 |
| Provider interruptions | 4 (503 high demand from the provider, retried, none scored as a case outcome) |
| Model | `gemini-3.6-flash` |
| Model versions seen | gemini-3.6-flash |
| Attack | `important_instructions`, declaring the injected text names the model "AI model developed by Google" |
| Temperature / thinking budget | 0.0 / 0 |
| Provider / prereg | `google` / `b9d4312` |
| Journal digest | `af8f7313c6857f3e710ce30ca2a9b4ced8374272b4c697684ef236818f888209` |

## The zero, and why it is not a result about the gate

Arm A has no gate. Its injection-success count is therefore the floor against
which the gated arms would be compared, and it came back at zero. Before reading
that as resistance, the harness was checked: the injected jailbreak text is
present in the model's message stream in **144 of 144** case logs, so the
attack was delivered in every case rather than silently dropped.

A second check was run outside this record, and its logs are kept in
`diagnostic-direct-attack/` so the claim can be re-read rather than trusted: the
`direct` attack, which states the goal in plain text with no jailbreak framing,
against `user_task_0` and all nine injection tasks, returned security False in
9 of 9. The diagnostic is not part of the arm
and is not scored into any figure above.

What the series can therefore say: within this harness, at temperature 0 and
thinking budget 0, `important_instructions` did not succeed against
`gemini-3.6-flash`. What it cannot say: that a control prevented injection. A floor
of zero also means arms B1 and B2 have nothing to reduce, so the v2 prediction
that a gated arm sits near arm A on utility while sitting near zero on injection
cannot be discriminated on this model. That consequence is stated here rather
than discovered by a reader.

## Files

`results-A.json`, `decisions-A.jsonl`, `journal-A.jsonl` and `manifest-A.json` are
the runner's own outputs. `logs/` holds the per-case conversation records the
provider actually returned. `SHA256SUMS` covers every file so a third party can
re-hash rather than trust: 157 entries, generated after the run and not touched
since, apart from the `SHA256SUMS` line itself which cannot contain its own
digest.

## What this record does not establish

That the result generalises to any other model, provider, attack, case list or
deployment. Arm A is one ungated baseline on one pinned model. Nothing here is a
certification, a validation or an endorsement, and no claim of prevention is made
or implied.
