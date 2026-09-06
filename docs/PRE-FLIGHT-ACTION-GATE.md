# Pre-Flight Action Gate (`custos/action_gate.py`, `/v1/evaluate_action`)

**Status:** shipped — module + API endpoint + 32 tests, sabotage-verified.
Extends the shipped output-governance posture with **action** governance:
what an agent PROPOSES TO DO is evaluated **before** the consequential
operation runs.

## The gap this closes

The LORL-9.1 `GovernedExecutor` docstring (shipped since v0.2.0) states the
split explicitly: output governance works for side-effect-free agents;
side-effectful agents need a pre-flight gate that evaluates the proposed
action BEFORE execution. The Nippon v. OpenAI class of failures is a content
failure; the 2026 lab sandbox escapes (OpenAI/Artifactory, Anthropic's three
Claude incidents, Meta/Irregular) were infrastructure failures. **This gate
addresses neither of those directly — it addresses the deployment-level
case between them: an agent inside a workload YOU control trying to take an
action it should not.** A rogue action inside a governed deployment is
denied before it executes.

## Semantics — fail-closed by construction

1. **Unknown tenant → DENY.** No ungoverned evaluation, ever.
2. **Deny-by-default tool allowlist.** A tenant with no registered tools
   denies ALL actions. Tools are enabled explicitly via
   `ActionGate.register_tools(tenant_id, {...})`. Allowlisting a tool means
   exactly "this agent may use this tool" — nothing more.
3. **Dangerous command classes → DENY**, checked before content rules:
   network exfiltration verbs (curl/wget/nc/scp…), destructive filesystem
   ops (rm -rf, mkfs, dd), privilege escalation (sudo/chmod 777),
   package installs (pip/npm/apt — the supply-chain vector that was the
   OpenAI escape path), process tampering (kill -9, systemctl stop),
   credential access (cat .env / id_rsa / .ssh), reverse shells
   (bash -i >& /dev/tcp/), and **oversight-disable attempts** — any attempt
   to disable/bypass/kill CUSTOS, the firewall, the policy engine, or the
   audit chain itself (the guardrail-bypassing-the-guardrail pattern).
4. **Existing content rules compose.** The serialized action (tool +
   command + args) also passes the tenant's full policy engine — prompt
   injection, PII, and every tenant pack rule apply to action payloads.
5. **Every decision is audit-chained** — allow and deny both produce
   tamper-evident records with hashes.

## Usage

```python
from custos.action_gate import ActionGate, ActionRequest
from custos.tenant import TenantManager

tm = TenantManager()
gate = ActionGate(tm)
gate.register_tools("my_pipeline", {"web_search", "file_read"})

result = gate.evaluate_action(
    "my_pipeline", ActionRequest(tool="web_search", command="clerk records 2026")
)
# result.decision.allowed is False on ANY deny; the action must not run.
```

HTTP: `POST /v1/evaluate_action` with
`{"tenant_id": "my_pipeline", "tool": "web_search", "command": "..."}` —
same `EvaluateResponse` shape as `/v1/evaluate`, with `audit_record_hash`.

## Deployment posture (defense-in-depth)

This gate is the **policy layer** of a layered stack. It composes with —
never replaces — the network layer (egress allowlists pointing only at the
CUSTOS endpoint), the runtime layer (gVisor/Firecracker), and OS-level
containment. If the gate is unreachable, the fail-closed semantics already
shipped in LORL-9.1's GovernedExecutor deny execution.

## Does not claim (frozen)

- Does NOT contain infrastructure-level sandbox escapes. Kernel, hypervisor,
  network-isolation, and supply-chain hardening belong to other layers.
  "CUSTOS prevents sandbox escapes" remains a prohibited claim.
- Does NOT make a tool allowlist a sandbox. An explicitly allowlisted tool
  does its own job (an allowlisted `http_fetch` may fetch); the dangerous
  command patterns govern shell-outs and misuse, not the tool's function.
- Zero external deployments today; the first governed workloads are the
  owner's own pipelines (dogfooding).
