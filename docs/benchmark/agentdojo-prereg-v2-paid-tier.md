# AgentDojo pre-registration v2: provider tier

**Status:** committed before the first scored case. The tier was verified by
measurement, not by reading a billing page: on 2026-11-09 the free tier refused
every call for this model with `GenerateRequestsPerDayPerProjectPerModel-FreeTier`
and `quotaValue: 20`, and after the prepaid balance was funded the same key
answered a burst of ten consecutive calls, plus the calls made earlier in the
same Pacific day, with one `modelVersion` reported throughout. Twenty requests
per day could not have produced that burst.

## What changed since v2 was frozen

`docs/benchmark/agentdojo-prereg-v2.md` was written when the Gemini series was
expected to run on the provider's free tier, and it carries the disclosure that
follows from that: on the free tier, submitted prompts and returned content may
be used to improve the provider's products.

The first live attempt on 2026-11-09 hit the free tier's own ceiling at case one
(`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 20`, retry
delay 12009s). Neither arm can complete a 144-case sitting at twenty requests
per day per model, and a series spread across weeks of daily resets is exposed to
the model-rotation void in v2's own terms. The series therefore moves to a
prepaid paid tier.

## What this addendum records

1. **Tier.** The `google` series runs on the provider's paid tier, funded by a
   prepaid balance, not the free tier.
2. **Data terms.** On the paid tier the provider states that prompts and
   responses are not used to improve its products. The free-tier disclosure in
   v2 is superseded for this series by this paragraph, and it is superseded only
   by observed behaviour: the free tier's twenty-per-day wall no longer refused
   the calls, which is the condition measured in the status block above.
3. **Rate limits.** Tier 1 interactive limits replace the twenty-per-day free
   ceiling. A per-minute 429 is waited out by the resilience layer; a per-day 429
   remains an interruption (`exit 3`), not a void.
4. **Nothing else moves.** Arms (`A`, `B1`), case list, attack, injected text,
   model id `gemini-3.6-flash`, thinking budget `0`, the `modelVersion`
   recorder, metrics and the void rule are unchanged. This addendum changes the
   environment in which the frozen design runs, not the design.

## Commitment

As in v1 and v2: what was measured is what gets reported. A reader of the frozen
record can see from the manifest and the journal that the series ran on one
provider, one model id, one declared role, and one `modelVersion` set. Where this
addendum makes a claim the artifacts cannot show, it says so in those words
rather than presenting the environment as measurement.
