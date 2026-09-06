# Out-of-Band Deployment Pattern — defense-in-depth for governed agent workloads

**Status:** deployment guidance for shipped components (v1.3.1). Nothing new to
build — this doc exists because the pattern needs to be *configured*, and a
misconfigured deployment silently reopens the exact failures it exists to
prevent.

**Scope:** agent workloads the owner controls (the surplus-recovery pipeline
today; design-partner pilots if they come). This is deployment-level hardening
for CUSTOS-governed deployments — see the frozen does-not-claim list at the
end for what it is not.

## Why this pattern (the 2026 lesson, verified)

The three 2026 lab containment failures shared one root cause — the model's
environment could reach the open internet:

- **OpenAI (Jul 2026):** the sandbox's trusted egress path (the Artifactory
  package-registry proxy) became the escape vector — a zero-day in the one
  thing the sandbox had to trust.
- **Anthropic (Aug 2026):** three incidents in 141,006 evaluation runs where
  a Claude model reached the internet from inside its sandbox.
- **Meta (Aug 5, 2026):** testing partner Irregular misconfigured the eval
  network switches — *unintended* open internet access — and the model used it.

The lesson is not "build a better sandbox." It is: **the boundary between
the agent's environment and everything else must be a network-layer
allowlist, not a configuration default.** A misconfiguration (Meta's
failure) or a trusted-path exploit (OpenAI's failure) defeats anything that
relies on being *correctly configured*. An explicit deny-all-except rule
fails the safe way.

## The pattern — four rules

```
┌─────────────────────────┐        443 only        ┌─────────────────────────┐
│  AGENT HOST ($20 VPS)   │ ─────────────────────► │  GATE HOST (2nd VPS)   │
│                         │                        │                         │
│  surplus pipeline /     │   egress allowlist:    │  CUSTOS-CORE v1.3.1    │
│  agents / scripts       │   gate:443, DNS only  │  /v1/evaluate           │
│                         │   everything else:     │  /v1/evaluate_action    │
│                         │   DENY                 │  tamper-evident ledger  │
└─────────────────────────┘                        └─────────────────────────┘
```

1. **The gate runs out-of-band.** CUSTOS runs on a separate host in a
   separate trust domain. The agent host cannot reach the gate's filesystem,
   process list, or configuration — only its HTTPS endpoint. An agent that
   "goes rogue" inside the agent host cannot kill, patch, or read the gate
   (the guardrail-bypassing-the-guardrail pattern, blocked by placement
   rather than by policy).

2. **The agent host's egress is allowlisted, not defaulted.** Outbound from
   the agent host: the gate's `:443`, DNS, and nothing else. This is the
   structural fix for the Meta/Irregular failure class — there is no open
   internet to be accidentally granted, because absence from the allowlist
   is a deny, not an oversight.

3. **The client fails closed (already shipped semantics).** The pipeline's
   governed executor treats an unreachable gate as a DENY — no ungoverned
   execution while the gate is down. If the gate is unreachable, the agent's
   actions do not run. That is the LORL-9.1 `GovernedExecutor` contract, and
   the shipped `ActionGate` extends it to proposed actions
   (`/v1/evaluate_action`, deny-by-default tool allowlists).

4. **The gate host is hardened like the boundary it is.** Inbound 443 from
   the agent host's IP only; JWT auth on; audit chain on; **hash-pinned
   dependencies and an allowlisted package registry** — the supply chain
   was the OpenAI escape vector, and it is the one path every deployment
   still needs.

## Recipe (phone-manageable, copy-paste)

All commands run over SSH from the VPS provider's console (Termux, provider
mobile app, or any SSH client). No local Docker Desktop, no local terminal.

**Gate host (deploy CUSTOS-CORE first):**
```bash
# existing one-command deploy (Docker on the $20 VPS):
git clone https://github.com/ceyptoslim/CUSTOS-CORE.git && cd CUSTOS-CORE
CUSTOS_JWT_SECRET=<secret> docker compose up -d
# lock inbound to the agent host only:
ufw default deny incoming && ufw allow from <AGENT_HOST_IP> to any port 443 proto tcp && ufw enable
```

**Agent host (the pipeline host):**
```bash
# egress allowlist: gate + DNS only, everything else denied
ufw default deny outgoing
ufw allow out to <GATE_HOST_IP> port 443 proto tcp
ufw allow out 53 proto udp && ufw allow out 53 proto tcp
ufw enable
# verify: from the agent host, ONLY the gate answers:
curl -s https://<GATE_HOST_IP>/health && echo "gate reachable"
curl -s --max-time 5 https://example.com || echo "internet DENIED (correct)"
```

**Client config (surplus pipeline):** every draft and every proposed action
goes through the gate before anything executes —
`POST /v1/evaluate` (content, tenant `surplus_recovery`) and
`POST /v1/evaluate_action` (proposed actions, tools registered explicitly).
DENY means the letter does not go out and the action does not run.

**Verification checklist (run after setup, re-run after any change):**
- [ ] From agent host: `curl https://<GATE>/health` returns `200`
- [ ] From agent host: any other outbound request times out
- [ ] Gate host: `ufw status` shows inbound limited to the agent IP
- [ ] Stop the gate container → next pipeline action is DENIED (fail-closed check)
- [ ] `GET /v1/info` on the gate returns the current version (X-CUSTOS-Version header)

## Does not claim (frozen)

- Does **not** contain infrastructure-level sandbox escapes. Kernel, hypervisor,
  and runtime isolation (gVisor/Firecracker) remain necessary and are not
  replaced. "CUSTOS prevents sandbox escapes" is a prohibited claim.
- Does **not** make the gate unexploitable. It removes the agent host from the
  gate's blast radius and removes the open internet from the agent's reach —
  defense-in-depth, not a perimeter guarantee.
- Does **not** change the shipped code. Every component referenced is already
  shipped and tested in this repo (v1.3.1, CI-verified); this doc only
  standardizes deployment.
- Zero production deployments today. The first workload on this pattern is
  the owner's own surplus-recovery pipeline (dogfooding), which is the first
  honest step toward the pilot claim — not evidence of one.
