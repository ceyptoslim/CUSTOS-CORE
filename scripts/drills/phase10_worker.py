"""One replica of the gate: boot (loading whatever head exists), wait at a
barrier, then append. Two copies of this run against one store, which is the
topology that is refused when DECLARED and cannot be seen when it is not.

Run through phase10_two_writers.py, not directly.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import os
import secrets
import sys
import time
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import main  # noqa: E402

name = sys.argv[1]
barrier = Path(os.environ["DRILL_BARRIER"])
secret = os.environ.setdefault("CUSTOS_JWT_SECRET", secrets.token_hex(32))
chain = main.tenant_manager.get("default").audit_chain
tag = f"{name}-{os.getpid()}"

with TestClient(main.app, raise_server_exceptions=True) as client:
    print(f"RESULT {name} booted holding {len(chain._records)} records", flush=True)
    if os.environ.get("DRILL_WARMUP") == "1":
        # Schema creation only. Kept separate from the fork condition because a
        # cold start on an empty database races in schema creation (issue 131),
        # which is a different failure and would otherwise be read as the fork
        # guard firing.
        raise SystemExit(0)
    (barrier / f"ready-{tag}").write_text("1")
    deadline = time.time() + 60
    while not (barrier / f"go-{tag}").exists() and time.time() < deadline:
        time.sleep(0.05)
    try:
        token = jwt.encode(
            {"sub": name, "exp": int(time.time()) + 3600}, secret, algorithm="HS256"
        )
        r = client.post(
            "/v1/evaluate",
            json={"client_id": name, "content": f"append from {name}"},
            headers={"Authorization": f"Bearer {token}"},
        )
        print(f"RESULT {name} append: {r.status_code}", flush=True)
    except Exception as exc:  # noqa: BLE001 - the refusal is the result
        print(f"RESULT {name} append refused: {type(exc).__name__}: {str(exc)[:120]}", flush=True)
    print(f"RESULT {name} in-process chain length after: {len(chain._records)}", flush=True)
    (barrier / f"done-{tag}").write_text("1")
