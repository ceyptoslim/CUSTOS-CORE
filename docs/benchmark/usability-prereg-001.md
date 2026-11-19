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

## Amendment 1 — 2026-11-19: the install command, its preconditions, and tag discipline

Appended after commit `de5f551b037d`. The text above is unchanged, as the status line requires. No
stranger has run this trial and tag `usability-001` does not exist, so no result is affected; this
amendment defines what the trial measures.

**1. The install command is replaced.** The Install line above fetches a `git+https` URL, which needs
git on the machine. On a fresh Mac the first `git` invocation can trigger a developer-tools download
that takes minutes, and that download would spend the five-minute budget on something the install
path does not control. The command is now:

`python3 -m pip install "custos-core[mcp] @ https://github.com/ceyptoslim/CUSTOS-CORE/releases/download/usability-001/custos_core-0.1.0-py3-none-any.whl"`

This fetches a wheel attached to the release at the tag, over HTTPS, and needs no git. It freezes two
further implementation obligations: a `custos-core` wheel at version `0.1.0` attached to the release
at `usability-001`, and an `mcp` extra pinning `mcp==1.30.0`.

**2. Install preconditions.** Python 3.10 or newer with a working `pip`, and no `mcp` 2.x already
installed. An environment carrying 2.x meets the pin as a conflict: it is recorded and reported as an
exclusion, not counted as a pass or as a fail, and three completed participants are still required for
any result.

**3. Tag discipline.** `usability-001` is created only at a commit whose README carries the command
above verbatim, with the CI quickstart run green on that exact commit. The commit it points at is
recorded in Amendment 2 before any stranger runs. Tags matching `usability-*` are protected against
moving and deletion in the repository settings, and the tag is never moved; a correction after it
starts trial 002, not a retry of this one.

**4. Scope of the pin.** Nothing here shows anything about `mcp` 2.x. The pin is the 1.x line, which
PyPI still publishes as a maintenance line while 2.x is the current stable release and
`pip install mcp` installs 2.x. Whether the core supports 2.x is undecided by this trial and is a
decision to take after it, since new agent builders will mostly be on 2.x. A 2.x trial would be trial
002 or later, with its own pre-registration.

## Amendment 2 — 2026-11-19: the claim, the pool, the client step, and the clock

Appended after commit `c1d4cb6e805e`. The text above is unchanged. This amendment records decisions
only. The tag commit and the wheel hashes are not decisions and do not exist yet, so they go in
Amendment 3; a document that named them now would be asserting facts it does not have.

**1. The claim is amended: "one command" becomes the quickstart block.** The original claim says a
stranger installs "with one command". A virtual environment is required, because a bare
`python3 -m pip install` is not reliable for a stranger: on Windows `python3` is often a Store stub,
on a fresh Mac it can trigger a developer-tools download, and Homebrew and Debian Pythons refuse it as
an externally managed environment. Creating the environment and installing into it is two commands at
minimum, and a per-OS one-liner would make the trial measure shell quoting. The amended claim is:

> A stranger on macOS or Windows with Python and Claude Desktop can copy the README quickstart
> verbatim (create a virtual environment, install the wheel, print the client config, paste it into
> Claude Desktop), send one prompt, and see a CUSTOS denial, in under five minutes, without reading
> source code.

This loosens the claim and is recorded as a loosening. It is permitted only because no stranger has
run and tag `usability-001` does not exist.

**2. The pool is macOS and Windows.** Claude Desktop is Anthropic's native application for macOS and
Windows, with no official Linux build, so "at least two of Linux, macOS, Windows (WSL)" is replaced.
Participants must cover both operating systems, minimum three participants.

**3. "Blocked call" is defined so that a participant can check it.** The original definition required
the audit record to show the decision and the chain to verify. With only an in-memory chain nothing
survives the call for a stranger to inspect, so zero-config mode must satisfy all three:

