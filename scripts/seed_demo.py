#!/usr/bin/env python3
"""Populate a running instance with realistic demo failure data.

An empty dashboard makes a poor first impression, so this script fills the
system with a plausible mix of failures across several models and failure
types. The data is deliberately correlated (low retrieval -> hallucination,
high latency -> timeout, low confidence -> confidence mismatch) so the pattern
and correlation views show something meaningful.

Usage:
    # with the stack running and your key exported
    export FAILURE_INVESTIGATOR_API_KEY=sk-...           # or pass --api-key
    python scripts/seed_demo.py --events 250 --days 7

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
}

SEVERITIES = ["critical", "high", "medium", "low"]


def make_event(now: datetime, days: int) -> dict:
    failure_type = random.choices(
        population=list(FIXTURES.keys()),
        weights=[30, 10, 12, 20, 13, 15],  # hallucination most common
        k=1,
    )[0]
    model_name, provider = random.choice(MODELS)
    prompt, response = random.choice(FIXTURES[failure_type])

    ts = now - timedelta(
        days=random.uniform(0, days),
        hours=random.uniform(0, 24),
    )

    # Baselines, then bend them so factors correlate with failure types.
    confidence = round(random.uniform(0.55, 0.95), 3)
    retrieval = round(random.uniform(0.5, 0.95), 3)
    latency = random.randint(200, 1500)
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

    return {
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "model_name": model_name,
        "provider": provider,
        "prompt": prompt,
        "response": response,
        "response_length": len(response),
        "latency_ms": latency,
        "confidence_score": confidence,
        "failure_type": failure_type,
        "failure_severity": severity,
        "retrieval_score": retrieval,
        "context_relevance": round(retrieval * random.uniform(0.8, 1.1), 3),
        "environment": random.choice(ENVIRONMENTS),
        "session_id": f"sess_{random.randint(1000, 9999)}",
        "tags": random.choice([["rag"], ["chat"], ["batch"], []]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo failure data.")
    parser.add_argument("--endpoint", default=os.getenv("FAILURE_INVESTIGATOR_ENDPOINT", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("FAILURE_INVESTIGATOR_API_KEY"))
    parser.add_argument("--events", type=int, default=250, help="Number of events to generate")
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

    print(f"\nDone. Seeded {sent} events across {len(MODELS)} models over {args.days} days.")
    print(f"Open the dashboard to explore: {endpoint.replace('8000', '8501')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
