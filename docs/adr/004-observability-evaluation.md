# ADR-004: Observability and Evaluation Strategy

**Status:** Accepted  
**Date:** 2026-04-30  
**Deciders:** Architect Agent, Observability Agent, QA Agent  
**Blueprint reference:** STEP 10 (KPIs and Alert Thresholds), NFR

---

## Context

The control plane processes healthcare AI requests where failure is high-consequence:

- Missed PHI detection → HIPAA violation, data breach liability
- Missed injection detection → data exfiltration, prompt hijacking
- Silent LLM quality degradation → incorrect clinical interpretations
- Audit log failures → HIPAA compliance gap

Standard application monitoring (uptime, latency, error rate) is insufficient. The system requires domain-specific observability:

1. **Security observability:** PHI detection rates, injection attempt rates, policy violation patterns
2. **Model quality observability:** Output quality drift, hallucination indicators, disclaimer compliance
3. **Cost observability:** Per-tier request distribution, LLM token consumption, fallback rate
4. **Compliance observability:** Audit write success rate, CRITICAL request resolution time

A critical constraint: PHI must never appear in logs, metrics labels, or dashboards. Observability must be rich without exposing patient data.

---

## Decision

### Metrics — Prometheus + Grafana

**Prometheus** scrapes metrics from the control plane's `/v1/metrics` endpoint. Metrics are labeled by tier, component, and outcome — never by user content or PHI-derived values.

**Grafana** dashboards organized into four views:

1. **Security Dashboard:** Injection detection rate by layer, PHI detection rate, policy violation rate by type, CRITICAL request queue depth
2. **Model Performance Dashboard:** Request volume by tier, primary/fallback model split, LLM timeout rate, circuit breaker state per model endpoint
3. **Latency Dashboard:** p50/p95/p99 per pipeline component, total latency histogram, PHI scrubber latency distribution
4. **Cost Dashboard:** Token consumption by tier, estimated cost per request by tier, injection classifier invocation rate (cost signal for Layer 3 usage)

**Key metric definitions:**

```
cp_requests_total{status, risk_tier, model}       — counter
cp_phi_detected_total{entity_type}                — counter (entity type, not value)
cp_injection_detected_total{detection_layer}      — counter
cp_policy_violation_total{violation_code}         — counter
cp_audit_write_total{status}                      — counter (success/fail)
cp_llm_fallback_total{tier, reason}               — counter
cp_circuit_breaker_state{model}                   — gauge (0=closed, 1=open)
cp_latency_ms{component, quantile}               — histogram
cp_critical_queue_depth                           — gauge
cp_token_count{tier, model}                       — histogram
```

PHI constraint: metric labels contain `entity_type` (e.g., `PERSON`, `DATE_TIME`, `MRN`) but never entity values.

### Alerting — Prometheus Alertmanager

Alert rules derived directly from blueprint KPI thresholds:

| Alert | Condition | Severity |
|---|---|---|
| PHI recall degradation | PHI detection rate < 97% in 15-min window | CRITICAL |
| Injection detection degradation | Injection recall < 93% in 15-min window | CRITICAL |
| Audit write failure | Audit success rate < 99.99% | CRITICAL |
| Availability | Error rate > 0.5% sustained 5 min | CRITICAL |
| Control plane latency | p95 > 800ms sustained 5 min | HIGH |
| LLM fallback rate | Primary model fallback > 5% sustained 10 min | HIGH |
| Injection spike | Injection attempts > 3× baseline in 5-min window | HIGH |
| CRITICAL queue SLA | Queue items unresolved > 4 hours | HIGH |
| Cost spike | Token consumption > 2× baseline per tier | MEDIUM |
| Injection classifier overuse | Layer 3 invocations > 10% of detections | MEDIUM |

Notification routing: CRITICAL alerts → on-call + security team; HIGH → on-call; MEDIUM → async Slack channel.

### Structured Application Logging

Every log line is valid JSON (enforced by the structured logger in `src/core/logger.py`). Log schema:

```json
{
  "timestamp": "ISO 8601",
  "level": "INFO|WARN|ERROR",
  "service": "ai-security-control-plane",
  "version": "1.0.0",
  "request_id": "uuid",
  "session_id": "uuid",
  "org_id": "uuid",
  "component": "phi_scrubber|injection_detector|...",
  "event": "phi_detected|injection_blocked|llm_called|...",
  "duration_ms": 42,
  "risk_tier": "MEDIUM",
  "model": "claude-sonnet-4-6",
  "error_code": null
}
```

