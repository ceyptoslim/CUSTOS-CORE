# The Impossibility Result Is the Design Spec

**Status:** position essay, grounded in cited computability results and this repository's public artifacts.
**Verified:** 2026-10-14 against `main` @ `4b46433` — 494 passing tests, 12 skipped, 89% coverage.

---

## 1. What the mathematics actually says

In 2021, researchers at the Max Planck Institute for Human Development — Alfonseca, Cebrián, Anta, Coviello, Abeliuk, and Rahwan — published *"Superintelligence Cannot be Contained: Lessons from Computability Theory"* in the Journal of Artificial Intelligence Research (DOI 10.1613/jair.1.12202). Their proofs are reductions from the halting problem, and they established three results:

1. A containment algorithm that works by **simulating** the AI and halting it if harm is detected cannot exist: computing the probability that an AI's actions are harmful is incomputable.
2. The containment algorithm's own operations fall into the same undecidable class — there is no guarantee it halts correctly on the cases that matter.
3. Determining whether a system has reached superintelligence is likewise incomputable.

Roman Yampolskiy's earlier work on the AI confinement problem ("Leakproofing the Singularity," 2012) had already argued that deliberately constrained boxes leak over time.

These results are frequently summarized as "AI cannot be controlled." That summary overstates the mathematics. What is *proven* impossible is a specific strategy: **judging the system's mind** — predicting behavior, computing harm probabilities, forecasting the future before it happens.

## 2. What the mathematics does not rule out

Halting-problem arguments attach to predicting the behavior of arbitrary programs. They do not attach to evaluating a fixed, finite rule set against a finite request.

- Regex policy evaluation terminates by construction.
- Rego — the Datalog-based policy language behind this repository's OPA mode — is designed so every query terminates.
- A deny-by-default gate makes no prediction about the requesting system at all. It answers a decidable question: *does this specific request match a deny rule?*

The distinction is not pedantic. When behavioral prediction is provably impossible, the remaining lever is **constraining the action surface before execution** — capability control at the interface, not motivation control inside the model (Bostrom's 2014 taxonomy).

## 3. The design conclusion

This repository is built on that conclusion: **alignment is the model's disposition; governance is the boundary.** The mathematics says the disposition cannot be verified in general. The boundary can be evaluated deterministically — on every request, before any execution occurs, failing closed when in doubt.

This is why the enforcement layer here does not score requests, estimate intent, or predict outcomes. It evaluates rules. The undecidable problems are never attempted; the decidable one is answered on every call.

## 4. A boundary claim must be falsifiable

A deterministic gate that silently degrades into an always-allow is worse than no gate: it manufactures false assurance. This repository therefore treats "the boundary works" as an empirical claim that must be re-established continuously:

- The red-proof workflow (`ci-red-proof.yml`) injects known-bad regressions — weakened admin auth, inverted deny verdicts — and **fails** if the test suite stays green on them. A green suite that cannot fail proves nothing.
- Every run produces sealed evidence records: identity, time, observations kept structurally separate from the verdict, a versioned rule mapping observations to verdict, and provenance (record spec v3).
- Observation sets of documented runs are committed in-repo (`docs/red-proof-records/`), so the evidence outlives CI artifact retention.
- An independent reconstruction by FactNotebook (Governance Falsifiability Infrastructure, Etoua 2026, Zenodo DOI 10.5281/zenodo.20709011) established what those records support and what they cannot, as a before/after pair spanning the v2 and v3 record specs. A credited worked example is forthcoming.

## 5. Honest limits

Three things this essay does not claim:

1. **This is not containment, and not alignment.** CUSTOS-CORE does not constrain any system's goals. It constrains what an agent may execute through a governed interface. Yampolskiy's leakproofing arguments — social engineering, side channels, human operators inside the boundary — apply to every gate, including this one.
2. **Nothing here speaks to superintelligence.** The honest scope is today's autonomous agents on today's infrastructure. The Max Planck results explain why the architecture refuses to predict; they do not bless any boundary against an adversary that outclasses it.
3. **A green suite is a snapshot, not a guarantee.** The evidence discipline exists precisely because every claim in this repository is falsifiable — including this essay.

---

## References

- Alfonseca, M., Cebrián, M., Anta, A. F., Coviello, L., Abeliuk, A., & Rahwan, I. (2021). Superintelligence Cannot be Contained: Lessons from Computability Theory. *Journal of Artificial Intelligence Research*, 70, 65–76. DOI 10.1613/jair.1.12202
- Yampolskiy, R. V. (2012). Leakproofing the Singularity: Artificial Intelligence Confinement Problem. *Journal of Consciousness Studies*.
- Bostrom, N. (2014). *Superintelligence: Paths, Dangers, Strategies.* Oxford University Press.
- Etoua, P. J. (2026). Evidence Attributes as the Foundation of Governance Falsifiability. Zenodo DOI 10.5281/zenodo.20709011
