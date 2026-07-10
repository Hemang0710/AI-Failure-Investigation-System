# Contributing to AI Failure Investigation System

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to this project.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Commit Messages](#commit-messages)
- [Pull Requests](#pull-requests)
- [Reporting Issues](#reporting-issues)
- [Feature Requests](#feature-requests)

---

## Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inclusive environment for all contributors. We pledge to act and interact in ways that contribute to an open, welcoming, diverse, inclusive, and healthy community.

### Our Standards

Examples of behavior that contribute to a positive environment include:

- Using welcoming and inclusive language
- Being respectful of differing opinions, viewpoints, and experiences
- Giving and gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other community members

Examples of unacceptable behavior include:

- Harassing or discriminatory language
- Trolling, insulting, or derogatory comments
- Public or private harassment
- Publishing others' private information without consent
- Other conduct which could reasonably be considered inappropriate

---

## Getting Started

### 1. Fork the Repository

Click the "Fork" button on GitHub to create your own copy.

```bash
git clone https://github.com/YOUR-USERNAME/ai-failure-investigation-system.git
cd ai-failure-investigation-system
git remote add upstream https://github.com/ORIGINAL-OWNER/ai-failure-investigation-system.git
```

### 2. Create a Development Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

**Branch naming conventions:**
- `feature/` — New features
- `fix/` — Bug fixes
- `docs/` — Documentation updates
- `refactor/` — Code refactoring
- `test/` — Test additions

### 3. Set Up Development Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
cd backend
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your configuration

# Install pre-commit hooks (optional but recommended)
pip install pre-commit
pre-commit install
```

### 4. Make Your Changes

Edit files, test locally, and commit with clear messages.

---

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/my-feature
```

### 2. Make Changes

Edit the relevant files for your feature or fix.

### 3. Test Locally

```bash
# Run tests
pytest

# Run linting
flake8 .

# Format code
black .

# Type checking
mypy .
```

### 4. Commit Changes

```bash
git add .
git commit -m "feat: Add support for custom failure types"
```

### 5. Push to Your Fork

```bash
git push origin feature/my-feature
```

### 6. Create Pull Request

Go to GitHub and open a pull request from your branch to `main`.

---

## Coding Standards

### Python Code Style

We follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) and use automated tools:

- **Black** for code formatting
- **flake8** for linting
- **mypy** for type checking

### Running Formatting Tools

```bash
# Format code with Black
black backend/ dashboard/ sdk/

# Check with flake8
flake8 backend/ dashboard/ sdk/

# Type check with mypy
mypy backend/ --ignore-missing-imports
```

### Code Organization

#### Backend (FastAPI)

```python
# backend/routers/example.py
from fastapi import APIRouter, HTTPException
from auth import verify_api_key
from schemas import FailureEvent

router = APIRouter(prefix="/api/v1", tags=["example"])

@router.post("/endpoint")
async def endpoint(
    body: FailureEvent,
) -> dict:
    """
    Brief description of endpoint.

    Args:
        body: Request body

    Returns:
        Response data
    """
    # Authentication is enforced router-wide in main.py via
    # dependencies=[Depends(verify_api_key)]. If the endpoint needs the
    # caller's identity, add: api_key: APIKey = Depends(verify_api_key)
    # Implementation
    return {"status": "ok"}
```

#### Key Points

- Use type hints for all functions
- Document all public functions with docstrings
- Keep functions focused and testable
- Use meaningful variable names
- Add comments for complex logic

### Directory Structure

Keep files organized:
- **routers/** — API endpoint handlers
- **services/** — Business logic
- **models.py** — Database models
- **schemas.py** — Request/response schemas
- **auth.py** — Authentication logic
- **database.py** — Database configuration

---

## Testing

### Writing Tests

```bash
# Create test file: backend/tests/test_failures.py

import pytest
from httpx import AsyncClient
from main import app

@pytest.mark.asyncio
async def test_get_failures():
    """Test retrieving failures."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/failures",
            headers={"Authorization": "Bearer sk-test-12345"}
        )
        assert response.status_code == 200
        assert "failures" in response.json()

@pytest.mark.asyncio
async def test_report_failure():
    """Test reporting a failure event."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/events",
            json={
                "events": [{
                    "timestamp": "2026-05-13T12:00:00Z",
                    "model_name": "gpt-4",
                    "provider": "openai",
                    "prompt": "Test",
                    "response": "Test response",
                    "confidence_score": 0.5,
                    "failure_type": "hallucination",
                    "failure_severity": "high",
                    "latency_ms": 100
                }]
            },
            headers={"Authorization": "Bearer sk-test-12345"}
        )
        assert response.status_code == 200
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest backend/tests/test_failures.py

# Run with coverage
pytest --cov=backend

# Run with verbose output
pytest -v
```

### Test Requirements

- All new features must include tests
- Minimum 80% code coverage
- Tests must pass before PR approval
- Use descriptive test names

---

## Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat:` — A new feature
- `fix:` — A bug fix
- `docs:` — Documentation only changes
- `style:` — Changes that don't affect code meaning
- `refactor:` — Code refactoring without feature changes
- `perf:` — Performance improvements
- `test:` — Adding or updating tests
- `chore:` — Build process, dependencies, tools

### Examples

```
feat(api): Add correlation analysis endpoint

Add new /correlations endpoint that analyzes which factors
correlate with LLM failures. Uses scikit-learn for computation.

Closes #42
```

```
fix(auth): Fix API key validation logic

Previously allowed empty API keys. Now properly validates
bearer token and rejects empty values.

Fixes #38
```

```
docs: Update API documentation

Added examples for all endpoints and clarified authentication
requirements.
```

---

## Pull Requests

### PR Title

Use descriptive titles following Conventional Commits:

```
feat: Add pattern analysis engine
fix: Correct timestamp parsing in event ingestion
docs: Update README with deployment guide
```

### PR Description

Include:

1. **What**: Brief description of changes
2. **Why**: Motivation and context
3. **How**: Technical approach
4. **Testing**: How to test the changes
5. **Screenshots**: If UI changes (optional)

### Template

```markdown
## What
Added correlation analysis feature to identify factors causing LLM failures.

## Why
Users needed better insights into what causes failures. Correlation analysis 
helps identify patterns like "long prompts cause timeouts".

## How
- Added `/api/v1/correlations` endpoint
- Implemented correlation calculation using scikit-learn
- Added correlation visualization in dashboard
- Included comprehensive tests

## Testing
1. Start the system: `docker-compose up -d`
2. Add test data: `python scripts/add_test_data.py`
3. Visit http://localhost:8501
4. Go to Correlations page
5. Verify correlations are calculated and displayed

## Checklist
- [x] Code follows style guidelines
- [x] All tests pass
- [x] Documentation updated
- [x] No new warnings or errors
```

### PR Guidelines

- **One feature per PR** — Don't mix multiple features
- **Keep it focused** — Smaller PRs are easier to review
- **Update docs** — Include documentation for new features
- **Add tests** — All new code must have tests
- **Link issues** — Reference related GitHub issues

### Review Process

1. Maintainers will review your PR
2. Request changes if needed
3. Respond to feedback and push updates
4. PR is merged once approved

---

## Reporting Issues

### Before Creating an Issue

- Check if the issue already exists
- Search closed issues for similar problems
- Verify you're using the latest version

### Issue Template

Use the GitHub issue template with:

1. **Description**: What is the problem?
2. **Steps to Reproduce**: How to reproduce the issue
3. **Expected Behavior**: What should happen
4. **Actual Behavior**: What actually happens
5. **Environment**: Python version, OS, Docker, etc.
6. **Logs/Screenshots**: Any relevant logs or screenshots

### Example

```markdown
### Description
Correlation analysis fails when dataset is empty.

### Steps to Reproduce
1. Start system with no data
2. Go to Correlations page
3. See error

### Expected Behavior
Display message "No data available" instead of error

### Actual Behavior
500 Internal Server Error

### Environment
- OS: Windows 11
- Python: 3.11
- Docker: 25.0.3
```

---

## Feature Requests

### Before Requesting

- Check existing feature requests
- Consider if it aligns with project goals
- Think about implementation approach

### Feature Request Template

```markdown
### Title
Brief, descriptive title

### Problem
Why is this feature needed? What problem does it solve?

### Proposed Solution
How should the feature work?

### Use Case
Real-world example of how you'd use this feature

### Additional Context
Any other relevant information
```

---

## Project Maintainers

Primary maintainer:
- **Hemang Patel** (hemangpatel0710@gmail.com)

---

## Questions?

- **Email**: hemangpatel0710@gmail.com
- **GitHub Issues**: For bug reports and feature requests
- **Discussions**: For questions and conversations

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

**Thank you for contributing! Your help makes this project better for everyone.** 🙏

