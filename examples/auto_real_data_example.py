"""Part B in practice: real-data auto-instrumentation against the hosted backend.

This is the exact two-line setup any app needs (DEPLOY.md Part B). Run it once
to see real telemetry flow into your hosted dashboard:

    # PowerShell
    $env:FAILURE_INVESTIGATOR_ENDPOINT = "https://aifis-backend.onrender.com"
    $env:FAILURE_INVESTIGATOR_API_KEY  = "<BOOTSTRAP_API_KEY from Render>"
    $env:OPENAI_API_KEY                = "<your OpenAI key>"   # optional
    python examples/auto_real_data_example.py

With an OPENAI_API_KEY set, the calls below succeed and are recorded as
successes (model, tokens, latency, cost). Without one, the calls raise real
authentication errors — which is telemetry too: they are captured and reported
as failures. Either way, the dashboard stops being empty.
"""

import os
import sys

# Only needed because this script lives inside the repo. In your own app,
# vendor the sdk/ folder (or add this repo to PYTHONPATH) and import the same way.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sdk import auto

# ── The two lines from DEPLOY.md B1 ─────────────────────────────────────────
# Reads FAILURE_INVESTIGATOR_API_KEY / FAILURE_INVESTIGATOR_ENDPOINT from env.
auto.init(default_task_type="chat")
# ────────────────────────────────────────────────────────────────────────────

# Everything below is a stand-in for YOUR application code — note that none of
# it mentions the investigator: instrumentation is invisible at call sites.


def main() -> None:
    try:
        from openai import OpenAI
    except ImportError:
        print("The 'openai' package is not installed. Run: pip install openai")
        print("(In your real app, whatever OpenAI/Anthropic calls you already "
              "make are instrumented — no example needed.)")
        return

    client = OpenAI()  # uses OPENAI_API_KEY from the environment

    prompts = [
        "In one sentence, what does an LLM observability tool do?",
        "Name three common failure modes of LLM applications.",
    ]

    for prompt in prompts:
        print(f"\n→ {prompt}")
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
            )
            print(f"✅ {resp.choices[0].message.content[:120]}")
        except Exception as exc:  # a real failure — captured automatically
            print(f"❌ Call failed ({type(exc).__name__}) — recorded as a failure event")

    auto.shutdown()  # flush the background queue before the script exits
    print("\nDone. Open the dashboard → Overview/Failures to see these events.")


if __name__ == "__main__":
    main()
