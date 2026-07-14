"""Estimated per-token pricing for cost attribution.

Prices are USD per **million** tokens as (input, output) pairs. They are
approximate public list prices and exist so the dashboard can rank models by
cost per call - they are estimates, not billing data. When an event arrives
with token counts but no explicit cost_usd, the cost is estimated from this
table at ingestion time.

Extend or override with the MODEL_PRICING_JSON env var, e.g.:

    MODEL_PRICING_JSON='{"my-finetune": [1.0, 3.0]}'

Model names match by longest prefix on the lowercased name, so "gpt-4o"
covers "gpt-4o-2024-08-06" while "gpt-4o-mini" still wins for mini variants.
"""

import json
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# (input_usd_per_1m_tokens, output_usd_per_1m_tokens)
DEFAULT_PRICING = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1-mini": (1.10, 4.40),
    "o1": (15.00, 60.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-opus": (15.00, 75.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-3-sonnet": (3.00, 15.00),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    "llama-3": (0.60, 0.90),  # typical hosted-inference rates
    "mistral-large": (2.00, 6.00),
    "mistral-small": (0.20, 0.60),
}


def _load_pricing() -> dict:
    pricing = dict(DEFAULT_PRICING)
    raw = os.getenv("MODEL_PRICING_JSON")
    if raw:
        try:
            overrides = json.loads(raw)
            for name, pair in overrides.items():
                pricing[name.lower()] = (float(pair[0]), float(pair[1]))
        except (ValueError, TypeError, IndexError, KeyError) as e:
            logger.warning(f"Ignoring malformed MODEL_PRICING_JSON: {e}")
    return pricing


PRICING = _load_pricing()


def lookup_pricing(model_name: str) -> Optional[Tuple[float, float]]:
    """Longest-prefix match of a model name against the pricing table."""
    name = model_name.lower()
    best = None
    for prefix, pair in PRICING.items():
        if name.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, pair)
    return best[1] if best else None


def estimate_cost(
    model_name: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
) -> Optional[float]:
    """Estimated USD cost of one call, or None if unknown model / no tokens."""
    if input_tokens is None and output_tokens is None:
        return None
    pair = lookup_pricing(model_name)
    if pair is None:
        return None
    input_rate, output_rate = pair
    cost = ((input_tokens or 0) * input_rate + (output_tokens or 0) * output_rate) / 1_000_000
    return round(cost, 8)
