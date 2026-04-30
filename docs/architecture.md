# Architecture: AI Security Control Plane for Healthcare Diagnostics

**Version:** 1.0  
**Date:** 2026-04-30  
**Blueprint:** docs/blueprint.md (APPROVED, 8.8/10)  
**Architect:** Architect Agent  

---

## 1. System Overview

The AI Security Control Plane is a stateless, synchronous middleware service. It intercepts every AI request from a clinical application, runs a sequential security pipeline, routes to the appropriate LLM, validates the response, logs an immutable audit event, and returns the result to the caller.

The control plane is transparent to the clinical application. The application sends one HTTP request and receives one HTTP response. All security, compliance, routing, and logging are internal to the plane.

```
[Clinical App / EHR Portal]
          │
          │ HTTPS TLS 1.3  POST /v1/analyze
          ▼
[API Gateway]  ──────────────────────────────────────────────────────────┐
          │                                                               │
          │ JWT validated, role confirmed, rate limits checked            │
          ▼                                                               │
[Control Plane Service]                                           [Audit DB]
    │                                                           (PostgreSQL)
    │  Sequential security pipeline                                       │
    ▼                                                                     │
[PHI Scrubber] → [Injection Detector] → [Risk Classifier]                │
                                              │                           │
                                              ▼                           │
                                    [Policy Engine]                       │
                                              │                           │
                                              ▼                           │
                                       [LLM Router]                      │
                                              │                           │
                                  ┌───────────┼──────────┐               │
                                  ▼           ▼          ▼               │
                              [Claude]    [OpenAI]   [Gemini]            │
                                  └───────────┼──────────┘               │
                                              ▼                           │
                                   [Output Validator]                    │
                                              │                           │
                                              ▼                           │
                                      [Audit Logger] ────────────────────┘
                                              │
                                              ▼
                                   [Response Builder]
                                              │
                                              │ HTTPS TLS 1.3
                                              ▼
                                    [Clinical App]
```

---

## 2. Component Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      CONTROL PLANE SERVICE                          │
│                                                                     │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────────────┐ │
│  │ FastAPI App │   │  Middleware   │   │   Dependency Injection   │ │
│  │  (ASGI)     │   │  (Auth/Logs) │   │   (Service wiring)       │ │
│  └──────┬──────┘   └──────────────┘   └──────────────────────────┘ │
│         │                                                           │
│  ┌──────▼───────────────────────────────────────────────────────┐  │
│  │                    SECURITY PIPELINE                          │  │
│  │                                                               │  │
│  │  ┌──────────────┐  ┌─────────────────┐  ┌────────────────┐  │  │
│  │  │ PHI Scrubber │→ │Injection Detector│→ │Risk Classifier │  │  │
│  │  │  (Presidio)  │  │ (3-layer)       │  │ (deterministic)│  │  │
│  │  └──────────────┘  └─────────────────┘  └───────┬────────┘  │  │
│  │                                                  │            │  │
│  │  ┌──────────────┐  ┌─────────────────┐          │            │  │
│  │  │Output Valid. │← │   LLM Router    │←─────────┘            │  │
│  │  │  (Presidio)  │  │ (tier-based)    │  ┌────────────────┐  │  │
│  │  └──────┬───────┘  └─────────────────┘  │ Policy Engine  │  │  │
│  │         │                               │ (consent/DUA)  │  │  │
│  │  ┌──────▼───────┐                        └────────────────┘  │  │
│  │  │Audit Logger  │                                             │  │
│  │  │(append-only) │                                             │  │
│  │  └──────────────┘                                             │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘

