#!/usr/bin/env python3
"""Populate a running instance with realistic demo data.

An empty dashboard makes a poor first impression, so this script fills the
system with a plausible mix of traffic across several models, task types and
failure types. Most events are successes (failure_type omitted) so success
rates are meaningful; failures are deliberately correlated (low retrieval ->
hallucination, high latency -> timeout, low confidence -> confidence
mismatch) so the pattern and correlation views show something, and each
model is given task-specific strengths and weaknesses so the Model Fit page
tells a story (e.g. gpt-4o strong at code, claude-3-5-sonnet strong at RAG
QA, llama cheap but weak at structured extraction).

Usage:
    # with the stack running and your key exported
    export FAILURE_INVESTIGATOR_API_KEY=sk-...           # or pass --api-key
    python scripts/seed_demo.py --events 2000 --days 7

Requires: httpx  (pip install httpx)
"""

import argparse
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import httpx

MODELS = [
    ("gpt-4o", "openai"),
    ("gpt-4", "openai"),
    ("claude-3-5-sonnet", "anthropic"),
    ("gemini-1.5-pro", "google"),
    ("llama-3-70b", "meta"),
]

ENVIRONMENTS = ["production", "production", "production", "staging", "dev"]

# Baseline failure probability per model, and per-task overrides that give
# each model a distinct fit profile on the Model Fit page.
BASE_FAILURE_RATE = {
    "gpt-4o": 0.06,
    "gpt-4": 0.07,
    "claude-3-5-sonnet": 0.06,
    "gemini-1.5-pro": 0.09,
    "llama-3-70b": 0.12,
}

TASK_FAILURE_OVERRIDES = {
    ("gpt-4o", "code_generation"): 0.03,
    ("gpt-4o", "extraction"): 0.05,
    ("gpt-4", "code_generation"): 0.05,
    ("claude-3-5-sonnet", "rag_qa"): 0.03,
    ("claude-3-5-sonnet", "summarization"): 0.04,
    ("gemini-1.5-pro", "translation"): 0.04,
    ("gemini-1.5-pro", "rag_qa"): 0.11,
    ("llama-3-70b", "extraction"): 0.22,
    ("llama-3-70b", "rag_qa"): 0.16,
    ("llama-3-70b", "classification"): 0.08,
}

# Weighted task mix and typical token volumes (input range, output range).
TASKS = {
    "summarization": {"weight": 20, "in": (1500, 6000), "out": (150, 400)},
    "rag_qa": {"weight": 20, "in": (2000, 8000), "out": (150, 500)},
    "code_generation": {"weight": 18, "in": (800, 3000), "out": (300, 1200)},
    "extraction": {"weight": 15, "in": (1000, 4000), "out": (100, 300)},
    "classification": {"weight": 15, "in": (200, 1200), "out": (5, 30)},
    "translation": {"weight": 12, "in": (400, 2000), "out": (300, 1800)},
}

# Which failure types each task tends to produce.
TASK_FAILURE_TYPES = {
    "summarization": (["hallucination", "semantic_error", "timeout"], [55, 30, 15]),
    "rag_qa": (["hallucination", "retrieval_failure", "confidence_mismatch"], [45, 40, 15]),
    "code_generation": (["malformed_response", "semantic_error", "timeout"], [45, 35, 20]),
    "extraction": (["malformed_response", "empty_response", "semantic_error"], [55, 25, 20]),
    "classification": (["semantic_error", "confidence_mismatch", "empty_response"], [45, 40, 15]),
    "translation": (["semantic_error", "hallucination", "empty_response"], [55, 30, 15]),
}

# Typical latency ranges per model (ms).
MODEL_LATENCY = {
    "gpt-4o": (400, 900),
    "gpt-4": (1200, 3000),
    "claude-3-5-sonnet": (500, 1200),
    "gemini-1.5-pro": (600, 1400),
    "llama-3-70b": (300, 800),
}

# Prompt/response fixtures per failure type. Kept short; the point is variety,
# not realism of content.
FIXTURES = {
    "hallucination": [
        ("Who won the 2019 Nobel Prize in Physics?", "It was awarded to Jane Doe for quantum teleportation."),
        ("What is the capital of Australia?", "The capital of Australia is Sydney."),
        ("Summarize the plot of the 2024 film 'Echoes'.", "Echoes is a 2024 thriller directed by A. Nolan about time loops."),
    ],
    "empty_response": [
        ("Explain the CAP theorem.", ""),
        ("Write a haiku about autumn.", ""),
    ],
    "timeout": [
        ("Generate a 5000-word essay on macroeconomics.", "[partial output truncated]"),
        ("Refactor this 2000-line file.", "[no response before timeout]"),
    ],
    "semantic_error": [
        ("Explain recursion to a beginner.", "Recursion is when a function calls itself, recursively, recursively."),
        ("Give three tips for better sleep.", "Sleep more. Sleep well. Sleep."),
    ],
    "confidence_mismatch": [
        ("What is 17 * 24?", "I'm certain the answer is 388."),
        ("Is Pluto a planet?", "Definitely yes, Pluto is the 9th planet, no doubt."),
    ],
    "retrieval_failure": [
        ("What does our refund policy say about digital goods?", "I couldn't find relevant information."),
        ("Summarize the attached contract's liability clause.", "No matching context was retrieved."),
    ],
    "malformed_response": [
        ("Return the user record as JSON.", '{"name": "Ada", "email": '),
        ("Extract line items as a CSV.", "item1;;3,,\nitem2|7"),
    ],
}