- The audit chain persists to a SQLite file at a fixed location under the participant's home
  directory, used when no database is configured, and its path is printed by the config command and
  named in the quickstart.
- The wheel ships a `verify` command that checks the persisted chain and reports its record count and
  head, and the quickstart includes it.
- A block counts only when both hold: the participant sees a CUSTOS denial in the tool result, and
  `verify` succeeds over a chain that contains the denial.

Both are inside the clock.

**4. "Block observed" is defined, with a fixed prompt.** The model may paraphrase a denial. A block
counts when the participant sees a CUSTOS denial in the tool result, or the reply states the call was
blocked; a paraphrase that names no denial does not count. The quickstart supplies the exact prompt to
send, so no part of the clock goes to deciding what to ask.

**5. The config step is emitted, not hand-merged.** Hand-merging JSON into an existing
`claude_desktop_config.json` is a common failure. The config command prints a complete block produced
by `json.dumps`, so Windows backslashes survive escaping, together with the config file path for the
participant's operating system. The README gives both cases: a new empty file, and an existing file
that already lists servers.

**6. The clock rule is fixed before the rehearsal.** Five minutes must cover creating the environment,
installing, editing the config, restarting Claude Desktop, one prompt and a verify. That is tight, and
adjusting the threshold after seeing a rehearsal time would be a degree of freedom. So the rule is
fixed here: the threshold may change only by dated amendment, before the first stranger runs, and the
amendment must disclose the rehearsal time that prompted it. Author runs are smoke tests and do not
count toward the result.

**7. CI and a rehearsal precede the one-shot tag.** CI runs the install path on Ubuntu, macOS and
Windows runners: install the exact wheel into a fresh environment, launch the stdio server, drive it
with a scripted MCP client, and assert both a denied call and a verified chain. Ubuntu is included
although Claude Desktop is not: it proves the install path, not the GUI step, which no runner covers.
The whole flow (wheel build, release, release-triggered quickstart job) is rehearsed first under the
unprotected name `rehearsal-001`. `usability-001` is created only after a clean rehearsal, from the
exact artifact the pull request produced, with its SHA-256 compared before publication.

**8. Recruiting.** Participants are recruited from outside the project. If fewer than three complete,
the result is "N=k, inconclusive", which is a statement about recruitment, not about the install path.

**9. Disclosure of a branch force-push.** After this document first merged, an amended commit was
force-pushed to the branch of its own pull request, PR 228, which had already merged. Main was never
affected, the branch was deleted, and the orphaned commit `38e984124d41` is not on main.
Non-fast-forward pushes are now blocked on all branches by ruleset 27634417, so the rule is enforced
rather than remembered.

## Amendment 3 — 2026-11-19: the wheel filename, corrected

Appended after `cea1e729e917`. The text above is unchanged, and this amendment supersedes it on one
point only: the wheel filename.

Amendment 1 froze `custos_core-0.1.0-py3-none-any.whl`. That was wrong when I wrote it. The package
reports `custos.__version__ = "1.4.0"`, and `/v1/info` reports the same, so a `0.1.0` distribution
would carry `1.4.0` code and put two version numbers on one artifact. The distribution version is
read from `custos.__version__` rather than chosen, so the frozen filename becomes:

`custos_core-1.4.0-py3-none-any.whl`

and the frozen command becomes:

`python3 -m pip install "custos-core[mcp] @ https://github.com/ceyptoslim/CUSTOS-CORE/releases/download/usability-001/custos_core-1.4.0-py3-none-any.whl"`

The filename is derived, not decided. If `custos.__version__` moves before the tag, the filename
moves with it and a further dated amendment records the final name. A reader should not treat this
amendment as fixing the number for all time; it records that the number follows the code.

Still deferred: the tag commit, the wheel's SHA-256 and the final filename, because none of them
exist yet. They are recorded in the amendment that follows the tag, as Amendment 2 established.
