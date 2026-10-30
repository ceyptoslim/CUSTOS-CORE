# Exit-class profile template

A template for writing an **implementation profile** against EABC v1 that declares, per failure mode,
what an implementation demonstrates, what it leaves open, and what it rules out by construction.

It exists because a status vocabulary without a required shape degrades into adjectives. The shape
below is taken from the register that produced it
([`EABC-EXIT-CLASS-REGISTER.md`](EABC-EXIT-CLASS-REGISTER.md)) and is offered implementation-neutral:
nothing in this document is about one system, and nothing in it creates an EABC property, an EABC
requirement, or a conformance level.

**This template is not an assessment.** It says what a profile must declare. It does not say whether
any particular declaration is true.

---

## Part A — Profile-level declarations

A profile begins with these, in this order. Each is a single statement; a profile that leaves one out
is not comparable with another profile, because a reader cannot tell what is being claimed.

| Declaration | What it must say | Invalid if |
|---|---|---|
| Implementation | Name and the commit or version the profile describes | It describes "the project" without a pin |
| EABC version | The version this profile is written against | It names a version it has not read |
| Profile version | This document's own version | It is absent, so a reader cannot tell if it is current |
| Scope | Which portion of the system the profile speaks for, and which portion it does not | It implies the whole system while analysing one component |
| Execution boundary | Where the decision is made, in one sentence, in terms of a mechanism rather than an intention | It says "before execution" without saying what observes the boundary |
| Evidence carrier | What object holds the decision record, and what binds the record to the decision | It names a log without saying what a reader can check |
| Status vocabulary | The three statuses this profile adopts, with the limits on each (Part B.4) | It invents a fourth word without defining it |
| Exclusions | Classes the implementation does not speak to, stated as such | Exclusions are left implicit |
| Attribution | The author, and the statement that findings belong to the author | The profile reads as endorsed by the specification's authors |

## Part B — Per-class requirements

The four classes below are a **starting set, not a mandatory canon.** An implementation may rename
them to fit its vocabulary, add classes, or declare a class inapplicable, subject to Part C.

For each class, all six fields are required and none may be empty. An empty field is a declaration
that the author has not examined the class, which is different from examining it and finding it
closed.

### B.1 What each class claims

- **Suppression** — a decision exists but no durable evidence of it does.
- **Substitution** — the effect performed is not the effect the decision governed.
- **Attribution** — the party whose evidence is trusted is the party that set the rule.
- **Coverage** — an effect-producing path never reaches the decision point.

### B.2 The six fields

| Field | Prompt to answer | Common failure |
|---|---|---|
| **Boundary** | "For every ___, exactly one ___ exists, and ___ carries it." | Prose about intent instead of a universal statement |
| **Failure mode** | One sentence: "an effect occurs that ___." | A description of a mitigation rather than a failure |
| **Declared status** | One of the three words, with the half that is closed and the half that is open named separately | One word covering two different claims |
| **Threat model assumed** | What is in scope, and what is explicitly out, with the reason | Unstated scope, so a reader supplies their own |
| **Artifact** | A path a stranger can open, and what it shows about this class | A test name with no output, or a document describing the test |
| **Falsification condition** | The observation that would make the closure claim false | A condition that cannot be observed |

### B.3 Boundary, worked

Two boundary statements, one usable and one not:

> *Not usable:* "All agent actions are mediated before execution."

> *Usable:* "For every decision the decision point returns, exactly one record is appended before the
> result is returned, and the result carries that record's hash, so the decision and its evidence are
> the same object rather than two events that ought to line up."

The second can be falsified by a code path or a run. It also states the half that is closed
(in-process) separately from the half that is not (across the storage boundary), which the first
elides.

### B.4 Status semantics

Three words, and each says what it may **not** claim:

- **`demonstrated-closed`** — closure is supported by an artifact within an explicitly stated boundary
  and threat model. It does **not** mean the class is closed everywhere, and it does **not** mean the
  implementation conforms to EABC. The claim is exactly as wide as the artifact and the threat model.
- **`declared-open`** — an acknowledged gap. The class is not closed, the limitation is visible to a
  reader, and the same row states what would close it.
- **`out-of-scope-by-construction`** — requires an architectural argument and a falsification
  condition for the declaration itself (Part C.3). The absence of a test is not an argument, and this
  label is where a missing test would go to hide.

A single status may describe a class that is half closed and half open. When it does, the profile must
say which half is which, because a reader will otherwise assume the wider claim.

## Part C — Rules the shape enforces

### C.1 Adding a class

1. Name the failure mode in one sentence of the form "an effect occurs that ___".
2. Show distinctness: no existing class covers it, and the nearest class does not either.
3. Name the EABC property it implicates, and state why that property's own vocabulary cannot express
   the failure without losing information.
4. State the artifact and the falsification condition for a closure claim.
5. Change the class list, the mapping, and whatever checks the profile's shape in one commit. A class
   present in one place and absent from another is a documentation defect.

### C.2 No aggregation

A profile reports scoped claims and their evidence. It does not sum them. No row, and no combination
of rows, establishes conformance; conformance remains a separate judgment against the applicable
properties, evidence model, threat model and required evidence. A reader who counts closure claims has
computed something the profile does not assert.

### C.3 What "out of scope by construction" requires

The label is the most easily abused, because "we did not test it" and "a test cannot change this" look
identical from outside. An architectural argument is required, and it must be a *constraint* that runs
in the opposite direction from a test:

- The constraint: what structural fact makes closure impossible without damaging another property.
- The falsification condition for the declaration itself: what would show the author was mistaken
  rather than merely convenient.

A profile that cannot state both must use `declared-open` instead. That is not a demotion; it is the
accurate word.

### C.4 Artifacts

An artifact must be inspectable by someone who does not trust the author: a path, a run record, a
published output. A test that exists but whose output nobody can read is a description of evidence,
not evidence. Where an artifact is produced within the same repository by the same author, the profile
should say so, and say what a third party could re-derive independently.

## Part D — Review checklist

For a third party reading a completed profile, in order:

1. Is the implementation pinned to a version?
2. Does the scope match what the profile actually analyses?
3. Is every status one of the three words, with the closed half and open half distinguishable?
4. Does every `demonstrated-closed` cite an artifact that is openable and shows what the boundary
   claims?
5. Is every threat model both stated and bounded, or does it silently expand to "everything"?
6. Does every `out-of-scope-by-construction` carry a constraint and a falsification condition for the
   declaration itself?
7. Does anything in the profile aggregate statuses into a conformance statement?
8. Is the attribution boundary explicit, so findings read as the author's?

A profile that fails 3, 6 or 7 has not been written in this vocabulary, whatever words it uses.

## What this template deliberately leaves open

The number of classes. The names of the classes. Document length, section order beyond Part A, and
whether the profile lives inside the implementation's repository or beside the specification.

Comparability is the goal, not uniformity. Two profiles that declare the same eight things in
different words can be read side by side; two that use the same headings to make different claims
cannot.
