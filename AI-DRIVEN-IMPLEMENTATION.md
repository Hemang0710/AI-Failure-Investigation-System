# AI-Driven Development Implementation Guide

This document guides **AI-assisted development** for building the AI Failure Investigation System using Claude and related tools.

---

## 1. Code Generation & Architecture Bootstrap

### When to Use AI for Code Generation
- ✅ **Boilerplate & scaffolding**: SDK wrapper classes, API endpoints, database schemas
- ✅ **Well-defined specs**: "Generate a FastAPI endpoint that accepts these 5 fields and validates them"
- ✅ **Standard patterns**: REST CRUD operations, test fixtures, CI/CD templates
- ❌ **Novel algorithms**: Failure detection heuristics, novel pattern recognition
- ❌ **Critical business logic**: Root cause inference, severity classification

### Effective AI Prompts for This Project

#### For SDK Development
```
Generate a Python SDK for capturing LLM failure events.

Requirements:
- Decorator pattern: @investigator.track() for easy integration
- Async batching: collect 100 events or 10 seconds, whichever first
- Fields to capture: {prompt, response, confidence, latency, metadata}
- Error handling: silently drop events if backend unavailable
- Config: endpoint URL, batch size, timeout

Output: Complete, production-ready class with docstrings and type hints.
```

#### For API Endpoints
```
Generate FastAPI endpoints for the Failure Investigation API.

Endpoints needed:
1. POST /events - accept batch failure events
2. GET /failures?type=hallucination&hours=24 - query failures
3. GET /patterns - get top failure patterns (cached)
4. POST /feedback - log user validation of failure classification

Include:
- OpenAPI documentation
- Request/response models (Pydantic)
- Basic auth
- Error handling with proper HTTP status codes
```

#### For Data Models
```
Design and generate SQLAlchemy ORM models for:
- FailureEvent table (indexed on timestamp, model_version, failure_type)
- FailurePattern table (unique signatures, occurrence count, last_seen)
- PromptVersion table (tracks prompt changes)
- Correlation table (factors associated with failures)

Include:
- Proper indexing for time-range queries
- Relationships between tables
- Migration templates for Alembic
```

---

## 2. Specification-First Development

### Create Living Specifications Before Coding

Each major component should have a `.spec.md` file:

```
📁 src/
├── collection/
│   ├── __init__.py
│   ├── investigator.py
│   └── investigator.spec.md       ← Specification
├── storage/
│   ├── models.py
│   ├── repository.py
│   └── storage.spec.md            ← Specification
└── analysis/
    ├── detector.py
    └── analysis.spec.md           ← Specification
```

**Example spec structure:**
```markdown
# Investigator SDK Spec

## Interface
- `FailureInvestigator(endpoint, batch_size=100, timeout=10)`
- `@investigator.track()` - decorator for LLM functions
- `investigator.report_failure(prompt, response, failure_type)` - explicit reporting
- `investigator.flush()` - force send pending events

## Behavior
- Captures: prompt, response, latency, model_name, custom_metadata
- Batches events asynchronously
- Retries with exponential backoff
- Drops events gracefully if backend unavailable (doesn't block caller)

## Example Usage
```python
investigator = FailureInvestigator(endpoint="http://localhost:8000")

@investigator.track()
def chat_with_llm(query: str) -> str:
    return llm.generate(query)
```

## Tests
- [ ] Decorator captures metadata correctly
- [ ] Events batched and sent within timeout
- [ ] Handles backend unavailability gracefully
- [ ] No performance impact on LLM calls
```

### Benefits
1. **Clarity**: AI can generate code from clear specs; humans review specs before coding
2. **Testability**: Specs define expected behavior explicitly
3. **Alignment**: Both you and Claude are working from the same target
4. **Parallelization**: Multiple AI agents can work on different specs simultaneously

---

## 3. AI-Driven Testing

### Test Generation from Specs
Ask Claude to generate tests alongside implementation:

```
Based on this collector.spec.md, generate comprehensive pytest tests covering:
- Decorator functionality and metadata capture
- Event batching (100 events or 10 seconds)
- Async/await behavior
- Error handling (network failures, timeouts)
- No-op behavior when instrumentation disabled

Include fixtures for mock LLM, mock backend, and test events.
```

### Mutation Testing for Critical Paths
For failure detection logic (which must be correct):
```
Generate mutation tests for the hallucination_detector.py module.

Mutations to test:
- Confidence threshold off-by-one
- Missing null checks
- Incorrect string comparisons
- Array bounds issues

Expected: 100+ mutations, 95%+ kill rate
```

---

## 4. Structured Iteration with AI

### The Specification → Code → Test → Review Loop

```
1. SPECIFY
   └─ Write or update .spec.md file
      (Human: clarity + requirements)

2. GENERATE
   └─ Ask Claude to implement from spec
      (AI: boilerplate + standard patterns)

3. REVIEW
   └─ You review generated code
      (Human: logic, edge cases, patterns)

4. TEST
   └─ Ask Claude to write comprehensive tests
      (AI: coverage + edge cases)

5. INTEGRATE
   └─ Merge into main codebase
      └─ Run full test suite
      └─ Check for regressions

6. REFINE
   └─ If issues found, update spec and loop
```

### Example Workflow

**Day 1: Specification**
```
Write: src/storage/storage.spec.md
- Define FailureEvent model
- Define query patterns needed
- Define indexing requirements
```

**Day 1: Code Generation**
```
Prompt Claude:
"Implement the Storage module based on storage.spec.md using SQLAlchemy.
Include migrations, type hints, and docstrings."
```

