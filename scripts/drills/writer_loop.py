"""Phase 8 child: write through the served path until the parent kills us.

One client identity per request so the per-client quota never engages, and a
unique content string per record so nothing is deduplicated. The parent sends
SIGKILL after a few seconds; there is no shutdown path to run, which is the
point.

Run through scripts/drills/phase8_kill_mid_append.py, not directly.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import os
import sys
import time

import jwt
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import main  # noqa: E402

secret = os.environ["CUSTOS_JWT_SECRET"]


def token(name: str) -> dict:
    return {
        "Authorization": "Bearer "
        + jwt.encode({"sub": name, "exp": int(time.time()) + 3600}, secret, algorithm="HS256")
    }


def main_loop() -> None:
    with TestClient(main.app) as client:
        print("BOOTED", flush=True)
        i = 0
        while True:
            i += 1
            r = client.post(
                "/v1/evaluate",
                json={"client_id": f"kill-{i}", "content": f"record {i} {time.time()}"},
                headers=token(f"kill-{i}"),
            )
            print(f"wrote {i} {r.status_code}", flush=True)


if __name__ == "__main__":
    main_loop()
