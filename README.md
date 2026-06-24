# CUSTOS-CORE

CUSTOS Core

Policy-Governed AI Execution Firewall

CUSTOS sits between AI systems and production infrastructure, enforcing deterministic policy decisions, auditability, observability, and governance controls before execution.

Features

- Deterministic policy engine
- Execution governance layer
- Audit-chain logging
- Correlation IDs
- OpenTelemetry tracing
- Prometheus metrics
- Grafana dashboards
- Structured logging
- Docker deployment
- Kubernetes-ready
- GitHub Actions CI
- Security scanning

Quick Start

Requirements

- Docker
- Docker Compose

Run

docker compose up --build

API

"POST /v1/evaluate"

Example request:

{
  "operation": "refund",
  "amount": 100
}

Example response:

{
  "allowed": true,
  "reason": "policy_passed"
}

Metrics

"GET /metrics"

Grafana

"http://localhost:3000" (http://localhost:3000)

Prometheus

"http://localhost:9090" (http://localhost:9090)

Architecture

Client
↓
FastAPI Gateway
↓
Policy Engine
↓
Audit Chain
↓
Observability Layer

Observability stack:

- OpenTelemetry
- Prometheus
- Grafana
- Structured logs

Roadmap

Phase 1

- Core runtime

Phase 2

- Observability

Phase 3

- Decision replay

Phase 4

- Merkle audit ledger

Phase 5

- Multi-tenant governance

License

Apache-2.0