**Day 2: Code Review & Testing**
```
1. Review generated code (30 min)
2. Ask Claude to generate tests
3. Run tests locally
4. Merge if all pass
```

---

## 5. Analysis & Insights - Where AI Excels

### Leverage AI for Algorithm Design

For complex pieces like **failure pattern detection**, use AI as a research partner:

```
I need to detect recurring failure patterns in LLM responses.

Context:
- Failure types: hallucination, empty response, timeout, semantic error
- Need to identify: "This type of query always fails when using Model X"
- Scale: 100k+ failure events/day

Recommend:
1. Unsupervised clustering algorithm(s) to try
2. Feature engineering approach
3. How to handle rare vs. common patterns
4. Computational complexity considerations

Then help me implement the most promising approach.
```

### AI for Documentation & Runbooks

Ask Claude to generate:
- Troubleshooting guides for common failure patterns
- Runbooks for on-call engineers
- Architecture decision records (ADRs)
- Migration guides for breaking changes

---

## 6. Quality Gates & Automation

### Automated Checks (Use Claude to Generate)

```python
# checks/schema_validation.py
# Generated by Claude based on requirements
# Validates all FailureEvent entries match expected schema

# checks/test_coverage.py
# Ensures critical paths (failure detection) have >95% coverage

# checks/performance.py
# Benchmarks: event batching, storage queries, pattern detection
```

### Prompt for Quality Gate Generation
```
Create a pre-commit hook script that:
1. Validates all .spec.md files exist for new modules
2. Runs pytest with 85%+ coverage requirement for src/
3. Checks that new FailureEvent fields are indexed if used in queries
4. Lints Python code with ruff and mypy
5. Confirms no hardcoded API endpoints

Output as: .githooks/pre-commit (bash) + setup in Makefile
```

---

## 7. Documentation Generation

### Use AI to Keep Docs in Sync

Every time you update a spec or implement a component, ask Claude:
```
Update the API documentation for the /events and /failures endpoints
based on the latest FastAPI code. Include:
- Request/response schemas
- Example curl commands
- Error codes and meanings
- Rate limiting info
```

### Auto-Generate READMEs
```
Generate a comprehensive README.md for the collection/ module covering:
- Installation and setup
- Quick start example
- Configuration options
- Troubleshooting
- Contributing guidelines
```

---

## 8. Practical Example: End-to-End AI Implementation

### Task: Build the Collection SDK

**Step 1: Specification (You write)**
```markdown
# collection.spec.md

## FailureInvestigator Class

### Interface
```python
investigator = FailureInvestigator(
    endpoint: str,
    batch_size: int = 100,
    timeout_seconds: int = 10,
    enabled: bool = True
)
```

### Methods
- `track()` - decorator for tracking LLM functions
- `report_failure(...)` - explicit failure reporting
- `flush()` - force-send pending events

### Event Fields
- prompt (string)
- response (string)
- latency_ms (int)
- confidence (float, 0-1)
- model_name (string)
- failure_type (enum: hallucination|empty|timeout|semantic_error)
- metadata (dict)

### Guarantees
- Non-blocking (async)
- Graceful degradation if endpoint unavailable
- <1ms overhead on LLM calls
```

**Step 2: Generation (Ask Claude)**
```
Implement the FailureInvestigator class based on collection.spec.md
using Python 3.10+, aiohttp, and pydantic. Include:
- Type hints throughout
- Docstrings (Google style)
- Error handling
- Configuration validation
```

**Step 3: Testing (Ask Claude)**
```
Generate comprehensive pytest tests for FailureInvestigator covering:
[list the test cases from spec]
Include fixtures for mocked backend and LLM.
```

**Step 4: Integration (You execute)**
```bash
# Review generated code
# Run tests
# Integrate into src/collection/
```

---

## 9. When NOT to Use AI

- **Novel failure detection algorithms**: Experiment manually first
- **Complex multi-component interactions**: Sketch design first
- **Security-critical code**: Generate, then security-review carefully
- **Performance-critical hot paths**: Benchmark multiple approaches
- **Business logic with regulatory implications**: Implement with human oversight

---

## 10. Tools & Setup

### Recommended Dev Tools

```bash
# Code generation & iteration
Claude (via Claude Code / API)

# Specification management
- Markdown files in `docs/specs/`
- PR reviews require spec + implementation alignment

# Testing & validation
pytest, pytest-cov, pytest-benchmark
mypy for type checking
ruff for linting

# Documentation
mkdocs or Sphinx (auto-generated from docstrings)

# Database
PostgreSQL + TimescaleDB extension (for time-series)
Alembic for migrations

# API Documentation
FastAPI auto-generates OpenAPI/Swagger

# CI/CD
GitHub Actions (or similar) running:
- Linting + type checking
- Test suite (>85% coverage)
- Documentation build
- Performance regression tests
```

### Example Makefile
```makefile
.PHONY: spec code test docs review

spec:
	echo "Reviewed spec files in docs/specs/"
	# Use to track which specs need implementation

code:
	# Ask Claude to generate code from specs

test:
	pytest src/ --cov=src/ --cov-fail-under=85

docs:
	# Generate API docs from FastAPI + docstrings

review:
	# Code review checklist
	mypy src/
	ruff check src/
```

---

## Summary

**AI Shines At:**
- Boilerplate code (models, APIs, tests)
- Documentation (READMEs, guides, examples)
- Refactoring & optimization suggestions
- Pattern generation (from specs)

**Keep Human For:**
- Architecture decisions
- Algorithm design & validation
- Security & compliance reviews
- Specs & requirements clarity
- Code review & testing

**Best Workflow:**
```
Spec (Human) → Generate (AI) → Review (Human) → Test (AI) → Integrate (Human)
```
