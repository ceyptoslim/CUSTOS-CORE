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

## Amendment 4 — 2026-11-19: the tag commit, the wheel digest, and the rehearsal

Appended after `453b7fc0371b`. The text above is unchanged. This amendment records the facts
Amendment 2 deferred: the tag commit, the wheel's digest, and the evidence that the frozen command
resolves and the quickstart runs.

**Tag.** `usability-001` is an annotated tag (object `c124bf516ef813adb2cf5360e7f2540b7284a7c1`)
pointing at commit `fc2f7b1ca2e67e82f75e550c725a8ebef3f44228`, the merge commit of PR 235 on `main`,
which passed all eleven checks. The tag is protected by ruleset 27633926, which blocks deletion and
any update, so this commit cannot be moved under the trial.

**Wheel.** `custos_core-1.4.0-py3-none-any.whl`, built from a fresh clone of that commit, attached to
the release at `usability-001`:

    sha256 b58f32075e2e68f2945f5e61f5576bc69203fd1d442a93e066b18c4a9c17bd1d

Downloaded without any credential, the published asset returns HTTP 302 to storage and the bytes hash
to that same value, so the digest above describes what a stranger actually receives.

**Rehearsal, before the trial tag was applied.** Tag `rehearsal-001` was placed on the same commit and
published as a prerelease with the same wheel bytes. The release-triggered job (run `44612942915`)
resolved the asset through the API, confirmed that this document's command names the asset the release
carries, installed from the published URL, observed the denial, and verified the chain on Ubuntu, macOS
and Windows. All three passed.

**The trial tag's own run.** Publishing `usability-001` (release `451918830`) triggered run
`44613595624` on the same three systems. All three passed, installing from
`https://github.com/ceyptoslim/CUSTOS-CORE/releases/download/usability-001/custos_core-1.4.0-py3-none-any.whl`,
with `records: 2` and `verify: OK`.

**Rehearsal time, disclosed as the clock rule requires.** The mechanical part of the quickstart took
10.0 seconds on the rehearsal run and 13.6 seconds on the trial tag's run, measured from environment
creation to a verified chain. The remainder of the five-minute budget is the human part: reading,
editing a configuration file, restarting Claude Desktop and sending the prompt. The threshold in this
document is unchanged.

**What this does and does not establish.** It establishes that the frozen command resolves for anyone,
that the artifact it fetches is the one digested above, and that the quickstart produces a CUSTOS
denial and a verified chain on all three operating systems. It does not establish that a stranger can
do it in five minutes, and it is not a trial result. No stranger has run this yet.

## Amendment 5 — 2026-11-19: the resolved environment, and `pip freeze` in every transcript

Appended after `fcd3723b3620`. The text above is unchanged.

**The gap.** The wheel pins `mcp==1.30.0` and nothing else. Installing it resolves twenty-nine further
packages by pip's own rules, so two runs a month apart may not be the same environment. Without a
record, a stranger's failure could not be attributed between the wheel and a dependency difference, and
the FAIL verdict this document pre-registers would be ambiguous exactly when it matters.

**The author's environment, recorded.** `docs/benchmark/usability-001-environment.txt`, file digest
`44501ff1659c34e0692319b999fd3e48fa7607c4181b448ac7623c9ae8d71bb2`, produced by installing the published
asset at `usability-001` into a fresh virtual environment on Python 3.11.15 with pip 26.3. It is the
resolved set, not a requirement. pip writes the wheel's own digest into that output, so the record and
the artifact verify each other rather than resting on a header.

**What every participant run now records.** Alongside the OS and Python versions already required,
the transcript includes the output of `python -m pip freeze` from the environment the quickstart
created. It is one command in a terminal the participant is already using, measured here at 0.19
seconds, and it converts a bare failure into an attributable one.

**Clock disclosure.** This adds one command and roughly a fifth of a second to the participant's work.
The five-minute threshold is unchanged, and the clock rule stands: any change to it needs a dated
amendment before the first stranger.

**What this does not establish.** It does not make runs reproducible and it does not pin transitive
dependencies. It makes differences between runs visible, which is all a first-run usability trial can
honestly claim from an environment it does not control.

## Amendment 6 — 2026-11-19: the instrument, fixed before the first stranger

Appended after `d5e70e6944ce`. The text above is unchanged. Amendments 1 to 5 settled the artifact, the
claim and the environment. This one settles the instrument: who is told what, what a transcript may
have removed from it, when the clock starts, and what counts as help. Each of these was a degree of
freedom the author could otherwise have exercised after seeing a result.

**1. Consent and publication, before any run.** Each participant is told, before starting, in writing:
that the trial tests the install path and not them; that a transcript or recording will be committed to
the public repository and pinned in a manifest; that they may withdraw at any point before publication,
in which case the run is reported as withdrawn and excluded from the count rather than counted as a
pass or a fail; and that they are not named unless they ask to be. A run started without that notice is
not a run and is not reported.

**2. Redaction, and what "unedited" means.** The transcript is unedited in substance: no command,
output, error, wait or detour is removed, reordered, summarised or tidied. Before commit, exactly four
things may be replaced with a fixed placeholder: the participant's username, their home directory path,
their hostname, and any credential or token that appears in the output. Each replacement is listed in a
redaction note committed beside the transcript, naming the placeholder and the kind of string it
replaced, never the original. The unredacted transcript is kept by the author and provided to any
reader who asks, unless the participant objects, so the redaction can be checked instead of trusted.

**3. The clock, and who holds it.** The participant holds the clock. It starts when they open this
README's quickstart section and stops when the block is observed in the sense Amendment 2 fixed. Elapsed
time comes from the participant's own terminal history, not from the author's recollection, and the
timestamps of the first and last command are recorded with the run. If a participant cannot produce
timestamps, the run is recorded as `elapsed time not measured` and cannot count as a PASS, because the
five minutes is the claim under test. This changes no threshold, so no clock disclosure is owed here;
the consent notice and the redaction are author-side work and take no time from the participant.

**4. What counts as help.** No help means no substantive answer to any question about the task. Saying
"I cannot answer that during the trial" is not help. Any answer that tells the participant what to type,
where a file belongs, which command to run, or what an error means is help, and makes the run a FAIL.
Reading this repository's code, tests or issues is source reading; reading the README is the task
itself. Whether the author was present during the run is recorded either way.

**5. Who counts as a stranger.** Someone who has not read this repository, has not run CUSTOS, and is
neither the author nor an AI system. Prior use of Claude Desktop is allowed and recorded, because the
trial tests the install path, not the client.

**What this does not change.** The claim, the pass and failure definitions, the pool, the five-minute
threshold and the artifact all stand as written above. These five items constrain the author, not the
participant.
