# Out-of-band deployment: capture kit

Purpose: turn the recipe in `docs/OUT-OF-BAND-DEPLOYMENT.md` from a plan into a dated,
self-verifying record. That document's frozen claims list says "zero production
deployments today". This kit is how that sentence gets retired honestly, with a
transcript rather than an assertion.

Two files:

- `capture.sh`, run once on each host, writes a timestamped transcript and exits
  non-zero if any expectation fails.
- `verify.py`, run by anyone afterwards, recomputes the transcript's self-hash so a
  reader does not have to trust the file's own verdict.

## Run it

The pipeline form needs no copy step, which is the practical one from a phone. On the
gate host, with `capture.sh` in the current directory:

```
ssh root@<GATE_HOST_IP> 'sh -s gate <GATE_HOST_IP>' < capture.sh
```

On the agent host, passing the gate's address as the third argument:

```
ssh root@<AGENT_HOST_IP> 'sh -s agent <GATE_HOST_IP>' < capture.sh
```

Or copy first and run from the host:

```
scp capture.sh root@<GATE_HOST_IP>:/root/
ssh root@<GATE_HOST_IP> 'sh /root/capture.sh gate <GATE_HOST_IP>'
```

The transcript lands in the working directory of the process, as
`out-of-band-<UTC>-<role>.txt`. Each run prints `FILE:` and `RESULT:` lines. Copy both
files back, then:

```
python3 verify.py out-of-band-<UTC>-gate.txt
python3 verify.py out-of-band-<UTC>-agent.txt
```

Both must print `RESULT: MATCH`.

## What it checks, and what it refuses to claim

Gate host: firewall state, the gate answering its own health endpoint, containers up.

Agent host: the gate answers, and the open internet does not. The second is the check
that matters, because a reachable internet from the agent host reopens the 2026
failure class this pattern exists to remove. The script treats a *successful* request
to example.com as a failure, not a pass.

Neither transcript is evidence that the pattern is complete. It is evidence that these
specific checks held at the stated time on the stated host, which is a narrower and
defensible claim.

## Why the hash covers the verdict

The transcript states the sha256 of everything above the `## Self-hash` marker, and
the `RESULT:` line is written before that marker, so the verdict is inside the hashed
span. An earlier version hashed the file before writing the verdict, which left the
one line a reader most needs to trust outside the hash: editing "at least one
expectation did NOT hold" into "all expectations held" still verified. That was found
by tampering with the kit's own output and is now pinned in the layout.

## The one step that stays manual

The fail-closed check, stopping the gate and confirming the next action is refused, is
printed as instructions rather than run, because stopping the gate from a script that
is writing to that host can leave the box half-configured. Paste its exact output into
the record by hand, or run it in a second SSH session and screen-capture.

## Turning transcripts into a repo record

Once both verified transcripts exist, the record is a short Markdown file under
`docs/out-of-band-deployments/` containing: the two filenames, both sha256 values, the
host roles, the UTC stamps, the `RESULT:` lines verbatim, the manual fail-closed
output, and one sentence stating what the record does not establish. Attach the raw
transcripts beside it unchanged.

That file is what allows the frozen claim to change from "zero production deployments"
to "one dogfooding deployment, dated and re-verifiable", which is the first honest step
toward the pilot claim and explicitly not evidence of one.
