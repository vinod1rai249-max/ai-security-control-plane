# ADR-003: Security Architecture — Defense in Depth

**Status:** Accepted  
**Date:** 2026-04-30  
**Deciders:** Architect Agent, Security Agent  
**Blueprint reference:** STEP 9 (Security Architecture), FR-01 through FR-08, NFR (HIPAA, HITECH, NIST AI RMF)

---

## Context

The control plane handles Protected Health Information (PHI) in clinical AI requests. HIPAA mandates technical safeguards for PHI access, transmission, and storage. Beyond HIPAA, the system faces specific AI-era threats not addressed by traditional security models:

- **Prompt injection:** Users may embed adversarial instructions in clinical text to hijack LLM behavior
- **PHI leakage via LLM prompts:** Without scrubbing, patient data flows to external AI providers
- **PHI leakage via LLM responses:** LLMs may echo back PHI fragments or hallucinate PHI-like strings
- **Unauthorized model access:** Without policy enforcement, any authenticated user can query any model
- **Audit trail gaps:** HIPAA requires every data access to be logged — missing logs are a compliance violation

A perimeter-only security model (firewall + TLS) is insufficient for this threat surface. A layered, defense-in-depth model is required where each layer assumes the previous layer may fail.

---

## Decision

Implement a **10-layer defense-in-depth security model** applied sequentially to every request. Each layer is independent — a failure or compromise at one layer is contained before the next layer executes.

### Layer Structure

```
Layer 1:  TLS 1.3 — transport encryption, no plaintext
Layer 2:  JWT Authentication (RS256) + role enforcement
Layer 3:  Rate limiting — per user, per org, global
Layer 4:  PHI Scrubbing — before any external call
Layer 5:  Prompt Injection Detection — 3-layer
Layer 6:  Risk Classification — deterministic, auditable
Layer 7:  Policy Enforcement — consent, DUA, role-request
Layer 8:  Hardened System Prompts — not user-overridable
Layer 9:  Output Validation — residual PHI, disclaimer, prohibited content
Layer 10: Immutable Audit Trail — append-only, HIPAA-compliant
```

### Fail-Closed Policy

Every security-critical layer operates fail-closed:

| Layer | Failure Behavior |
|---|---|
| PHI Scrubber | 503, no LLM call |
| Injection Detector | 503, no LLM call |
| Policy Engine | 503 (timeout), 403 (violation) |
| Output Validator | Sanitize or block |
| Audit Logger | Block response (no unlogged interactions) |
| Redis (token store) | 503 — cannot restore tokens |

Only the Risk Classifier has a soft fallback (default to HIGH tier) — because being overly conservative on risk is safe; being overly permissive is not.

### PHI Containment Strategy

PHI exists in exactly three states, each with strict controls:

| State | Location | Control |
|---|---|---|
| Raw inbound | Request payload | Scrubbed immediately by PHI Scrubber; never persisted |
| Tokenized | Redis (encrypted) | TTL=300s; private subnet; deleted after output restoration |
| Restored outbound | Control plane response | Not stored; returned to authorized caller only |

PHI never exists in: LLM prompts, audit logs, application logs, config files, metrics.

### Secrets Management

All credentials (LLM API keys, DB passwords, JWT signing keys, Redis auth) are stored in a cloud secret manager (GCP Secret Manager or AWS Secrets Manager). They are:
- Never hardcoded in source code
- Never in `.env` files committed to version control
- Never logged (structured logger masks values matching secret patterns)
- Rotated on schedule: LLM API keys every 90 days; JWT signing keys every 30 days

### Network Isolation

- Control plane runs in a private VPC subnet; not directly internet-accessible
- Only the API gateway is internet-facing
- All egress to LLM APIs: via fixed outbound IP addresses, allowlisted at provider level
- PostgreSQL, Redis, internal consent service: private subnet only
- Inter-service calls within VPC: mTLS (mutual TLS)

### Injection Attack Surface

The injection detector specifically addresses the AI-era threat of adversarial prompt manipulation. Three layers protect against distinct attack classes:

| Layer | Attacks Addressed |
|---|---|
| Pattern (regex) | Known injection templates (textbook attacks, DAN mode, jailbreaks) |
| Semantic (embedding) | Paraphrased variants of known attacks |
| LLM Classifier | Novel injection techniques not seen before |

The fail-closed default for the LLM classifier (confidence < 0.60 → treat as injection) means novel attacks default to blocked, not passed.

### System Prompt Hardening

Each request type has a corresponding hardened system prompt stored in `config/system_prompts/`. These prompts:
- Define the LLM's role as a clinical assistant, not a general-purpose agent
- Explicitly prohibit definitive diagnoses and specific prescription recommendations
- Require a medical disclaimer in every response
- Specify structured output format
- Cannot be overridden, appended to, or modified by user-supplied input

The user's clinical context and query are injected into a fixed template — users cannot supply a system prompt.

---

## Alternatives Considered

### Perimeter-Only Security (Firewall + TLS + Auth)

Rejected. Perimeter security assumes authenticated users are trusted. In a healthcare context, authenticated users may still attempt prompt injection, submit queries outside their authorized scope, or submit PHI to unauthorized models. The layered model does not trust any layer in isolation.

### PHI Anonymization via Cloud NLP APIs (AWS Comprehend Medical, GCP Healthcare NLP)

Rejected. Sending PHI to a cloud API for the purpose of detecting PHI creates the exact exposure the scrubber is meant to prevent. Presidio runs locally; no PHI leaves the control plane during detection.

### Trust LLM Safety Training as a Security Control

Rejected. LLM safety training (RLHF, Constitutional AI) is a probabilistic control, not a deterministic one. It reduces but does not eliminate the probability of harmful outputs. PHI scrubbing, injection detection, and output validation are deterministic controls that do not rely on model behavior.

### Single-Point Validation (Input Only or Output Only)

Rejected. Input-only validation misses residual PHI in LLM outputs (hallucinated strings). Output-only validation (without input scrubbing) allows PHI to reach external LLM providers, violating HIPAA. Both directions must be validated.

---

## Consequences

**Positive:**
- Each layer independently reduces attack surface — a failure at one layer is caught by the next
- PHI containment is enforced structurally (Presidio + token map) rather than by policy compliance
- Injection detection is defense-in-depth: pattern → semantic → LLM covers known, paraphrased, and novel attacks
- Audit trail is immutable at the DB level — no application-layer bug can delete or modify records
- The fail-closed design means the system defaults to safety rather than availability under failure

**Negative:**
- 10 layers add cumulative latency overhead (~140–250ms p95 for control plane processing alone)
- More components mean more failure modes to monitor and alert on
- Defense-in-depth increases code surface area — more code to maintain, test, and audit
- Fail-closed on audit logger means a DB outage blocks all responses — this is the correct HIPAA behavior but has availability implications

**Neutral:**
- The 10-layer model maps directly to HIPAA Technical Safeguards (§164.312), making compliance documentation straightforward

---

## Trade-offs

| Trade-off | Choice Made | What Was Sacrificed |
|---|---|---|
| Latency vs security depth | Accept 140–250ms overhead for 10 layers | Faster response with fewer checks |
| Availability vs compliance | Fail-closed on audit write | Some availability under DB failure |
| Deterministic vs ML-based controls | Deterministic for risk and policy; ML only for injection ambiguity | Flexibility of fully ML-driven policy |
| Local PHI detection vs cloud API | Presidio local | Cloud NLP APIs have higher recall on some entity types |
| Prompt trust vs prompt hardening | Hardened templates, no user prompt override | User cannot customize LLM behavior per request |
