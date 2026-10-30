"""What a timed-out decision leaves behind.

A timeout denies without forwarding, which is correct. It does not produce a
citable record: the proxy returns no record hash, and whether a record lands at
all depends on where the gate was cancelled. These tests pin that behaviour so a
later change to it is deliberate rather than accidental.
"""
import asyncio

from custos.mcp_proxy import GateVerdict, McpProxy


class SlowGate:
    """Accepts, optionally writing a record first, then outlives the timeout."""

    def __init__(self, write_after=None):
        self.records = []
        self._write_after = write_after

    async def evaluate(self, *, tenant_id, tool, arguments, trace_id):
        if self._write_after is not None:
            await asyncio.sleep(self._write_after)
            self.records.append(trace_id)
        await asyncio.sleep(0.3)
        return GateVerdict(allowed=True, record_hash="abc123", rule=None, reason="ok")


def _run(write_after):
    gate = SlowGate(write_after)
    proxy = McpProxy(gate, tenant_id="t", timeout_seconds=0.05)
    forwarded = []

    async def scenario():
        async def forward(name, args):
            forwarded.append(name)

        outcome = await proxy.call_tool("delete_file", {}, forward)
        await asyncio.sleep(0.25)
        return outcome

    outcome = asyncio.run(scenario())
    return outcome, forwarded, gate.records


def test_timeout_denies_without_forwarding():
    outcome, forwarded, _ = _run(None)
    assert outcome.forwarded is False
    assert forwarded == []
    assert outcome.rule == "mcp_proxy_gate_timeout"


def test_timeout_carries_no_record_hash_even_when_a_record_lands():
    outcome, _, records = _run(0.02)
    assert records, "precondition: the gate wrote a record before the timeout"
    assert outcome.record_hash is None, \
        "a timed-out decision must not claim a record it cannot prove is its own"


def test_timeout_can_leave_no_record_at_all():
    outcome, _, records = _run(None)
    assert records == []
    assert outcome.record_hash is None
