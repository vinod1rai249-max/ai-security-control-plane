# AI Product Factory Operating Guide

## Purpose

This guide explains how to use your `CLAUDE.md`, agent teams, reusable skills, hooks, Codex, Google AI Studio, and optional models like Kimi K2.6 to build real full-stack AI products in a professional, repeatable way.

---

## 1. Core Operating Model

Use this setup as an AI product factory:

```text
CLAUDE.md = Constitution
AGENTS.md = Team roles
Skills = Repeatable playbooks
Hooks = Quality gates
Claude = Architect + reviewer
Codex = Fast implementer
Google AI Studio = Prompt/model lab
Kimi K2.6 = Cost-efficient long-horizon coding/model option
```

The main rule is simple:

```text
Blueprint first → Approval gate → Build modules → Validate → Deploy → Monitor
```

No coding should happen until the blueprint is approved.

---

## 2. Recommended Project Structure

```text
your-project/
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
├── .claude/
│   ├── skills/
│   │   ├── blueprint-review/SKILL.md
│   │   ├── backend-fastapi/SKILL.md
│   │   ├── frontend-ui/SKILL.md
│   │   ├── llm-router/SKILL.md
│   │   ├── rag-engine/SKILL.md
│   │   ├── guardrails/SKILL.md
│   │   ├── observability/SKILL.md
│   │   ├── evaluation/SKILL.md
│   │   └── deployment/SKILL.md
│   ├── agents/
│   │   ├── architect.md
│   │   ├── backend-engineer.md
│   │   ├── frontend-engineer.md
│   │   ├── ai-engineer.md
│   │   ├── security-reviewer.md
│   │   ├── qa-engineer.md
│   │   └── devops-engineer.md
│   └── hooks/
│       ├── pre-edit-check.sh
│       ├── post-edit-format.sh
│       ├── test-after-change.sh
│       └── security-scan.sh
├── src/
├── tests/
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## 3. Mandatory Blueprint Gate

Create this file:

```text
docs/blueprint_status.md
```

Template:

```md
# Blueprint Status

Status: NOT_APPROVED

Scores:
- Clarity:
- Completeness:
- Scalability:
- Cost Efficiency:
- Reliability:

Decision:
- APPROVED / NOT_APPROVED

Reviewer:
- Architect Agent

Notes:
-
```

Rule:

```text
If Status is not APPROVED, no coding is allowed.
```

This prevents random coding, wasted tokens, and poor architecture.

---

## 4. Agent Team Structure

Do not use all agents at once. Use them based on phase.

### Planning Team

```text
Architect Agent
Security Agent
AI Engineer Agent
QA Agent
```

Responsibilities:

- Problem definition
- Requirements
- User journey
- Data flow
- API contract
- Failure scenarios
- KPIs
- ADRs
- Blueprint scoring

### Build Team

```text
Backend Agent
Frontend Agent
AI Engineer Agent
Observability Agent
DevOps Agent
```

Responsibilities:

- FastAPI backend
- Streamlit/React frontend
- LLM router
- RAG engine
- Guardrails
- Logging and metrics
- Deployment

### Review Team

```text
QA Agent
Security Agent
Architect Agent
```

Responsibilities:

- Tests
- Security review
- Evaluation
- Cost review
- Architecture compliance

---

## 5. Sequential vs Parallel Work

### Sequential Work

Use sequential work when decisions depend on earlier outputs.

```text
Blueprint → Architecture → API Contract → Backend → Frontend → QA → Deploy
```

Use this for:

- New products
- Healthcare apps
- Finance apps
- Enterprise systems
- High-risk systems

### Parallel Work

Use parallel work only after blueprint approval.

```text
Backend Agent      → API implementation
Frontend Agent     → UI implementation
AI Engineer Agent  → LLM router/RAG
DevOps Agent       → Docker/deployment
QA Agent           → Test plan
```

Use this for:

- Faster delivery
- Independent modules
- Approved architecture
- Clear contracts

Never run parallel agents before the blueprint is approved.

---

## 6. Skills as Commands

Each skill must produce a fixed output.

### blueprint-review/SKILL.md

Purpose:

```text
Review and improve the product blueprint before implementation.
```

Must output:

```text
- Problem definition
- Functional requirements
- Non-functional requirements
- User journey
- Data flow
- API contract
- Failure scenarios
- KPIs
- ADR
- Scores
- Approval decision
```

### backend-fastapi/SKILL.md

Purpose:

```text
Generate FastAPI backend modules from approved API contract only.
```

Rules:

```text
- Do not invent endpoints
- Use Pydantic request/response models
- Use service classes
- Add structured logging
- Add tests
- Follow approved architecture
```

### guardrails/SKILL.md

Purpose:

```text
Implement input validation, prompt injection detection, policy engine, output validation, confidence scoring, fallback, and audit logging.
```

### evaluation/SKILL.md

Purpose:

```text
Create offline and online evaluation plan.
```

Must include:

```text
- Golden dataset
- Accuracy checks
- Hallucination checks
- Cost checks
- Latency checks
- Regression tests
```

---

## 7. Hooks as Quality Gates

Hooks enforce rules automatically.

### pre-edit-check.sh

Purpose:

```text
Block coding if blueprint is not approved.
```

Example:

```bash
#!/bin/bash
if ! grep -q "Status: APPROVED" docs/blueprint_status.md; then
  echo "❌ Blueprint is not approved. Coding is blocked."
  exit 1
fi

