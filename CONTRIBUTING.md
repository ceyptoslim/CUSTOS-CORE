# Contributing to CUSTOS Core

## Getting Started

```bash
git clone https://github.com/ceyptoslim/CUSTOS-CORE.git
cd CUSTOS-CORE
pip install -r requirements.txt
pytest tests/ -v
```

All tests must pass before submitting a PR.

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

Focus areas for contributions: audit persistence, OPA integration, structured logging, multi-tenant client management.
