# Contributing to CUSTOS Core

## Getting Started

```bash
git clone https://github.com/ceyptoslim/CUSTOS-CORE.git
cd CUSTOS-CORE
pip install -r requirements.txt
pytest tests/ -v
```

All tests must pass before submitting a PR.

## CLA — Required Before First Contribution

All contributors must sign the [Contributor License Agreement (CLA)](./CLA.md)
before their pull requests can be merged. This is **automatically enforced** by
a GitHub Action that checks every PR.

### How to Sign

1. Read the [CLA document](./CLA.md)
2. Add your GitHub username to `CLA_SIGNERS.md` in your PR:

```markdown
| @your-github-username | Individual | 2026-09-02 | v1.0 |
```

3. Commit this change as part of your PR

The CLA check will automatically verify your signature and update the PR status.
If you have questions about the CLA, contact frolifeproductions@gmail.com.

## Branch Convention

| Branch | Purpose |
|--------|---------|
| `main` | Stable releases only |
| `dev`  | Active development |
| `feat/your-feature` | Feature branches |

## Commit Convention

```
feat: add OPA policy backend
fix: resolve rate limiter hour window reset bug
test: add audit chain tamper detection tests
docs: update ARCHITECTURE.md
refactor: move models to custos/models.py
```

## Pull Request Requirements

- [ ] CLA signed (add username to `CLA_SIGNERS.md`)
- [ ] All existing tests pass (`pytest tests/ -v`)
- [ ] New functionality has tests
- [ ] `ruff check custos/ main.py` passes with no errors
- [ ] No secrets or credentials in code
- [ ] PR description explains what changed and why

## Code Style

- Python 3.12+
- `ruff` for linting (pinned version in CI)
- Type hints on all public functions
- Docstrings on all public classes and methods

## What We Are NOT Looking For Right Now

- Blockchain anchoring
- Merkle tree ledgers
- Multi-cloud deployment configs
- Enterprise SSO

Focus areas for contributions (as of v1.3):
- Policy version registry with rollback
- RS256 / JWKS auth upgrade for multi-tenant production use
- Distributed rate limiting for multi-replica deployments
- OTLP export test coverage against a real collector
- Additional SSRF test vectors for private IP ranges
- Performance benchmarking for high-throughput /v1/evaluate