External dependencies (all behind VPC egress):
- Redis (token store, encrypted, TTL=300s)
- PostgreSQL (audit DB, append-only)
- Claude API (Anthropic)
- OpenAI API
- Google Gemini API
- Internal Consent Service (HTTP)
```

---

## 3. Component Responsibilities

### 3.1 API Gateway

**Owned by:** Infrastructure (not part of control plane source code)  
**Technology:** Cloud Run ingress / nginx / Kong (TBD per deployment target)

Responsibilities:
- TLS 1.3 termination
- JWT validation (RS256, public key from org identity provider)
- Role extraction from JWT claims
- Rate limiting: per-user (60/min), per-org (1000/min), global (10,000/min)
- Request ID generation and header injection (`X-Request-ID`)
- Return 401 for invalid JWT, 429 for rate limit exceeded

Does NOT: inspect payload, perform PHI checks, apply business logic.

---

### 3.2 PHI Scrubber

**Owned by:** AI Engineer Agent  
**File:** `src/services/phi_scrubber.py`

Responsibilities:
- Accept: raw clinical text string + `session_id`
- Run Presidio `AnalyzerEngine` with en_core_web_lg NER model
- Apply custom recognizers for MRN and US insurance ID formats
- Replace each detected entity with a typed pseudonymous token: `[PHI_{TYPE}_{INDEX}]`
- Build token-to-value map keyed by token string
- Store encrypted token map in Redis: `phi:tokens:{session_id}` with TTL=300s
- Return: de-identified text + entity count + entity types detected (no raw values)

Failure mode: raises `PHIScrubberError` → caller returns 503, attempts audit log write.

Does NOT: make external API calls, log raw PHI values, store PHI beyond TTL.

---

### 3.3 Injection Detector

**Owned by:** AI Engineer Agent  
**File:** `src/services/injection_detector.py`

Responsibilities:
- Layer 1 (Pattern): compile regex library at startup from `config/injection_patterns.yaml`; scan for known adversarial strings; return immediately if matched
- Layer 2 (Semantic): load sentence-transformer (`all-MiniLM-L6-v2`) at startup; embed prompt; compute cosine similarity against 500+ injection embedding vectors loaded from `config/injection_embeddings.npy`; threshold 0.85 → detected
- Layer 3 (LLM Classifier): invoked only when Layer 2 similarity is in range [0.70, 0.85]; uses Claude Haiku via LLM Router; parses `{injection: bool, confidence: float}` from structured response; confidence < 0.60 → treat as injection (fail-closed)
- Return: `InjectionResult(detected, layer, confidence, matched_patterns)`

Failure mode: raises `InjectionDetectorError` → caller returns 503.

Does NOT: pass injected prompts to downstream models, log prompt content.

---

### 3.4 Risk Classifier

**Owned by:** AI Engineer Agent  
**File:** `src/services/risk_classifier.py`

Responsibilities:
- Accept: request metadata (type, urgency, role) + `phi_entity_count`
- Load scoring weights from `config/risk_weights.yaml`
- Compute weighted score across 6 factors (see blueprint FR-04)
- Map score to band: LOW (1.0–1.8), MEDIUM (1.9–2.6), HIGH (2.7–3.4), CRITICAL (3.5–4.0)
- Return: `RiskLevel` enum — immutable once set
- If CRITICAL: write to human review queue table in PostgreSQL, return 202 to caller

Failure mode: default to HIGH risk tier, set `risk_classifier_error=true` flag in audit event, continue pipeline.

Does NOT: call any external service, use LLMs, store state.

---

### 3.5 Policy Engine

**Owned by:** Backend Agent  
**File:** `src/services/policy_engine.py`

Responsibilities:
- Run 5 sequential policy checks (order matters — cheaper checks first):
  1. Role-request alignment (in-memory config lookup, < 1ms)
  2. Time restriction (in-memory org config, < 1ms)
  3. Model restriction (in-memory org config, < 1ms)
  4. Data Use Agreement (in-memory org config, < 1ms)
  5. Consent check (HTTP call to internal consent service, timeout=2s)
- Load org policy rules from `config/org_policies/{org_id}.yaml` at startup, refresh every 5 minutes
- Return: `PolicyResult(allowed: bool, violation_code: str | None)`

Failure mode: on timeout or error → `PolicyResult(allowed=False, violation_code="POLICY_ENGINE_TIMEOUT")` → 503.

Does NOT: cache consent check results (consent may be revoked between requests).

---

### 3.6 LLM Router

**Owned by:** AI Engineer Agent  
**File:** `src/services/llm_router.py`

Responsibilities:
- Accept: `RiskLevel` + de-identified prompt + `org_id`
- Load tier-to-model mapping from `config/model_tiers.yaml`
- Apply org-level model restriction override (within tier only — cannot downgrade tier)
- Load hardened system prompt from `config/system_prompts/{request_type}.txt`
- Build final prompt: system prompt + de-identified clinical context + query
- Set timeout per tier: LOW=10s, MEDIUM=30s, HIGH=60s
- Set max_tokens per tier: LOW=512, MEDIUM=1024, HIGH=2048
- Call primary model via provider SDK; if timeout: retry once; if retry fails: failover to secondary model
- Maintain circuit breaker per model endpoint: open if 5 failures in 60s window; half-open after 30s
- Return: `LLMResponse(text, model_used, latency_ms, token_count)`

Failure mode: if all models at tier fail → raises `AllModelsUnavailableError` → 503.

Does NOT: send raw PHI to models, allow user-controlled system prompt override, downgrade risk tier to find an available model.

---

### 3.7 Output Validator

**Owned by:** AI Engineer Agent  
**File:** `src/services/output_validator.py`

Responsibilities:
- Step 1 — Residual PHI scan: run Presidio on LLM response text; if PHI detected, strip tokens; if unable to cleanly strip → block response
- Step 2 — Disclaimer check: verify response contains required disclaimer string (org-configurable, default: `"This is not a substitute for professional medical advice"`); if missing → append standard disclaimer
- Step 3 — Prohibited content check: scan for patterns defined in `config/prohibited_output_patterns.yaml` (e.g., definitive diagnosis statements, specific prescription dosages); if matched → flag in audit, optionally block
- Step 4 — Token restoration: retrieve token map from Redis using `session_id`; replace all `[PHI_*]` tokens in response with original values; delete Redis key after restoration
- Return: `ValidationResult(passed, sanitized_text, residual_phi_found, disclaimer_appended)`

Failure mode: if Redis unavailable for token restoration → block response (cannot deliver corrupted output with unreplaced tokens).

Does NOT: pass validation failures silently, skip PHI scan for any model.

---

### 3.8 Audit Logger

**Owned by:** Backend Agent  
**File:** `src/services/audit_logger.py`

Responsibilities:
- Accept: all lifecycle fields defined in blueprint FR-08 schema
- Validate that no raw PHI is present in any field before writing
- Write one `AuditEvent` row to PostgreSQL `audit_events` table
- Table enforces append-only via DB trigger (UPDATE/DELETE raise exception)
- Use row-level security: service account `cp_writer` has INSERT only; `cp_admin` has SELECT only
- Return: `audit_event_id` (UUID) on success
- On write failure: raise `AuditWriteError` — caller must block response

Does NOT: log raw PHI, allow batch writes that could skip individual events, write outside the service account role.

---

### 3.9 FastAPI Application (Orchestrator)

**Owned by:** Backend Agent  
**Files:** `src/api/routes/`, `src/api/dependencies.py`, `src/core/`

Responsibilities:
- Define route handlers for: `POST /v1/analyze`, `GET /v1/audit/logs`, `POST /v1/injection/probe`, `GET /v1/health`, `GET /v1/metrics`
- Route handlers contain orchestration logic only — no business logic
- Inject services via FastAPI dependency injection
- Catch all service exceptions, map to structured HTTP responses
- Emit structured JSON log for every request (no PHI in log fields)
- Expose Prometheus metrics via `prometheus-fastapi-instrumentator`

---

## 4. Service Pipeline Sequence (Happy Path)

```
Request arrives at /v1/analyze
    │
    ├─ [Auth Middleware] JWT → role, org_id, user_id extracted
    │
    ├─ [PHI Scrubber] raw text → de-identified text + token map → Redis
    │
    ├─ [Injection Detector] Layer 1 → Layer 2 → (Layer 3 if ambiguous)
    │   └─ DETECTED: 403 + audit → STOP
    │
    ├─ [Risk Classifier] score → risk_level (LOW/MEDIUM/HIGH/CRITICAL)
    │   └─ CRITICAL: 202 + human queue + audit → STOP
    │
    ├─ [Policy Engine] 5 checks sequentially
    │   └─ VIOLATION: 403 + violation_code + audit → STOP
    │
    ├─ [LLM Router] select model → call → retry/failover
    │   └─ ALL_FAIL: 503 + audit → STOP
    │
    ├─ [Output Validator] PHI scan → disclaimer → prohibited → token restore
    │   └─ UNRESOLVABLE: 503 + audit → STOP
    │
    ├─ [Audit Logger] write append-only audit event
    │   └─ WRITE_FAIL: 503, suppress response → STOP
    │
    └─ [Response Builder] 200 OK with result + metadata + audit_event_id
