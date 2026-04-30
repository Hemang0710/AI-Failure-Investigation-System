"""Example: Tracking OpenAI failures with the Failure Investigator SDK."""

import sys
import os
from datetime import datetime
from typing import Optional


# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sdk import FailureInvestigator

# You can also install with: pip install openai
# For testing without OpenAI API, we'll just mock the response


def simulate_llm_call(prompt: str, should_fail: bool = False) -> dict:
    """Simulate an LLM call (would be actual OpenAI call in production)."""

    if should_fail:
        return {
            "model": "gpt-4",
            "response": "",
            "latency_ms": 100,
            "confidence": 0.0,
            "failure_type": "empty_response",
        }

    return {
        "model": "gpt-4",
        "response": "The capital of France is Paris.",
        "latency_ms": 245,
        "confidence": 0.95,
        "failure_type": None,
    }


def main():
    """Example workflow: LLM call -> failure detection -> reporting."""

    # Initialize investigator
    investigator = FailureInvestigator(
        api_key="sk-demo-12345",  # From .env or use your key
        endpoint="http://localhost:8000",
        batch_size=5,  # Auto-flush after 5 events
    )

    print("🔍 AI Failure Investigator - OpenAI Example\n")
    print("=" * 50)

    # Test cases: successful and failed LLM calls
    test_cases = [
        {
            "prompt": "What is the capital of France?",
            "should_fail": False,
            "description": "Successful response",
        },
        {
            "prompt": "What is 2+2?",
            "should_fail": True,
            "description": "Empty response failure",
        },
        {
            "prompt": "What is the capital of Japan?",
            "should_fail": False,
            "description": "Successful response",
        },
        {
            "prompt": "Tell me a fact about the moon.",
            "should_fail": True,
            "description": "Hallucinated response",
        },
    ]

    failures_detected = 0

    for i, test in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test['description']}")
        print(f"Prompt: {test['prompt']}")

        # Simulate LLM call
        result = simulate_llm_call(test["prompt"], test["should_fail"])

        # Check for failures
        if result["failure_type"]:
            print(f"❌ Failure detected: {result['failure_type']}")

            # Report failure to investigator
            event = {
                "timestamp": datetime.utcnow(),
                "model_name": result["model"],
                "provider": "openai",
                "prompt": test["prompt"],
                "response": result["response"],
                "confidence_score": result["confidence"],
                "failure_type": result["failure_type"],
                "latency_ms": result["latency_ms"],
                "environment": "development",  # For testing
                "tags": ["example", "openai"],
            }

            investigator.report_failure(event)
            failures_detected += 1

        else:
            print(f"✅ Success: {result['response'][:50]}...")

    print("\n" + "=" * 50)
    print(f"\n📊 Summary:")
    print(f"  Total calls: {len(test_cases)}")
    print(f"  Failures detected: {failures_detected}")
    print(f"  Success rate: {((len(test_cases) - failures_detected) / len(test_cases) * 100):.1f}%")

    # Flush any remaining buffered events
    print("\n📤 Flushing buffered events...")
    investigator.flush()

    # Query the backend to show reported failures
    print("\n🔎 Querying reported failures...")
    failures = investigator.get_failures(
        model="gpt-4",
        hours=1,
        limit=10,
    )

    if failures:
        print(f"\n✅ Found {failures['pagination']['total_count']} failures in database:")
        for failure in failures['failures'][:3]:  # Show first 3
            print(f"  - {failure['failure_type']}: {failure['prompt'][:40]}...")
    else:
        print("⚠️  Could not query failures. Is backend running?")
        print("   Try: docker-compose up -d")

    # Query patterns
    print("\n🔍 Querying detected patterns...")
    patterns = investigator.get_patterns(model="gpt-4")

    if patterns and patterns['patterns']:
        print(f"✅ Found {patterns['summary']['total_patterns']} patterns:")
        for pattern in patterns['patterns'][:2]:
            print(f"  - {pattern['failure_type']}: {pattern['occurrence_count']} occurrences")
    else:
        print("ℹ️  No patterns detected yet (need more events)")

    # Close client
    investigator.close()

    print("\n✅ Example completed!")
    print("\n📊 Next steps:")
    print("  1. Open dashboard: http://localhost:8501")
    print("  2. Navigate to 'Failures' tab")
    print("  3. Filter by model='gpt-4'")
    print("  4. Check 'Patterns' for recurring issues")


if __name__ == "__main__":
    main()
