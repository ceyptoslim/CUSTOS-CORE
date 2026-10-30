"""Pass trace_id through the gate so proxy mediation produces correlated records."""
from pathlib import Path

p = Path("custos/action_gate.py")
s = p.read_text()

# 1. signature: accept trace_id from callers (proxy, API, tests)
old_sig = """    def evaluate_action(
        self,
        tenant_id: str,
        action: ActionRequest,
        client_id: str = "agent",
    ) -> ActionGateResult:"""
new_sig = """    def evaluate_action(
        self,
        tenant_id: str,
        action: ActionRequest,
        client_id: str = "agent",
        trace_id: Optional[str] = None,
    ) -> ActionGateResult:"""
assert old_sig in s, "signature not found"
s = s.replace(old_sig, new_sig, 1)

# 2. every record() call carries the correlation id through to the chain.
old_rec = """                policy_digest=cited_digest,
                tenant_id=tenant_id,
            )"""
new_rec = """                policy_digest=cited_digest,
                tenant_id=tenant_id,
                trace_id=trace_id,
            )"""
count = s.count(old_rec)
assert count == 3, f"expected 3 record() call sites, found {count}"
s = s.replace(old_rec, new_rec)

p.write_text(s)
print("action_gate.py: trace_id threaded through", count, "record sites")
