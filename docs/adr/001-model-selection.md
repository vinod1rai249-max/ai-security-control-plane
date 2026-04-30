# ADR-001: LLM Model Selection Strategy

**Status:** Accepted  
**Date:** 2026-04-30  
**Deciders:** Architect Agent, AI Engineer Agent, Security Agent  
**Blueprint reference:** FR-06 (Risk-Based LLM Routing)

---

## Context

The control plane must route requests to AI models based on risk tier. Three decisions must be made:

1. Which models map to which risk tiers?
2. Which model provider(s) should be supported?
3. Which model handles the injection classifier (Layer 3)?

Healthcare diagnostics demands high accuracy for HIGH-risk requests, cost discipline for LOW-risk requests, and HIPAA-safe providers for all tiers. The model abstraction layer must support multi-provider fallback without changing routing policy.

Additional constraints from the blueprint:
- Injection classifier (Layer 3) must use the cheapest possible model — it is called for < 5% of requests
- CRITICAL risk requests never touch a model — they go to a human review queue
- Org-level overrides can change model selection within a tier but cannot change tier membership
- De-identified prompts only — no raw PHI ever sent to any model

---

## Decision

### Primary Model Tier Assignment

| Risk Tier | Primary Model | Secondary (Fallback) | Injection Classifier |
|---|---|---|---|
| LOW | claude-haiku-4-5-20251001 | gemini-2.0-flash | claude-haiku-4-5-20251001 |
| MEDIUM | claude-sonnet-4-6 | gpt-4o-mini | (not applicable) |
| HIGH | claude-opus-4-7 | gpt-4 | (not applicable) |
| CRITICAL | Blocked — human queue | N/A | (not applicable) |

### Rationale for Claude as Primary

- Claude models are trained with Constitutional AI and have strong safety alignment relevant to healthcare content
- Consistent API interface across Haiku / Sonnet / Opus simplifies the router abstraction
- Claude Haiku is one of the lowest-cost, lowest-latency frontier models available — appropriate for LOW-tier queries
- Claude Opus 4.7 provides the highest reasoning quality for HIGH-tier diagnostic queries

### Rationale for OpenAI / Gemini as Fallback

- Single-provider dependency creates availability risk; adding one fallback per tier is the minimum for 99.9% uptime target
- GPT-4o-mini is cost-comparable to Sonnet for MEDIUM tier
- Gemini Flash is cost-comparable to Haiku for LOW tier
- Fallback providers are only invoked after primary model retry fails — not for cost optimization

### Rationale for Haiku as Injection Classifier

- Layer 3 injection classification is invoked for ambiguous cases only (< 5% of requests)
- Structured output `{injection: bool, confidence: float}` is a simple binary classification task
- Haiku provides the lowest cost-per-call with sufficient capability for this task
- Using Opus or Sonnet for injection classification would be over-engineered and cost-inefficient

### Per-Call Configuration

| Setting | LOW | MEDIUM | HIGH |
|---|---|---|---|
| max_tokens | 512 | 1024 | 2048 |
| timeout | 10s | 30s | 60s |
| retries | 1 | 1 | 1 |
| system prompt | healthcare-safe-low.txt | healthcare-safe-medium.txt | healthcare-safe-high.txt |

System prompts are hardened: users cannot override them via request payload. System prompts enforce:
- No definitive diagnosis
- No specific prescription recommendations
- Medical disclaimer required in every response
- If uncertain, state uncertainty explicitly

---

## Alternatives Considered

### Single-Provider (Claude Only)

Rejected. Single-provider dependency creates a single point of failure incompatible with the 99.9% availability target. Provider outages do occur; fallback to a secondary provider is the standard mitigation.

### Open-Source / Self-Hosted Models (Llama, Mistral)

Rejected for initial deployment. Self-hosted models require GPU infrastructure, model management, and ongoing evaluation. The operational overhead is not justified at initial scale. The router abstraction allows adding self-hosted models as a future option without architectural change.

### Cost-Based Routing (Cheapest Available Model Regardless of Risk)

Rejected. The blueprint explicitly states that routing decisions must be made on security/risk criteria. Routing a HIGH-risk diagnostic query to Haiku because Opus is temporarily expensive would undermine the safety model. Cost is a consequence of risk-based routing, not a routing driver.

### Single Model for All Tiers

Rejected. Using Opus for all requests would cost approximately 15× more than Haiku for LOW-risk queries. At scale, this is not financially sustainable. The risk-tiered model exists specifically to match capability to need.

---

## Consequences

**Positive:**
- Three providers (Anthropic, OpenAI, Google) provide provider-level redundancy
- Tier-based routing is auditable — every audit event records `model_used`
- Model rotation within a tier requires only a config change, no code change
- Injection classifier reuses the existing LLM Router abstraction — no additional SDK integration

**Negative:**
- Three provider API keys must be managed and rotated (90-day rotation policy)
- Behavior differences between Claude, GPT-4, and Gemini may produce subtly different response styles — output validation must normalize disclaimer presence regardless of provider
- Fallback to secondary provider adds a provider switch mid-request when primary fails; secondary model quality may differ from primary for HIGH-tier requests

**Neutral:**
- Model IDs will need updating as providers release new versions; `config/model_tiers.yaml` is the single point of change

---

## Trade-offs

| Trade-off | Choice Made | What Was Sacrificed |
|---|---|---|
| Provider consistency vs availability | Multi-provider | Consistent output style across all requests |
| Injection classifier quality vs cost | Cheapest model (Haiku) | Marginal accuracy improvement from using Sonnet |
| Model lock-in vs operational simplicity | Abstraction layer | Slightly more upfront engineering on the router |
| Cost optimization vs safety | Risk tier drives routing | Some LOW requests could have been served even more cheaply |