```

Every STOP path attempts an audit log write before returning. If the audit log write also fails, the error is logged to the structured application log only.

---

## 5. Data Stores

### 5.1 Redis — Ephemeral Token Store

| Property | Value |
|---|---|
| Purpose | PHI token maps (session → token → original value) |
| Key pattern | `phi:tokens:{session_id}` |
| Value format | Encrypted JSON hash |
| TTL | 300 seconds |
| Encryption | Redis encryption at rest enabled |
| Access | Control plane service only (private subnet) |
| HA mode | Redis Cluster (3 nodes minimum in production) |
| On failure | Fail-closed: block request |

Redis does not store any state beyond the request TTL. It is not used for caching LLM responses (caching identical clinical queries is operationally risky and not in scope).

### 5.2 PostgreSQL — Audit Log Store

| Property | Value |
|---|---|
| Purpose | Immutable HIPAA-compliant audit trail |
| Table | `audit_events` (append-only, no UPDATE/DELETE) |
| Schema | See blueprint FR-08 |
| Row-level security | INSERT: `cp_writer` only; SELECT: `cp_admin` only |
| Encryption at rest | AES-256 (cloud-managed key) |
| Partitioning | Monthly range partition on `timestamp` (applied at > 10M events/month) |
| Backup | Daily encrypted snapshot → cold storage |
| Retention | 7 years |
| Access | Control plane service network only |
| On failure | Block response — no unlogged interactions |

### 5.3 PostgreSQL — Human Review Queue

| Property | Value |
|---|---|
| Purpose | Hold CRITICAL-risk requests for human review |
| Table | `critical_review_queue` |
| Schema | `queue_id`, `session_id`, `user_id`, `org_id`, `timestamp`, `request_summary` (no PHI), `status`, `reviewed_by`, `reviewed_at` |
| SLA | Resolution target: 4 hours; alert at 8 hours |
| Access | Admin role only |

### 5.4 Config Store — File-Based

| Property | Value |
|---|---|
| Purpose | Org policies, model tiers, risk weights, injection patterns, system prompts |
| Format | YAML (structured, version-controlled) |
| Location | `config/` directory |
| Refresh | In-memory cache refreshed every 5 minutes on policy rules |
| Secret values | Never stored in config — secrets via environment variables |

---

## 6. Security Boundary Map

```
┌──────────────────────────────────────────────────────────┐
│                   PUBLIC INTERNET                        │
│                                                          │
│   Clinical App → HTTPS TLS 1.3 → API Gateway            │
│                                                          │
└────────────────────────┬─────────────────────────────────┘
                         │ (authenticated, rate-limited)
