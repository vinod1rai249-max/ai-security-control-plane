# ADR-005: Deployment Strategy

**Status:** Accepted  
**Date:** 2026-04-30  
**Deciders:** Architect Agent, DevOps Agent, Security Agent  
**Blueprint reference:** NFR (Availability 99.9%, Throughput 100 concurrent, AES-256 at rest, TLS 1.3 in transit)

---

## Context

The control plane requires a deployment target that satisfies:

1. **HIPAA Technical Safeguards:** Encryption at rest (AES-256), encryption in transit (TLS 1.3), access controls, audit controls
2. **Availability:** 99.9% uptime (8.7 hours downtime/year)
3. **Scalability:** Horizontal scaling from 100 to 500+ concurrent requests
4. **Security isolation:** PHI token store and audit DB must not be accessible from the internet
5. **Operational efficiency:** Small initial team; managed services reduce operational overhead
6. **Zero-downtime deployments:** Clinical workflows cannot tolerate maintenance windows

Deployment decisions have long-term operational consequences. The initial target must be correct for the 12–18 month horizon; re-platforming later is expensive.

---

## Decision

### Platform: Google Cloud Platform (GCP)

GCP is selected as the deployment platform. Key reasons:
- GCP HIPAA BAA (Business Associate Agreement) covers the services used in this architecture
- Managed services (Cloud Run, Cloud SQL, Memorystore, Secret Manager) reduce operational overhead
- Cloud Run provides serverless container execution with automatic scaling, no cluster management

### Compute: Google Cloud Run

Control plane service deployed as a Docker container on Cloud Run.

| Property | Configuration |
|---|---|
| Container | Python 3.11, slim base image, multi-stage build |
| Autoscaling | Min instances: 2 (warm, avoid cold starts in production); Max instances: 50 |
| Concurrency | 10 requests per instance (CPU-bound due to Presidio NER) |
| CPU | 2 vCPU per instance |
| Memory | 2GB per instance (sentence-transformer model loaded at startup) |
| Timeout | 120s (max request timeout, covers HIGH-tier LLM calls at 60s + overhead) |
| Region | Single region initially (us-central1); multi-region if uptime SLA tightened |
| Ingress | Internal + Cloud Load Balancer (HTTPS external) |
| Egress | VPC connector → private VPC (for DB/Redis access) |

**Why Cloud Run over Kubernetes:**
- No cluster management, node upgrades, or pod scheduling
- Pay-per-request billing model is appropriate at initial scale (500K requests/month)
- Auto-scales to zero in non-production environments (staging, dev) — cost savings
- At > 5M requests/month or with strict latency requirements for cold starts, GKE Autopilot becomes the migration path

### Database: Google Cloud SQL (PostgreSQL 15)

| Property | Configuration |
|---|---|
| Version | PostgreSQL 15 |
| Tier | db-custom-2-8192 (2 vCPU, 8GB RAM) |
| Storage | 100GB SSD, auto-grow enabled |
| Encryption | CMEK (Customer-Managed Encryption Key) via Cloud KMS |
| HA | High Availability with automatic failover (regional) |
| Backup | Daily automated backups, 7-year retention configured |
| Read replicas | 1 read replica for admin audit queries (writes to primary only) |
| Network | Private IP only (VPC); no public IP |
| Connection | Cloud SQL Auth Proxy (IAM-authenticated, no password in connection string) |

### Cache: Google Cloud Memorystore (Redis 7)

| Property | Configuration |
|---|---|
| Version | Redis 7 |
| Tier | Standard (HA with automatic failover) |
| Capacity | 1GB (sufficient for 500 concurrent sessions × ~2KB token map each) |
| Encryption | In-transit (TLS) + at-rest (GCP-managed) |
| Network | Private IP only (VPC) |
| Auth | Redis AUTH token stored in Secret Manager |

### Secrets: Google Secret Manager

All secrets (LLM API keys, DB passwords, Redis AUTH, JWT signing keys) stored in Secret Manager:
- Access via IAM: control plane service account has `roles/secretmanager.secretAccessor` for specific secrets only
- Secret versions: previous version retained for 1 rotation cycle
- Rotation: LLM API keys every 90 days (automated via Cloud Scheduler + Cloud Function); JWT signing keys every 30 days

### Container Build: Multi-Stage Dockerfile

```
Stage 1 (builder): python:3.11-slim + install dependencies + compile Presidio models
Stage 2 (runtime): python:3.11-slim + copy only app code and installed packages
```

