# UAT protocol for the pilot

Status: pilot-entry artifact. User acceptance testing is a property of the pilot
rather than a precondition of it, because the pilot is the only available source
of non-maintainer users, and a precondition that requires the pilot's own output
cannot be met by the party being conditioned. This document is the entry condition:
the protocol exists before the pilot, and executing it is an exit condition.

The purpose is evidence, and a pilot that reports no defects has failed this
protocol rather than passed it.

## Participant profile

At least one policy author who is not the maintainer and who owns a policy about
real work. The participant must be able to state a rule in the policy language and
say what outcome they expected; a developer is not required and not preferred,
because the operability question is whether a policy author can work without one.

Excluded: anyone with write access to the repository, anyone in a compensating
relationship with the maintainer, and the maintainer themselves. A maintainer
re-run is a regression test, not a participant session, and is recorded as such.

## Environment

Single tenant, non-regulated data, PostgreSQL audit backend, a pinned commit
recorded with its `X-CUSTOS-Version` value. Anything the participant used that was
not the documented path gets recorded, because a workaround is a finding.

## Task list

Each task has an expected outcome and an evidence artifact. The participant
attempts all of them unaided first; the maintainer may assist only after a
failure is recorded, and every assisted task is counted.

1. Deny a specific tool for a tenant, then show the denial happening.
2. Allow a second tool, configured so that the decision is recorded rather than
   silent, and show the record it produced.
3. Compare the two records and say which fields carry the decision and which
   carry the evidence for it.
4. Starting only from the action they just attempted, locate its record.
5. Verify the hash chain and say what the verification actually checked.
6. Modify a stored record, then show that verification now fails. The participant
   performs the tamper, not the maintainer.
7. Restart the service and verify the chain again.
8. In their own words, state what the record shows and what it does not.

Task four and task eight are the ones that predict whether the software is
operable by someone else. Task eight is quoted verbatim in the report, because a
participant's account of the limit is better evidence than the maintainer's.

## Defect intake

Every defect carries: task number, timestamp, what was expected, what happened,
the artifact (record hash, command output, or screenshot), and the participant's
words unedited. Defects are entered by the participant or by the maintainer
transcribing verbatim, and the transcription is read back for confirmation before
it is filed.

A disagreement about whether something is a defect is itself recorded. The
maintainer does not resolve it by reclassifying.

## Severity taxonomy

- **S1, control failure.** A task fails and the gate behaved wrongly: an action
  proceeded when the policy denied it, a decision left no record, verification
  passed on a modified chain, or the service failed open. S1 blocks pilot exit.
- **S2, task blocked without a control failure.** The gate behaved correctly and
  the participant still could not complete the task: unusable error, missing
  documentation, required a developer. S2 requires a decision before exit, either
  a fix or a documented workaround the participant confirms is workable.
- **S3, wrong or misleading statement.** Documentation or a message asserts
  something the software does not do. The claim is corrected or withdrawn.
- **S4, friction.** Preference, wording, ergonomics. Logged, no commitment.

Anything the participant expected the software to do and it does not do is a
defect for intake purposes even where the answer is that the expectation was
outside scope. Out-of-scope is a resolution, not an intake filter.

## Closure definition

A defect closes when the reporter confirms it, not when the maintainer asserts it.
For S1 the closure evidence is a re-run of the failed task with its artifact. For
S2 it is either the re-run or the participant's written acceptance of the
workaround. For S3 it is the corrected text with the commit that carries it. For
S4 there is no closure, only a log entry that survives the pilot.

## Metrics reported

Counts of tasks attempted and completed, defects by severity, assisted tasks,
time to a first working deny rule, and time to locate a record. No satisfaction
score and no rating scale: a preference number is not evidence about a control,
and including one invites the report to be read as a verdict.

## Reporting, including the negative case

The report goes to the participant and to whoever commissioned the review, with
defects verbatim and the artifacts attached. If the pilot finds nothing, the
report says the protocol was executed and found nothing, names the tasks, and does
not describe that as validation. A negative result about coverage, such as a route
that reaches the effect without the gate, is reported in the same voice as a
positive one, because the pilot's product is a record of what was observed.
