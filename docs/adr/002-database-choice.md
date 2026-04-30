# ADR-002: Database Choice for Audit Storage

**Status:** Accepted  
**Date:** 2026-04-30  
**Deciders:** Architect Agent, Security Agent, DevOps Agent  
**Blueprint reference:** FR-08 (Audit Logging), NFR (Audit write durability 99.999%, 7-year retention)

---

## Context

The control plane must write one immutable audit event per request. These events are:

- HIPAA-required: every AI interaction involving PHI must be logged
- Append-only: no record may ever be modified or deleted
- Compliance-queryable: admins need to filter by date, user, risk level, injection status
- Long-retention: 7-year minimum under HIPAA
- PHI-free: audit records must not contain raw PHI values
- Write-critical: if the audit write fails, the response must be suppressed

The audit store is not a general-purpose data store. It has a narrow, specific contract: structured events written by one service, read by the admin role for compliance queries.

Additional scale consideration: initial deployment targets 500K events/month. At > 10M events/month, storage and query performance must remain acceptable.

---

## Decision

**PostgreSQL** with the following enforcement mechanisms:

1. **Append-Only Trigger:** A database-level trigger on `audit_events` raises an exception for any `UPDATE` or `DELETE` statement, regardless of the calling role. This is enforced at the DB engine level, not at the application level.

2. **Row-Level Security (RLS):**
   - `cp_writer` service account: `INSERT` only on `audit_events`
   - `cp_admin` role: `SELECT` only on `audit_events`
   - No role has `UPDATE` or `DELETE` on `audit_events`
   - Database superuser is excluded from RLS (documented — rotation keys and backup processes are the only legitimate superuser operations)

3. **Monthly Range Partitioning (when > 10M events/month):**
   - Partition by `timestamp` column, one partition per calendar month
   - Old partitions can be archived (moved to cold storage) without touching the trigger logic
   - Query planner uses partition pruning to keep compliance queries fast

4. **Column-Level Encryption:**
   - `user_id` column: encrypted using pgcrypto with app-managed key
   - All other columns: rely on tablespace-level AES-256 encryption

5. **Schema:**
   See blueprint FR-08 for the full field list. No raw PHI fields exist in the schema — enforced by a pre-write validation check in `src/services/audit_logger.py`.

---

## Alternatives Considered

### Dedicated Audit SaaS (Datadog Audit Trail, Splunk)

Rejected for two reasons:
1. Cost scales linearly with event volume — at 10M events/month the cost exceeds PostgreSQL operational cost by a significant margin
2. PHI-adjacent audit data (user IDs, org IDs, risk levels) would flow to a third-party SaaS. While PHI is excluded from audit records by design, audit metadata is still sensitive healthcare data that should remain internal.

### Kafka + S3 (Event streaming + Object storage)

Considered viable for > 50M events/month but rejected for initial deployment. Kafka adds significant operational complexity (cluster management, consumer group management, offset tracking) that is not justified at the 500K events/month baseline. The router abstraction makes a future migration to Kafka possible without changing the service interface. Revisit at > 20M events/month.

### InfluxDB / TimescaleDB

Rejected. Time-series databases are optimized for high-cardinality metrics queries (e.g., "average latency per model over 24 hours"). HIPAA compliance queries are relational: "show me all HIGH-risk requests from user X in date range Y where injection was detected." PostgreSQL's `WHERE`, `JOIN`, and `GROUP BY` capabilities are a better fit.

### MongoDB (Document Store)

Rejected. Schema flexibility is a disadvantage here — the audit schema must be strictly enforced. MongoDB's document model does not natively support append-only enforcement equivalent to a PostgreSQL trigger. Compliance queries on MongoDB require careful indexing that PostgreSQL handles via standard B-tree indexes on the relevant columns.

### DynamoDB

Rejected. DynamoDB's primary access pattern is key-value or sparse index lookup. The compliance audit access pattern is range queries on timestamp + filters on multiple attributes — better served by a relational engine. DynamoDB also lacks native row-level security semantics.

---

## Consequences

**Positive:**
- PostgreSQL triggers provide DB-level append-only enforcement — no application bug can modify or delete audit records
- RLS ensures the service account physically cannot run UPDATE or DELETE even if a code bug attempts it
- Rich SQL querying covers all expected compliance use cases without custom query tooling
- Managed PostgreSQL (Cloud SQL) reduces operational overhead: backups, patching, HA failover handled by the platform
- Monthly partitioning is a non-breaking future migration — the schema and trigger are partition-aware by design

**Negative:**
- PostgreSQL on a single primary node is a write throughput ceiling (typically 10K–30K inserts/second depending on hardware). At 500K events/month this is well within limits; at 10M events/month, careful index management and partitioning are required
- Read replicas for admin queries require replica lag awareness — compliance queries should target the primary or a replica with acceptable lag
- Schema migrations require downtime or careful online migration (using `pg_rewrite` or `pglogical`) — the append-only trigger makes `ALTER TABLE` for existing columns safe but adding columns requires a migration

**Neutral:**
- 7-year retention at 500K events/month ≈ 42M rows ≈ ~20GB (estimated row size ~500 bytes). Well within Cloud SQL limits without archival. At 10M events/month, monthly partitioning and cold archival of partitions > 2 years old is required.

---

## Trade-offs

| Trade-off | Choice Made | What Was Sacrificed |
|---|---|---|
| Write throughput vs query richness | PostgreSQL (SQL) | Kafka/S3 can handle 10× higher event volume |
| Data sovereignty vs operational ease | Self-managed (Cloud SQL) vs SaaS | SaaS audit tools have better built-in dashboards |
| Schema strictness vs flexibility | Fixed schema + trigger enforcement | Cannot add ad-hoc fields to audit events without a migration |
| Simplicity now vs scale later | Single primary, partitioning as migration | Must revisit at > 10M events/month |
