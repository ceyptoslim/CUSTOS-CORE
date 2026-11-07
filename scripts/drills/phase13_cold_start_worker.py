"""One cold start against an empty store, from a separate OS process.

Run through phase13_cold_start_race.py, not directly. The wall-clock barrier is
the point: both processes have to be inside schema creation at the same moment,
because the defect being measured is a race between two CREATE statements, and a
staggered pair measures nothing.

Reports the two stages separately because they are different claims:

  schema up          schema creation finished. This is the condition issue 131
                     is about, and it is asserted for BOTH processes.
  append allowed     the record landed.
  append refused     the store refused the append, which for the second writer
                     is the single-writer invariant doing its job.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from custos.audit import AuditChain  # noqa: E402
from custos.policy_store import PolicyStore  # noqa: E402

name = sys.argv[1]
url = os.environ["CUSTOS_DRILL_URL"]
start_at = float(os.environ["CUSTOS_DRILL_START_AT"])

while time.time() < start_at:
    time.sleep(0.0002)

began = time.time()
try:
    chain = AuditChain(database_url=url, tenant_id="default")
    PolicyStore(database_url=url)
except Exception as exc:  # noqa: BLE001 - this is the defect being measured
    detail = str(exc).splitlines()[0][:110]
    print(f"RESULT {name}: SCHEMA died {type(exc).__name__}: {detail}", flush=True)
    raise SystemExit(0)

print(f"RESULT {name}: schema up after {int((time.time() - began) * 1000)} ms", flush=True)

try:
    record = chain.record(
        client_id=name,
        action="allow",
        reason="cold start probe",
        content=f"cold start from {name}",
    )
except Exception as exc:  # noqa: BLE001
    print(f"RESULT {name}: append refused {type(exc).__name__}", flush=True)
    raise SystemExit(0)

print(f"RESULT {name}: append allowed {record.record_hash[:12]}", flush=True)