┌────────────────────────▼─────────────────────────────────┐
│                   PRIVATE VPC                            │
│                                                          │
│   ┌──────────────────────────────────────────────────┐   │
│   │             CONTROL PLANE SUBNET                 │   │
│   │                                                  │   │
│   │   FastAPI Service (Cloud Run / container)        │   │
│   │   ↕ mTLS ↕ Redis (Memorystore)                  │   │
│   │   ↕ mTLS ↕ PostgreSQL (Cloud SQL)               │   │
│   │   ↕ mTLS ↕ Consent Service (internal HTTP)      │   │
│   └──────────────────────────────────────────────────┘   │
│                                                          │
│   ┌──────────────────────────────────────────────────┐   │
│   │             EGRESS (FIXED IP, ALLOWLISTED)        │   │
│   │                                                  │   │
│   │   → api.anthropic.com (Claude)                   │   │
│   │   → api.openai.com (GPT)                         │   │
│   │   → generativelanguage.googleapis.com (Gemini)   │   │
│   └──────────────────────────────────────────────────┘   │
│                                                          │
└──────────────────────────────────────────────────────────┘

PHI exists only in:
- Inbound request payload (scrubbed immediately)
- Redis token map (encrypted, TTL=300s)
- Authorized response after token restoration (never stored)