PHI constraint: `user_id` and `patient_id` never appear in application logs. `session_id` is the correlation identifier. Raw clinical text, PHI values, and LLM response content never appear in any log field.

### Offline Evaluation — Golden Dataset

A golden dataset of 500 curated test cases maintained in `tests/evaluation/golden/`:

- **PHI Detection:** 200 cases covering all 18 entity types; known PHI values and expected token outputs; precision and recall measured against ground truth
- **Injection Detection:** 150 cases; 100 known injection strings across all 3 detection layers; 50 clean clinical strings that must not trigger false positives
- **Risk Classification:** 100 cases; all combinations of request type, urgency, role, PHI count; expected tier for each
- **Output Validation:** 50 cases; responses with residual PHI, missing disclaimers, prohibited content; expected sanitization behavior

Evaluation cadence:
- PHI golden dataset: run weekly (automated CI job)
- Injection golden dataset: run weekly + after any injection pattern library update
- Risk classification: run on every config weight change
- Output validation: run weekly

Metric tracked per evaluation run: precision, recall, false positive rate, compared against targets from blueprint KPIs. Alert if any metric drops below warning threshold.

### Online Evaluation — Sampling

1% of production responses (de-identified) sampled for quality review:
- Reviewer checklist: disclaimer present, no definitive diagnosis, no hallucinated PHI-like strings, answer is clinically appropriate given the de-identified query
- Sampling uses `session_id` — no raw PHI involved in review
- Findings feed back into golden dataset and system prompt tuning

---

## Alternatives Considered

### Third-Party Observability SaaS (Datadog, New Relic, Honeycomb)

Considered for operational convenience. Rejected for two reasons:
1. Log and trace data from clinical AI requests — even without raw PHI — is sensitive healthcare metadata. Routing it to a third-party SaaS requires additional BAA (Business Associate Agreement) review and increases data governance complexity.
2. Cost at 500K requests/month with full distributed tracing would exceed the cost of self-hosted Prometheus + Grafana by a significant margin.

Prometheus + Grafana can be deployed on Cloud Run or as managed services (Google Managed Prometheus + Grafana Cloud) with data staying within the org's GCP project.

### LLM-Based Quality Evaluation (Using a Judge Model)

Considered for online evaluation. Rejected as primary evaluation mechanism because:
- LLM-as-judge introduces a non-deterministic evaluation layer that may disagree with itself across runs
- For the offline golden dataset, ground truth labels are more reliable than LLM judgment
- LLM-as-judge is appropriate for supplementary review of sampled responses but not for metric-tracked evaluation

Will be used as a supplementary signal in the 1% online sampling review process, not as the primary evaluation mechanism.

### No Offline Evaluation (Rely Only on Production Metrics)

Rejected. Production metrics measure system behavior but not model quality. PHI detection recall, for example, cannot be measured in production without knowing which PHI the scrubber missed (by definition). A golden dataset with known ground truth is the only way to measure recall accurately.

---

## Consequences

**Positive:**
- Prometheus + Grafana stays within the organization's infrastructure — no third-party data sharing
- Golden dataset evaluation provides ground-truth measurement of PHI and injection detection recall
- Metric labels are designed to be PHI-free from the start — no data scrubbing required for metrics pipeline
- Alert thresholds derived directly from blueprint KPIs — no interpretation gap between what was designed and what is monitored

**Negative:**
- Golden dataset requires maintenance: PHI entity patterns evolve, new injection techniques emerge, new request types need coverage. Quarterly review is an operational commitment.
- Self-hosted Prometheus + Grafana has higher operational setup cost than a SaaS dashboard
- Online sampling review requires a human reviewer process — this is an ongoing operational cost

**Neutral:**
- 1% sampling at 500K requests/month = 5,000 responses reviewed monthly — manageable with a small QA team

---

## Trade-offs

| Trade-off | Choice Made | What Was Sacrificed |
|---|---|---|
| Data sovereignty vs dashboard convenience | Self-hosted Prometheus/Grafana | Richer out-of-box SaaS dashboards |
| Ground truth vs automation | Golden dataset (human-labeled) | Faster iteration with LLM-as-judge |
| Coverage vs maintenance | 500-case golden dataset | Larger dataset with broader coverage |
| Online signal vs PHI risk | 1% de-identified sampling | Richer online evaluation with full context |
