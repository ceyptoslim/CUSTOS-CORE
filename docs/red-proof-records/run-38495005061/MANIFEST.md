# Frozen Observation Set — Run 38495005061

**Purpose.** A permanent, in-repo copy of the CI evidence artifacts produced by workflow
`ci-red-proof` run 38495005061 (record spec v3, commit `925f96eabebf`). GitHub expires run
artifacts after ~90 days; this copy makes the observation set citable indefinitely and closes
the one gap in the frozen series, where a v3 record had been reconstructed from ephemeral
artifacts.

**Source (public):** https://github.com/ceyptoslim/CUSTOS-CORE/actions/runs/38495005061

**Provenance of this copy.** The artifacts were downloaded from the run's own GitHub Actions
artifact store on 2026-11-04, while still within retention, as the two published artifacts
`red-proof-records-001-weaken-admin-auth` and `red-proof-records-002-invert-opa-deny`. They were
not reconstructed from a third party's copy. Byte identity against the digests recorded
independently by FactNotebook in `FN-CUSTOS-REDPROOF-002` Annex D was confirmed before freezing:

| Artifact | Digest recorded in Annex D | Digest of the file frozen here |
|---|---|---|
| `red-proof-junit.xml` | `5ffa02dc…` | `5ffa02dca42ee5f41954a9b6b1b352e5a31433614a0b4f65770ddf0ec51af9e3` |
| `red-proof-pytest-output.txt` | `d8b9e12d…` | `d8b9e12daf32aeabbd278994278a71765b495dc3a6a5cc2f5d307f0dcb25fe3d` |
| `red-proof-injection-diff.patch` | `29d73e8f…` | `29d73e8fca95e8961fe209bcae490410eb539afff83f187da832bca3cd1be567` |
| `red-proof-exit-code.txt` | `4355a46b…` | `4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865` |

The exit-code artifact is two bytes, `1\n`. That is why its digest matches the exit-code
artifact frozen for run 38610363998: identical content, so identical hash. `sha256("1")` without
the trailing newline is a different value (`6b86b273…`) and is not what these runs record.

## What the run contains

Two classes executed in the same run, each with its own artifact:

| Class | record_version | Tests | Result | Verdict |
|---|---|---|---|---|
| `001-weaken-admin-auth` | 3 | 506 collected, 35 skipped | 6 failed, 465 passed | RED-CONFIRMED |
| `002-invert-opa-deny` | 3 | 506 collected, 35 skipped | 18 failed, 453 passed | RED-CONFIRMED |

`001-weaken-admin-auth` is the class the third-party reconstruction `FN-CUSTOS-REDPROOF-002`
reconstructs. Its six failures are exactly the assertions that reconstruction names:

- `TestAdminEndpointsRequireAuth::test_audit_endpoints_reject_missing_token`
- `TestAdminEndpointsRequireAuth::test_replay_rejects_missing_token`
- `TestAdminEndpointsRequireAuth::test_tenant_register_rejects_missing_token`
- `TestAdminEndpointsRequireAuth::test_tenant_delete_rejects_missing_token`
- `TestAdminEndpointsRequireAuth::test_invalid_token_rejected`
- `TestAuthEnforcement::test_production_disables_auth_bypass`

Both records carry `record_version: 3`, `pytest_exit_code: 1`, verdict rule v3, and a sealed
`injection_diff_sha256` bound into the record identity.

## Contents and hashes

### `001-weaken-admin-auth/`

| File | SHA-256 |
|---|---|
| `red-proof-evidence.json` | `6d148985fc1b27ded23f3f2b832e006637c20b09e20c701396e895b04779f0f1` |
| `red-proof-junit.xml` | `5ffa02dca42ee5f41954a9b6b1b352e5a31433614a0b4f65770ddf0ec51af9e3` |
| `red-proof-pytest-output.txt` | `d8b9e12daf32aeabbd278994278a71765b495dc3a6a5cc2f5d307f0dcb25fe3d` |
| `red-proof-injection-diff.patch` | `29d73e8fca95e8961fe209bcae490410eb539afff83f187da832bca3cd1be567` |
| `red-proof-exit-code.txt` | `4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865` |

### `002-invert-opa-deny/`

| File | SHA-256 |
|---|---|
| `red-proof-evidence.json` | `f7ad661ba496c166784f79c3e5749a805d077c0faefa45bef26eaf24270f3f31` |
| `red-proof-junit.xml` | `af6327e99cc5b282275f9b52f1ff7c5348afa573666814ef2aee65ffef75e867` |
| `red-proof-pytest-output.txt` | `a6b30c345373573004376ce0fc2449e9fa0b47caf0482ed8dce6c15c0da21903` |
| `red-proof-injection-diff.patch` | `90536c15e486987abf2ef148e90040a46eac137df9c23eb2f657a466435c5ac1` |
| `red-proof-exit-code.txt` | `4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865` |

## What this closes, and what it does not

Closes: the re-walkability gap. Any reader can now re-hash these files against this manifest
without depending on GitHub's retention window or on a proxy link, so the record that
`FN-CUSTOS-REDPROOF-002` reconstructs is preserved the same way runs 9, 11 and 12 are.

Does not change: the observations themselves. Freezing artifacts does not re-run anything, does
not upgrade a claim, and does not convert a third party's reconstruction into a certification.
The bound injection diff records the modification; it does not by itself show the executed code
was exactly the diffed code, and FactNotebook does not re-run the suite.