PHI never exists in:
- Audit logs
- Application logs
- LLM prompt payloads
- Config files
- Environment variables
```

---

## 7. Scalability Model

### Horizontal Scaling

- Control plane service is stateless between requests — all ephemeral state in Redis
- Scale horizontally: add Cloud Run instances (or container replicas) under load
- Redis Cluster handles concurrent token map reads/writes across instances
- PostgreSQL read replicas for audit log queries (writes to primary only)

### Throughput Targets

| Tier | Baseline | Scale Target | Notes |
|---|---|---|---|
| Concurrent requests | 100 | 500 | Add instances |
| Audit events/month | 500K | 10M | Add monthly partitioning |
| Redis keys at peak | 100 TTL=300s | 500 TTL=300s | Redis Cluster handles |
| Injection patterns | 200 | 2000 | Regex compile at startup |
| Injection embeddings | 500 | 5000 | Load from `.npy` at startup |

### Latency Budget

| Component | p50 | p95 | p99 |
|---|---|---|---|
| Auth middleware | < 1ms | < 2ms | < 5ms |
| PHI Scrubber (Presidio) | 20ms | 80ms | 150ms |
| Injection Layer 1 (regex) | < 1ms | < 1ms | < 2ms |
| Injection Layer 2 (embedding) | 5ms | 15ms | 25ms |
| Injection Layer 3 (LLM, rare) | 200ms | 400ms | 600ms |
| Risk Classifier | < 1ms | < 1ms | < 2ms |
| Policy Engine (with consent) | 20ms | 80ms | 150ms |
| Output Validator | 15ms | 50ms | 100ms |
| Audit Logger (DB write) | 5ms | 20ms | 50ms |
| **Control plane total (p95)** | | **< 500ms** | |

Model inference latency (not in scope for control plane budget):
- LOW (Haiku/Flash): 500ms–2s
- MEDIUM (Sonnet): 2s–8s
- HIGH (Opus): 5s–20s

---

## 8. Technology Decisions (ADR Index)

| Decision | ADR | Summary |
|---|---|---|
| LLM model selection per tier | ADR-001 | Claude family primary; OpenAI/Gemini as fallback |
| Audit database | ADR-002 | PostgreSQL + append-only trigger + RLS |
| Security architecture | ADR-003 | 10-layer defense-in-depth; fail-closed on all critical paths |
| Observability and evaluation | ADR-004 | Prometheus + Grafana; structured JSON logs; offline golden dataset |
| Deployment strategy | ADR-005 | Docker + Google Cloud Run; PostgreSQL on Cloud SQL; Redis on Memorystore |

---

## 9. Environment Layout

| Environment | Purpose | Notes |
|---|---|---|
| `local` | Developer iteration | Docker Compose; mock consent service; local Redis/Postgres |
| `staging` | Pre-production testing | Cloud Run; real LLM APIs with test keys; real DB; no real patient data |
| `production` | Live healthcare traffic | Cloud Run; real LLM APIs; Cloud SQL; Memorystore; monitoring active |

Promotion path: `local` → (passing tests) → `staging` → (passing integration + security tests) → `production`

No feature flags. No backwards-compatibility shims. Changes are deployed as new versions.

---

## 10. What This Architecture Explicitly Does NOT Do

- Does not store complete request or response text anywhere (not in DB, not in logs)
- Does not cache LLM responses (clinical queries are session-specific)
- Does not expose raw PHI in any interface, log, or metric
- Does not allow any pipeline component to be skipped under normal operation
- Does not downgrade a request to a lower risk tier to improve availability
- Does not call external APIs for PHI detection (Presidio is local)
- Does not use LLMs for deterministic decisions (risk classification, policy checks)
