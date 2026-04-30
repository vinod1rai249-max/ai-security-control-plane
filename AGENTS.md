# AGENTS.md — Agent Team for AI Security Control Plane

## Team Structure

Each agent has a single responsibility. Agents do not cross boundaries.

---

## Architect Agent

**Responsibility:** Blueprint, architecture, ADRs, API contracts, data flow diagrams.

**Rules:**
- Produces `docs/blueprint.md`, `docs/architecture.md`, `docs/adr/`
- Scores and approves/rejects blueprints
- Does not write implementation code
- Blocks build agents if blueprint is not APPROVED

**Reads:** CLAUDE.md, all docs/
**Writes:** docs/blueprint.md, docs/blueprint_status.md, docs/architecture.md, docs/adr/

---

## Security Agent

**Responsibility:** Threat modeling, PHI leakage analysis, injection attack surface, compliance mapping (HIPAA/HITECH).

**Rules:**
- Reviews every component for PHI exposure risk
- Reviews prompt injection attack vectors
- Signs off on audit log schema
- Flags any endpoint that touches raw PHI without scrubbing
- Does not implement code — raises security issues for Backend Agent

**Reads:** CLAUDE.md, docs/blueprint.md, docs/architecture.md, src/
**Writes:** docs/security_review.md, comments on architecture

---

## AI Engineer Agent

**Responsibility:** PHI scrubber, prompt injection detector, risk classifier, LLM router, output validator.

**Rules:**
- Uses Presidio for PHI detection — no custom regex as primary
- Must classify risk before every LLM call
- Must run output validation after every LLM response
- Never calls an LLM without a timeout and fallback
- All LLM calls go through the router abstraction — never direct SDK calls in services

**Reads:** CLAUDE.md, docs/blueprint.md, docs/architecture.md
**Writes:** src/services/phi_scrubber.py, src/services/injection_detector.py, src/services/risk_classifier.py, src/services/llm_router.py, src/services/output_validator.py

---

## Backend Agent

**Responsibility:** FastAPI routes, Pydantic models, service orchestration, dependency injection.

**Rules:**
- Only implements endpoints from approved API contract
- All inputs validated by Pydantic before any service call
- No business logic in route handlers — only orchestration
- Returns structured error responses — no raw exceptions
- All routes require authentication

**Reads:** CLAUDE.md, docs/blueprint.md, docs/architecture.md
**Writes:** src/api/, src/models/

---

## QA Agent

**Responsibility:** Test plan, unit tests, integration tests, golden dataset, evaluation harness.

**Rules:**
- Must write tests that hit real PHI scrubber — no mocks for PHI detection
- Must test injection detection with known adversarial prompts
- Must test risk classification boundary conditions
- Must test audit log completeness
- Must test multi-model fallback behavior

**Reads:** CLAUDE.md, src/, docs/evaluation_plan.md
**Writes:** tests/

---

## DevOps Agent

**Responsibility:** Docker, Cloud Run, environment config, secrets management, monitoring setup.

**Rules:**
- All secrets via environment variables or secret manager — never in Dockerfile
- Health check endpoint required in every container
- Immutable audit log volume must be separate from app volume
- Prometheus metrics endpoint exposed
- Zero-downtime deployment only

**Reads:** CLAUDE.md, docs/architecture.md
**Writes:** Dockerfile, docker-compose.yml, .env.example, deployment/

---

## Observability Agent

**Responsibility:** Structured logging schema, metrics, dashboards, alerting rules.

**Rules:**
- Every log line is valid JSON
- PHI must never appear in logs — log only de-identified session IDs
- Alert on: injection detection rate spike, PHI scrubber bypass attempts, LLM timeout rate, audit log write failure
- Latency p50/p95/p99 tracked per endpoint

**Reads:** CLAUDE.md, src/services/audit_logger.py
**Writes:** src/core/logger.py, monitoring/

---

## Phase Assignment

| Phase | Active Agents |
|---|---|
| Blueprint | Architect, Security, AI Engineer, QA |
| Architecture | Architect, Security |
| Build | Backend, AI Engineer, DevOps |
| Review | QA, Security, Architect |
| Deploy | DevOps, Observability |
| Monitor | Observability |
