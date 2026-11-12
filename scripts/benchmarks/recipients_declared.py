"""Generate the declared recipient list for the provenance series.

The list is not hand-written. It is derived from the benchmark's own data files,
under one rule: a recipient is *declared* if it appears in the environment the
suite ships, and it is *not* declared if it appears only inside an injection
vector. The second set is what an attack tries to introduce, so treating it as
declared would be the very error the series measures.

Regenerate and compare the hash rather than editing the JSON:

    python scripts/benchmarks/recipients_declared.py --check

The pre-registration pins the sha256 of the generated file, so a drift in the
suite's data or in this rule fails a test rather than quietly changing what the
attack is allowed to reach.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
OUT = pathlib.Path(__file__).resolve().parents[2] / "docs" / "benchmark" / "recipients-declared-v1.json"
SUITE_DATA = "data/suites/banking"
FILES = ("environment.yaml", "injection_vectors.yaml")


def build(agentdojo_root: pathlib.Path) -> dict:
    base = agentdojo_root / SUITE_DATA
    env_text = (base / FILES[0]).read_text()
    inj_text = (base / FILES[1]).read_text()
    in_env = sorted(set(IBAN.findall(env_text)))
    in_injection = sorted(set(IBAN.findall(inj_text)))
    attacker_only = sorted(set(in_injection) - set(in_env))
    return {
        "source": f"{SUITE_DATA}/{FILES[0]}",
        "rule": (
            "declared = IBAN present in the shipped environment; a recipient that "
            "appears only inside an injection vector is excluded and recorded "
            "separately, because the attack is what introduces it"
        ),
        "recipients": in_env,
        "excluded_injection_recipients": attacker_only,
    }


def digest(payload: dict) -> str:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(text.encode()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agentdojo-root", default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.agentdojo_root:
        root = pathlib.Path(args.agentdojo_root)
    else:
        try:
            import agentdojo
        except ImportError:
            # The suite's data files live inside the package, so there is nothing
            # to compare against without it. Said plainly and refused rather than
            # raised, because a CI runner has no benchmark extra and a traceback
            # there reads like a defect in this script.
            print(
                "agentdojo is not installed; install requirements-benchmark.txt or "
                "pass --agentdojo-root to a checkout of the package",
                file=sys.stderr,
            )
            return 2
        root = pathlib.Path(agentdojo.__file__).resolve().parent
    payload = build(root)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.write:
        OUT.write_text(text)
        print(f"wrote {OUT.relative_to(OUT.parents[2])} sha256={digest(payload)}")
        return 0
    if OUT.exists() and OUT.read_text() == text:
        print(f"identical sha256={digest(payload)}")
        return 0
    print(f"DRIFT: on-disk file does not match the rule\nsha256={digest(payload)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
