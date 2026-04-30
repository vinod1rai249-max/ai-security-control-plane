# CLAUDE.md — AI Security Control Plane for Healthcare Diagnostics

## Constitution

This document is the single source of truth for all agents, tools, and contributors working on this project.

---

## Product

**Name:** AI Security Control Plane for Healthcare Diagnostics
**Domain:** Healthcare AI / Cybersecurity / Compliance
**Regulation:** HIPAA, HITECH, NIST AI RMF

---

## Mission

Provide a policy-enforcing middleware layer that sits between clinical applications and AI models, ensuring:

- Zero PHI leakage to external LLMs
- Detection and rejection of adversarial prompt injections
- Risk-based routing to cost-appropriate models
- Immutable HIPAA-compliant audit logs
- Unified multi-model support without rebuilding security per model

---

## Golden Rules

1. Blueprint must be APPROVED before any code is written.
2. No PHI ever leaves the control plane in raw form.
3. Every request and response is logged — no exceptions.
4. Risk classification happens before routing — never after.
5. Human review is required for CRITICAL risk requests.
6. All secrets in environment variables only — never in code or logs.
7. Do not invent API endpoints beyond the approved contract.
8. Do not use LLMs for deterministic validation — use code.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python 3.11+) |
| Validation | Pydantic v2 |
| PHI Detection | Presidio + custom regex |
| Prompt Injection | Pattern matching + Claude classifier |
| LLM Router | Custom abstraction (Claude, OpenAI, Gemini) |
| Audit Storage | PostgreSQL (append-only with row-level security) |
| Cache | Redis |
| Auth | JWT + API keys |
| Observability | Structured JSON logs + Prometheus + Grafana |
| Tests | pytest + httpx |
| Deployment | Docker + Cloud Run |

---

## Non-Negotiables

- No `print()` statements — use structured logger
- No hardcoded secrets
- No mocking of PHI scrubber in integration tests
- No LLM call without prior risk classification
- Every endpoint must have a Pydantic input and output schema
- Every service function must have a docstring explaining the security contract

---

## Directory Layout

```
ai-security-control-plane/
├── CLAUDE.md
├── AGENTS.md
├── docs/
│   ├── blueprint.md
│   ├── blueprint_status.md
│   ├── architecture.md
│   ├── evaluation_plan.md
│   └── adr/
│       ├── 001-model-selection.md
│       ├── 002-database-choice.md
│       └── 003-deployment-strategy.md
├── src/
│   ├── api/
│   ├── services/
│   │   ├── phi_scrubber.py
│   │   ├── injection_detector.py
│   │   ├── risk_classifier.py
│   │   ├── policy_engine.py
│   │   ├── llm_router.py
│   │   ├── output_validator.py
│   │   └── audit_logger.py
│   ├── models/
│   └── core/
├── tests/
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Workflow

```
Blueprint APPROVED → Architecture → ADRs → Module Tasks → Build → Hook Validation → Review → Deploy → Monitor
```