Result: ~800MB runtime image (dominated by sentence-transformer model and Presidio en_core_web_lg). No build tools, test dependencies, or secrets in the runtime image.

### CI/CD: GitHub Actions + Cloud Build

```
PR opened → lint + type check + unit tests → pass to merge
Merge to main → integration tests → build image → push to Artifact Registry → deploy to staging
Staging smoke tests pass → manual approval gate → deploy to production (Cloud Run traffic migration, 10% → 100%)
```

Traffic migration (10% → 100%) provides a zero-downtime deployment path with the ability to roll back to the previous revision in < 60 seconds.

### Environments

| Environment | Compute | DB | Redis | Secrets | LLM Keys |
|---|---|---|---|---|---|
| `local` | Docker Compose | PostgreSQL container | Redis container | `.env.local` (not committed) | Test keys with rate limits |
| `staging` | Cloud Run (min=1) | Cloud SQL (shared) | Memorystore (basic) | Secret Manager | Test keys |
| `production` | Cloud Run (min=2) | Cloud SQL (HA) | Memorystore (standard HA) | Secret Manager | Production keys |

---

## Alternatives Considered

### Google Kubernetes Engine (GKE Autopilot)

Viable option, rejected for initial deployment due to higher operational surface area. GKE Autopilot manages node provisioning but still requires namespace configuration, pod security policies, network policies, and ingress configuration. Cloud Run provides the same container execution model with less configuration. Revisit at > 5M requests/month or if complex inter-service networking is required.

### AWS ECS on Fargate

Viable equivalent to Cloud Run. Rejected in favor of GCP because GCP's managed service suite (Cloud SQL, Memorystore, Secret Manager) integrates more cohesively for this architecture. Choosing one cloud provider for all managed services reduces cross-cloud IAM complexity. Both GCP and AWS have signed HIPAA BAAs.

### Azure Container Apps

Similar to Cloud Run. Rejected — no strong advantage over Cloud Run for this architecture, and the team's familiarity with GCP reduces operational risk.

### Self-Hosted (On-Premise / Bare Metal)

Rejected. On-premise deployment removes access to managed services, increases operational overhead (hardware, patching, HA configuration), and makes HIPAA compliance documentation more complex. Cloud providers with signed BAAs are the standard for healthcare SaaS.

### Serverless Functions (Cloud Functions / Lambda)

Rejected. The control plane service loads large models at startup (Presidio NER, sentence-transformer). Cold starts with these models would take 10–30 seconds — unacceptable for a clinical workflow. Cloud Run with minimum instances set to 2 keeps instances warm.

---

## Consequences

**Positive:**
- Cloud Run auto-scaling handles load spikes without manual intervention
- Managed Cloud SQL HA provides automatic failover — supports 99.9% availability target
- No cluster management overhead — DevOps Agent focuses on application config, not infrastructure
- CMEK (customer-managed encryption keys) gives the organization control over data encryption — a HIPAA technical safeguard
- Traffic migration deployment model means zero-downtime deploys and fast rollback
- Cloud SQL Auth Proxy eliminates DB passwords from the application environment

**Negative:**
- Cloud Run cold start with Presidio + sentence-transformer models: 15–30 seconds from zero instances. Mitigated by `min-instances=2` in production, but staging environments will experience cold starts.
- Single GCP region dependency for initial deployment — a regional GCP outage could impact availability. Multi-region failover is a future milestone.
- Cloud Run concurrency limit (10 requests/instance) means more instances are needed for high concurrency than a thread-per-request server. At 100 concurrent requests: 10 instances minimum.
- GCP vendor dependency for core infrastructure — migration to another cloud requires re-platforming Cloud SQL, Memorystore, and Secret Manager integrations

**Neutral:**
- GCP costs at 500K requests/month are predictable and within typical SaaS operational budgets; detailed cost modeling should be done at > 2M requests/month

---

## Trade-offs

| Trade-off | Choice Made | What Was Sacrificed |
|---|---|---|
| Operational simplicity vs control | Cloud Run (managed) vs GKE | Fine-grained container scheduling control |
| Cloud portability vs integration depth | GCP-native services | Multi-cloud optionality |
| Warm instances vs cost | min=2 in production | Zero-cost cold-start savings |
| Single-region vs HA geo | Single region initially | Geographic redundancy |
| Automated rotation vs simplicity | Secret Manager + rotation | Manual key management is simpler short-term |