echo "✅ Blueprint approved. Proceeding."
```

### post-edit-format.sh

Purpose:

```text
Run formatting after code edits.
```

Example:

```bash
#!/bin/bash
black src tests || true
ruff check src tests --fix || true
```

### test-after-change.sh

Purpose:

```text
Run tests after changes.
```

Example:

```bash
#!/bin/bash
pytest tests -q
```

### security-scan.sh

Purpose:

```text
Detect secrets and unsafe files.
```

Example:

```bash
#!/bin/bash
if grep -R "sk-\|OPENAI_API_KEY=\|ANTHROPIC_API_KEY=" . --exclude-dir=.git; then
  echo "❌ Possible secret detected."
  exit 1
fi

echo "✅ No obvious secrets found."
```

---

## 8. Tool Usage Strategy

### Claude Code

Use for:

```text
- Blueprint review
- Architecture
- ADRs
- Multi-file reasoning
- Final review
- Hook setup
- Refactoring strategy
```

Do not use Claude Code for every small coding task if cost is a concern.

Best prompt:

```text
Read CLAUDE.md first.
Run blueprint-review skill.
Do not code until docs/blueprint_status.md is APPROVED.
After approval, create architecture.md and ADRs.
Then create small implementation tasks for Codex.
```

### Codex

Use for:

```text
- Small module implementation
- Bug fixes
- Tests
- Refactoring
- PR-style tasks
```

Best prompt:

```text
Implement only this approved module:

File:
Requirement:
Input schema:
Output schema:
Tests required:

Rules:
- Follow CLAUDE.md and AGENTS.md
- Do not change architecture
- Do not invent endpoints
- Use Pydantic validation
- Add logging and tests
```

### Google AI Studio

Use for:

```text
- Prompt testing
- Gemini model comparison
- Structured JSON output validation
- Long-context experiments
- Guardrail prompt testing
- UI/app idea prototyping
```

Best prompt:

```text
Test this AI response prompt.
Return only valid JSON matching this schema.
Check if the response follows safety, guardrails, and domain rules.
Identify hallucination risk and improvement suggestions.
```

### Kimi K2.6

Use Kimi K2.6 as a cost-efficient long-horizon coding and agentic coding option when available through your provider or local/open-source setup.

Best use cases:

```text
- Long coding tasks
- Codebase-wide refactoring
- DevOps scripts
- Performance optimization
- Multi-step implementation
- Alternative to expensive premium coding models
```

Do not use it blindly for high-risk healthcare/finance final answers unless your guardrails, validation, and evaluation pipeline are active.

Recommended role:

```text
Kimi K2.6 = Cost-efficient coding worker / long-horizon engineering assistant
Claude = Architect and final reviewer
Google AI Studio/Gemini = Prompt and structured output lab
Codex = Module-level implementation worker
```

---

## 9. End-to-End Product Workflow

### Phase 1: Product Idea

Input:

```text
I want to build [product idea] for [target users].
```

Output:

```text
docs/blueprint.md
docs/blueprint_status.md
```

### Phase 2: Blueprint Review

Claude runs blueprint-review skill.

If score < 8:

```text
Improve blueprint. Do not code.
```

If score >= 8:

```text
Update docs/blueprint_status.md to APPROVED.
```

### Phase 3: Architecture

Create:

```text
docs/architecture.md
docs/adr/001-model-selection.md
docs/adr/002-database-choice.md
docs/adr/003-deployment-strategy.md
```

### Phase 4: Prompt and Model Testing

Use Google AI Studio to test:

```text
- Prompt format
- JSON response schema
- Guardrail behavior
- Gemini model quality
- Cost/performance
```

### Phase 5: Implementation

Use Codex or Kimi K2.6 for small tasks:

```text
- Pydantic models
- FastAPI routes
- Services
- Tests
- UI pages
- Docker files
```

### Phase 6: Hooks Validate

Run:

```text
- Formatting
- Tests
- Security scan
- Blueprint gate
```

### Phase 7: Final Review

Claude reviews:

```text
- Architecture compliance
- Guardrails
- Evaluation
- Cost optimization
- Security
- Deployment readiness
```

### Phase 8: Deployment

DevOps Agent handles:

```text
- Docker
- Cloud Run
- Streamlit Cloud
- Environment variables
- Monitoring
```

### Phase 9: Monitor and Improve

Track:

```text
- Latency
- Cost
- Failures
- User feedback
- Model quality
- Drift
```

---

## 10. Practical Example: Healthcare Lab Report Assistant

### Blueprint

Problem:

```text
Patients need safe, understandable explanations of lab results.
```

Target users:

```text
Patients, care coordinators, diagnostic lab support teams.
```

Success:

```text
Safe explanations, low hallucination, clear next-step guidance, low cost.
```

### Approved Architecture

```text
Streamlit UI
↓
FastAPI Backend
↓
Pydantic Validation
↓
Rules Engine
↓
RAG Engine
↓
LLM Router
↓
Output Guardrails
↓
Audit Logs
```

### Model Strategy

```text
Rules first
Gemini/OpenRouter/Kimi for cheap explanation
Claude only for complex review
```

### Guardrail

```text
No final diagnosis.
Explain ranges and suggest consulting a qualified clinician for concerning results.
```

---

## 11. Cost-Saving Strategy

Use expensive models only for:

```text
- Architecture
- Final review
- Complex debugging
- High-risk reasoning
```

Use cheaper models for:

```text
- Drafting code
- Writing tests
- UI copy
- Structured outputs
- Simple explanations
```

Use deterministic code for:

```text
- Validation
- Lab ranges
- Routing
- Calculations
- Policy checks
```

---

## 12. Golden Rule

```text
Never ask an AI tool to “build the full app.”

Always ask it to implement one approved module from an approved blueprint.
```

That is how you reduce cost, improve quality, and build like a professional product team.

