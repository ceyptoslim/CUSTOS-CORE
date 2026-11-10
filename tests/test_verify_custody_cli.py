"""Guards for scripts/verify_custody.py — the operator-facing verifier.

The point of these tests is the exit code, because that is what a reviewer
scripts against: a truncated store must not exit 0 no matter how clean the
remaining chain is.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from custos.audit import AuditChain
from custos.custody import AnchorManager, MemorySink

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "verify_custody.py",
)


def _chain(n: int = 6) -> AuditChain:
    chain = AuditChain()
    for i in range(n):
        chain.record(
            client_id="default",
            action="allow",
            reason=f"decision {i}",
            content=f"content {i}",
        )
    return chain


def _anchors(chain: AuditChain) -> list:
    sink = MemorySink()
    mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
    mgr.anchor_due()
    return [a.to_dict() for a in sink.anchors]


def _run(records: list, anchors: list) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        rpath = os.path.join(tmp, "records.json")
        apath = os.path.join(tmp, "anchors.json")
        with open(rpath, "w", encoding="utf-8") as fh:
            json.dump({"records": records}, fh)
        with open(apath, "w", encoding="utf-8") as fh:
            json.dump({"anchors": anchors}, fh)
        return subprocess.run(
            [sys.executable, SCRIPT, "--records", rpath, "--anchors", apath],
            capture_output=True,
            text=True,
        )


class TestExitCodes:
    def test_clean_store_establishes_and_exits_zero(self):
        chain = _chain(6)
        proc = _run(chain.get_records(), _anchors(chain))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "ESTABLISHED" in proc.stdout

    def test_truncated_tail_exits_two_and_names_truncation(self):
        chain = _chain(6)
        anchors = _anchors(chain)
        proc = _run(chain.get_records()[:4], anchors)
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "CONTRADICTION" in proc.stdout
        assert "truncation" in proc.stdout.lower()

    def test_no_anchors_cannot_establish_and_exits_one(self):
        chain = _chain(3)
        proc = _run(chain.get_records(), [])
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "CANNOT ESTABLISH" in proc.stdout


class TestInputShapes:
    def test_bare_list_files_are_accepted(self):
        chain = _chain(4)
        anchors = _anchors(chain)
        with tempfile.TemporaryDirectory() as tmp:
            rpath = os.path.join(tmp, "r.json")
            apath = os.path.join(tmp, "a.json")
            with open(rpath, "w", encoding="utf-8") as fh:
                json.dump(chain.get_records(), fh)
            with open(apath, "w", encoding="utf-8") as fh:
                json.dump(anchors, fh)
            proc = subprocess.run(
                [sys.executable, SCRIPT, "--records", rpath, "--anchors", apath,
                 "--json"],
                capture_output=True,
                text=True,
            )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        payload = json.loads(proc.stdout[: proc.stdout.rindex("}") + 1])
        assert payload["overall"] == "ESTABLISHED"
