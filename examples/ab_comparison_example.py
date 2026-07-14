"""Example: shadow A/B comparison of two models on identical live prompts.

The primary model serves every request; a sampled fraction also runs against
a candidate model in shadow mode. Both outcomes are reported on the same
prompts, so the dashboard's Model Fit page compares the two models on
identical traffic - the strongest evidence for "model X is better at task Y".

Run with the stack up:
    export FAILURE_INVESTIGATOR_API_KEY=sk-...
    python examples/ab_comparison_example.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdk import create_investigator  # noqa: E402


def call_primary(prompt: str) -> dict:
    # Replace with your real LLM call (OpenAI, Anthropic, ...).
    return {"response": f"primary answer to: {prompt}", "input_tokens": 120, "output_tokens": 40}


def call_candidate(prompt: str) -> dict:
    # Replace with the model you are evaluating.
    return {"response": f"candidate answer to: {prompt}", "input_tokens": 120, "output_tokens": 35}


def classify(response_text: str):
    """Your quality check: return a failure_type or None for success."""
    if not response_text.strip():
        return "empty_response"
    if "sorry, i cannot" in response_text.lower():
        return "semantic_error"
    return None


def main():
    investigator = create_investigator()

    comparison = investigator.compare_models(
        primary_model="gpt-4o",
        candidate_model="claude-3-5-sonnet",
        task_type="rag_qa",
        sample_rate=0.5,       # shadow half the requests (use ~0.1 in prod)
        classify=classify,
        primary_provider="openai",
        candidate_provider="anthropic",
    )

    prompts = [
        "What does the refund policy say about digital goods?",
        "Summarize the Q3 incident report.",
        "Which plan includes SSO?",
    ]
    for prompt in prompts:
        result = comparison.run(prompt, primary_fn=call_primary, candidate_fn=call_candidate)
        print(f"served: {result['response']!r}")

    investigator.close()  # flush buffered events
    print(f"\nDone. Filter events by tag '{comparison.comparison_id}' or open the Model Fit page.")


if __name__ == "__main__":
    main()