SUCCESS_FIXTURES = [
    ("Summarize this quarterly report.", "Revenue grew 12% QoQ driven by the enterprise segment..."),
    ("Write a function to deduplicate a list.", "def dedupe(items):\n    return list(dict.fromkeys(items))"),
    ("Classify this ticket's sentiment.", "negative"),
    ("Translate 'good morning' to French.", "bonjour"),
    ("What does the onboarding doc say about SSO?", "SSO is configured via the identity provider settings page..."),
]

SEVERITIES = ["critical", "high", "medium", "low"]

TASK_NAMES = list(TASKS.keys())
TASK_WEIGHTS = [TASKS[t]["weight"] for t in TASK_NAMES]


def make_event(now: datetime, days: int) -> dict:
    task = random.choices(TASK_NAMES, weights=TASK_WEIGHTS, k=1)[0]
    model_name, provider = random.choice(MODELS)

    ts = now - timedelta(
        days=random.uniform(0, days),
        hours=random.uniform(0, 24),
    )

    input_tokens = random.randint(*TASKS[task]["in"])
    output_tokens = random.randint(*TASKS[task]["out"])
    latency = random.randint(*MODEL_LATENCY[model_name])

    event = {
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "model_name": model_name,
        "provider": provider,
        "task_type": task,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency,
        "environment": random.choice(ENVIRONMENTS),
        "session_id": f"sess_{random.randint(1000, 9999)}",
        "tags": random.choice([["rag"], ["chat"], ["batch"], []]),
    }

    failure_rate = TASK_FAILURE_OVERRIDES.get(
        (model_name, task), BASE_FAILURE_RATE[model_name]
    )
    if random.random() >= failure_rate:
        # Successful call: no failure_type.
        prompt, response = random.choice(SUCCESS_FIXTURES)
        event.update({
            "prompt": prompt,
            "response": response,
            "response_length": len(response),
            "confidence_score": round(random.uniform(0.75, 0.99), 3),
        })
        return event

    types, weights = TASK_FAILURE_TYPES[task]
    failure_type = random.choices(types, weights=weights, k=1)[0]
    prompt, response = random.choice(FIXTURES[failure_type])

    # Baselines, then bend them so factors correlate with failure types.
    confidence = round(random.uniform(0.55, 0.95), 3)
    retrieval = round(random.uniform(0.5, 0.95), 3)
    severity = random.choices(SEVERITIES, weights=[10, 25, 40, 25], k=1)[0]

    if failure_type in ("hallucination", "semantic_error"):
        confidence = round(random.uniform(0.15, 0.5), 3)
        retrieval = round(random.uniform(0.1, 0.45), 3)
    elif failure_type == "timeout":
        latency = random.randint(8000, 30000)
        severity = random.choice(["critical", "high"])
    elif failure_type == "confidence_mismatch":
        confidence = round(random.uniform(0.9, 0.99), 3)
    elif failure_type == "retrieval_failure":
        retrieval = round(random.uniform(0.05, 0.3), 3)

    event.update({
        "prompt": prompt,
        "response": response,
        "response_length": len(response),
        "latency_ms": latency,
        "confidence_score": confidence,
        "failure_type": failure_type,
        "failure_severity": severity,
        "retrieval_score": retrieval,
        "context_relevance": round(retrieval * random.uniform(0.8, 1.1), 3),
    })
    return event


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo traffic (successes + failures).")
    parser.add_argument("--endpoint", default=os.getenv("FAILURE_INVESTIGATOR_ENDPOINT", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("FAILURE_INVESTIGATOR_API_KEY"))
    parser.add_argument(
        "--events", type=int, default=2000,
        help="Number of events to generate (default 2000; the Model Fit page "
        "needs volume for per task x model samples)",
    )
    parser.add_argument("--days", type=int, default=7, help="Spread events over the last N days")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: provide --api-key or set FAILURE_INVESTIGATOR_API_KEY", file=sys.stderr)
        return 2

    if args.seed is not None:
        random.seed(args.seed)

    now = datetime.now(timezone.utc)
    events = [make_event(now, args.days) for _ in range(args.events)]
    failure_count = sum(1 for e in events if "failure_type" in e)

    headers = {"Authorization": f"Bearer {args.api_key}"}
    endpoint = args.endpoint.rstrip("/")
    sent = 0

    with httpx.Client(timeout=30) as client:
        for i in range(0, len(events), 100):  # API caps batches at 1000; 100 is polite
            batch = events[i : i + 100]
            resp = client.post(f"{endpoint}/api/v1/events", headers=headers, json={"events": batch})
            if resp.status_code != 202:
                print(f"ERROR: batch failed ({resp.status_code}): {resp.text}", file=sys.stderr)
                return 1
            sent += len(batch)
            print(f"  sent {sent}/{len(events)} events")

        # Nudge pattern analysis so the Patterns view is populated immediately.
        client.post(f"{endpoint}/api/v1/events/trigger-analysis", headers=headers, params={"hours": 720})

    print(
        f"\nDone. Seeded {sent} events ({failure_count} failures, "
        f"{sent - failure_count} successes) across {len(MODELS)} models, "
        f"{len(TASKS)} task types, over {args.days} days."
    )
    print(f"Open the dashboard to explore: {endpoint.replace('8000', '8501')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
