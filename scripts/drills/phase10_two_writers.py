"""Phase 10: two replicas, one store, both booted before either writes.

The staggering is the condition, not a weakening of it: two processes that load
the same head and then both append is the topology the single-replica constraint
refuses when it is declared, and the case a rollout meets when a replacement pod
boots while another is still starting.

    DATABASE_URL=postgresql://user:pass@host:port/db \\
      python3 scripts/drills/phase10_two_writers.py

Pass condition: exactly one append succeeds, the other is refused at the store
with ChainForkError, the refused writer keeps no record in memory, and a fresh
process verifies the store green.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
WORKERS = ("A", "B")


def spawn(name: str, barrier: Path, env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(HERE / "phase10_worker.py"), name],
        cwd=str(ROOT),
        env={**env, "DRILL_BARRIER": str(barrier)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is required: this phase needs a store two processes can share")
        return 2

    env = dict(os.environ)
    env.setdefault("CUSTOS_ENV", "production")
    env.setdefault("CUSTOS_JWT_SECRET", secrets.token_hex(32))

    with tempfile.TemporaryDirectory(prefix="drill-barrier-") as tmp:
        barrier = Path(tmp)
        # Warm the store first so both replicas can boot: two cold starts against
        # an empty database race in schema creation (issue 131), and that failure
        # arriving here would be mistaken for the fork guard working.
        warm = spawn("W", barrier, {**env, "DRILL_WARMUP": "1"})
        warm.communicate(timeout=90)
        procs = {name: spawn(name, barrier, env) for name in WORKERS}

        # Both ready means both have loaded the head. Only then does anyone write.
        deadline = time.time() + 60
        while time.time() < deadline:
            if len(list(barrier.glob("ready-*"))) >= len(WORKERS):
                break
            time.sleep(0.05)
        for name in WORKERS:
            marker = next(barrier.glob(f"ready-{name}-*"), None)
            if marker:
                (barrier / marker.name.replace("ready-", "go-")).write_text("1")

        outs = {}
        for name, proc in procs.items():
            out, err = proc.communicate(timeout=90)
            outs[name] = out
            if err.strip():
                print(f"{name} stderr (tail): {err.strip().splitlines()[-1][:160]}")

    for name in WORKERS:
        for line in outs[name].splitlines():
            if line.startswith("RESULT"):
                print(line)

    accepted = sum(1 for name in WORKERS if f"{name} append: 200" in outs[name])
    refused = [name for name in WORKERS if "append refused" in outs[name]]
    phantom = [
        name for name in WORKERS if "append refused" in outs[name] and f"{name} in-process chain length after: 1" in outs[name]
    ]
    print(f"RESULT appends accepted: {accepted} of {len(WORKERS)}")
    print(f"RESULT refused writers: {refused}")
    print(f"RESULT refused writer kept a phantom record: {bool(phantom)}")

    sys.path.insert(0, str(ROOT))
    from custos.audit import AuditChain

    chain = AuditChain(database_url=os.environ["DATABASE_URL"])
    ok, why = chain.verify()
    clients = sorted({r.client_id for r in chain._records})
    print(f"fresh process: records {len(chain._records)} | verify: [{ok}, '{why}'] | clients {clients}")
    print(f"RESULT store verifies green from a fresh process: {ok}")
    return 0 if (accepted == 1 and refused and not phantom and ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
