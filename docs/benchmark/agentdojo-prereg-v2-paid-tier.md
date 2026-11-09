# AgentDojo pre-registration v2: provider tier

**Status:** committed 2026-11-09, after the first case of the series was scored.
That ordering is disclosed rather than glossed: sitting one ran on the free tier
and recorded one case before the provider refused. The remaining 143 cases were
scored after the tier was verified by the measurement below. This addendum
therefore precedes publication, not all data collection, and a reader comparing
timestamps should find exactly that.

## Why it exists

`agentdojo-prereg-v2.md` was frozen against the free tier and carries the
disclosure that follows from it: on the free tier, submitted prompts and returned
content may be used to improve the provider's products. The series cannot run
there. Twenty requests per day per model, measured at case one, cannot carry a
144-case arm, and a series spread across weeks of daily resets sits exposed to
v2's own model-rotation void.

## How the tier was verified

Not by reading a billing page. A burst of ten consecutive calls was accepted as
evidence once, on the strength of reaching a working endpoint, and it was wrong:
ten does not exceed the provider's own free limit of twenty in a day, so it was
compatible with the account that had just refused. The mistake is recorded here
because it is the trap this verification had to clear.

The test that settles it: exceed twenty calls inside one Pacific day and see
whether call twenty-one is refused. On 2026-11-09, in a Pacific day in which the
same model had refused at call one, twenty-two consecutive calls at four-second
spacing all returned normally, with one `modelVersion` (`gemini-3.6-flash`)
reported throughout. Twenty-two calls cannot come from a twenty-per-day account.

## What this changes, and what it does not

- **Data terms.** On the paid tier the provider states that prompts and responses
  are not used to improve its products. That supersedes the free-tier disclosure
  in v2 for this series, and it is superseded only by the measured behaviour
  above rather than by a claim about the account.
- **Limits.** Tier 1 interactive limits replace the twenty-per-day ceiling. A
  per-minute wall is waited out by the resilience layer; a per-day wall remains
  exit 3, an interruption rather than a void.
- **Nothing else moves.** Arms `A` and `B1`, the case list, the attack, the
  injected text, the model id `gemini-3.6-flash`, thinking budget `0`, the
  `modelVersion` recorder, the metrics and the void rule are unchanged. This
  addendum changes the environment the frozen design runs in, not the design.

## Cost, recorded because the owner paid for it

The prepaid balance was ten dollars, purchased after a trial-type Cloud account
proved unable to pay for Gemini API usage at all. Actual spend for the completed
arm is not asserted here: the provider invoices asynchronously and no figure has
been read back from a billing console. What is established is that the arm ran to
completion on the pinned model.
