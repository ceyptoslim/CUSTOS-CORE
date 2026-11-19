# Pre-registration: first-run usability trial 001

Status: PRE-REGISTERED. Committed before any install-path code is written. The stdio transport is
not new: it landed on main at `cb28659` (`custos/mcp_stdio.py`, four tests in
`tests/test_mcp_stdio_smoke.py`), so this trial measures whether a stranger can install and run it,
not whether it gets written. That sentence was corrected at commit time from a draft that said no
stdio-transport code was written; the claim under test is unchanged.

Changes after commit are dated amendments appended at the bottom; the original text is never edited.

## Claim under test
A stranger with Python and an MCP client config can install CUSTOS-CORE with one command and watch a
tool call being blocked, in under five minutes, without reading source code.

## Definitions (fixed now)
- Stranger: has not contributed to the repo, has not seen internal design notes, is not the author,
  and is not an AI agent that helped write the code.
- Install: one command copied verbatim from the README quickstart at tag `usability-001`.
  Command:
  `python3 -m pip install "custos-core[mcp] @ git+https://github.com/ceyptoslim/CUSTOS-CORE@usability-001"`
- Blocked call: the client shows a CUSTOS denial for a tool call not in the allowlist, and the audit
  record shows that decision and the chain verifies.
- Allowed materials: the README quickstart and the CLI help text. Reading source files, the design
  notes, or asking the author counts as needing help.
- Clock: starts when the README is opened, stops when the block is observed and verify succeeds.

## Participants and environments
- Target: 3 strangers minimum, on at least two of: Linux, macOS, Windows (WSL).
  Client: Claude Desktop.
- If fewer than 3 strangers complete the trial, the result is reported as "N=k, inconclusive", not as
  a pass.
- Author and AI self-runs are recorded as smoke tests and do not count toward the result.

## Pass and failure (fixed now)
- Per participant: PASS = block observed in 5 minutes or less with no help and no source reading.
  FAIL = anything else, including a block observed only after 10 minutes (hard stop).
- Overall PASS requires every participant to pass. Any FAIL is a failure of the install path, not a
  caveat about the user. It is fixed and re-tested as trial 002; the result is never reinterpreted.
- Also required in CI before the trial: the README quickstart commands run verbatim in a clean
  container and end in a block. Necessary, not sufficient.

## Evidence recorded for every run
Terminal transcript or screen recording with timestamps, OS and Python versions, client and version,
README tag, elapsed time, whether help was requested, and friction notes. Transcripts are committed
unedited and pinned in a manifest.

## Author predictions (recorded before running)
- Expected: 2 of 3 pass first time.
- Most likely failure points: client config location or format, and Python version mismatch.

## What this trial does not show
Anything about security or bypass resistance. It measures only first-run usability of the stdio
transport with the pinned mcp version `mcp==1.30.0`. It is not a certification.

## Reporting
Results are published whether they pass or fail, with the README tag, commit hash, and raw
transcripts.
