"""Main SDK client for reporting and querying failures."""

import httpx
import logging
import random
import threading
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from functools import wraps

logger = logging.getLogger(__name__)


class FailureInvestigator:
    """Client for reporting LLM failures and querying insights."""

    def __init__(
        self,
        api_key: str,
        endpoint: str = "http://localhost:8000",
        timeout: int = 30,
        batch_size: int = 10,
        flush_interval: int = 5,
    ):
        """
        Initialize the Failure Investigator client.

        Args:
            api_key: API key for authentication
            endpoint: Backend API endpoint (default: http://localhost:8000)
            timeout: Request timeout in seconds
            batch_size: Maximum events per batch before auto-flush
            flush_interval: Seconds between automatic batch flushes
        """
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.events_buffer = []

        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

        # Start background flush thread
        self._stop_event = threading.Event()
        self._flush_thread = threading.Thread(
            target=self._background_flush_loop,
            daemon=True,
        )
        self._flush_thread.start()

    def _background_flush_loop(self):
        """Background thread that periodically flushes buffered events."""
        while not self._stop_event.wait(self.flush_interval):
            if self.events_buffer:
                self.flush()

    async def async_client(self):
        """Get async HTTP client."""
        return httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )

    def report_failure(self, event: Dict[str, Any]) -> bool:
        """
        Report a single failure event.

        Args:
            event: Failure event dict with keys: timestamp, model_name, prompt, response, etc

        Returns:
            True if successful, False otherwise
        """
        try:
            self.events_buffer.append(event)

            if len(self.events_buffer) >= self.batch_size:
                self.flush()

            return True

        except Exception as e:
            logger.error(f"Failed to report failure: {str(e)}")
            return False

    def report_success(
        self,
        model_name: str,
        task_type: Optional[str] = None,
        provider: Optional[str] = None,
        latency_ms: Optional[int] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        sample_rate: float = 1.0,
        **extra: Any,
    ) -> bool:
        """
        Report a successful LLM call (an event with no failure_type).

        Success events are what make per-model and per-task success rates
        trustworthy - without them the system only sees failures. On
        high-volume paths, pass sample_rate (e.g. 0.1 to record 1 in 10);
        note that sampled success counts understate true volume by that
        factor, so keep the rate consistent per model/task when comparing.

        Args:
            model_name: Model that served the call
            task_type: Task category (summarization, code_generation,
                extraction, rag_qa, classification, translation, agentic,
                creative_writing, chat, other)
            provider: Provider name (openai, anthropic, ...)
            latency_ms: Call latency
            input_tokens / output_tokens: Token counts; the backend estimates
                cost_usd from these when cost_usd is not given
            cost_usd: Exact cost if known
            sample_rate: Probability of recording this event (0.0-1.0]
            **extra: Any other event fields (session_id, tags, prompt, ...)

        Returns:
            True unless buffering failed (a sampled-out event returns True)
        """
        if sample_rate < 1.0 and random.random() > sample_rate:
            return True

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "model_name": model_name,
            "prompt": "",
            "response": "",
            **extra,
        }
        for key, value in (
            ("task_type", task_type),
            ("provider", provider),
            ("latency_ms", latency_ms),
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("cost_usd", cost_usd),
        ):
            if value is not None:
                event[key] = value
        event.pop("failure_type", None)  # success is defined by its absence

        return self.report_failure(event)

    def report_failures(self, events: List[Dict[str, Any]]) -> bool:
        """
        Report multiple failure events in batch.

        Args:
            events: List of failure event dicts

        Returns:
            True if successful, False otherwise
        """
        try:
            self.events_buffer.extend(events)

            if len(self.events_buffer) >= self.batch_size:
                self.flush()

            return True

        except Exception as e:
            logger.error(f"Failed to report failures: {str(e)}")
            return False

    def flush(self, retries: int = 3) -> bool:
        """
        Send all buffered events to the backend with exponential backoff retry.

        Args:
            retries: Number of retry attempts

        Returns:
            True if successful, False otherwise
        """
        if not self.events_buffer:
            return True

        for attempt in range(retries):
            try:
                response = self.client.post(
                    f"{self.endpoint}/api/v1/events",
                    json={"events": self.events_buffer},
                )
                response.raise_for_status()

                logger.info(f"Flushed {len(self.events_buffer)} events")
                self.events_buffer = []
                return True

            except Exception as e:
                if attempt < retries - 1:
                    # Exponential backoff: 1s, 2s, 4s
                    backoff_time = 2 ** attempt
                    logger.warning(
                        f"Flush attempt {attempt + 1} failed, retrying in {backoff_time}s: {str(e)}"
                    )
                    time.sleep(backoff_time)
                else:
                    logger.error(f"Failed to flush events after {retries} attempts: {str(e)}")
                    return False

        return False

    def get_failures(
        self,
        model: Optional[str] = None,
        failure_type: Optional[str] = None,
        hours: int = 24,
        severity: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        Query failures from the backend.

        Args:
            model: Filter by model name
            failure_type: Filter by failure type
            hours: Look back N hours (default 24)
            severity: Filter by severity (critical, high, medium, low)
            limit: Results per page (default 20, max 100)
            page: Page number (1-indexed)

        Returns:
            Response dict with failures and pagination info, or None on error
        """
        try:
            params = {
                "limit": limit,
                "page": page,
                "hours": hours,
            }
            if model:
                params["model"] = model
            if failure_type:
                params["type"] = failure_type
            if severity:
                params["severity"] = severity

            response = self.client.get(
                f"{self.endpoint}/api/v1/failures",
                params=params,
            )
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Failed to query failures: {str(e)}")
            return None

    def get_failure_detail(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific failure.

        Args:
            event_id: Event ID

        Returns:
            Failure detail dict or None on error
        """
        try:
            response = self.client.get(
                f"{self.endpoint}/api/v1/failures/{event_id}",
            )
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Failed to get failure detail: {str(e)}")
            return None

    def get_patterns(
        self,
        model: Optional[str] = None,
        failure_type: Optional[str] = None,
        limit: int = 20,
    ) -> Optional[Dict[str, Any]]:
        """
        Get detected failure patterns.

        Args:
            model: Filter by model name
            failure_type: Filter by failure type
            limit: Results per page

        Returns:
            Response dict with patterns and summary, or None on error
        """
        try:
            params = {"limit": limit}
            if model:
                params["model"] = model
            if failure_type:
                params["type"] = failure_type

            response = self.client.get(
                f"{self.endpoint}/api/v1/patterns",
                params=params,
            )
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Failed to query patterns: {str(e)}")
            return None

    def export_pattern(
        self,
        pattern_id: str,
        limit: int = 500,
        hours: int = 720,
    ) -> Optional[str]:
        """
        Export a pattern's failing events as JSONL (one event per line).

        The result is ready to use as a regression eval set when testing a
        remediation or evaluating a different model on the prompts that
        actually failed.

        Args:
            pattern_id: Pattern ID (pat_xxx)
            limit: Max events to export (default 500)
            hours: Look back N hours (default 720)

        Returns:
            JSONL text, or None on error
        """
        try:
            response = self.client.get(
                f"{self.endpoint}/api/v1/patterns/{pattern_id}/export",
                params={"limit": limit, "hours": hours},
            )
            response.raise_for_status()

            return response.text

        except Exception as e:
            logger.error(f"Failed to export pattern {pattern_id}: {str(e)}")
            return None

    def get_stats(self, hours: int = 24) -> Optional[Dict[str, Any]]:
        """
        Get system-wide statistics.

        Args:
            hours: Look back N hours

        Returns:
            Stats dict or None on error
        """
        try:
            response = self.client.get(
                f"{self.endpoint}/api/v1/stats",
                params={"hours": hours},
            )
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Failed to query stats: {str(e)}")
            return None

    def get_models(self, hours: int = 24) -> Optional[Dict[str, Any]]:
        """
        Get per-model performance statistics.

        Args:
            hours: Look back N hours

        Returns:
            Response dict with model stats, or None on error
        """
        try:
            response = self.client.get(
                f"{self.endpoint}/api/v1/models",
                params={"hours": hours},
            )
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Failed to query model stats: {str(e)}")
            return None

    def get_recommendations(
        self,
        task_type: Optional[str] = None,
        hours: int = 720,
        min_events: int = 20,
    ) -> Optional[Dict[str, Any]]:
        """
        Get per-task model rankings (which model fits which task).

        Rankings reflect observed reliability on your own workload: failure
        rate first, then cost per call, then latency. Only events ingested
        with a task_type participate.

        Args:
            task_type: Limit to one task type (default: all)
            hours: Look back N hours (default 720 = 30 days)
            min_events: Events required before a model can be recommended

        Returns:
            Response dict with ranked models per task, or None on error
        """
        try:
            params: Dict[str, Any] = {"hours": hours, "min_events": min_events}
            if task_type:
                params["task_type"] = task_type

            response = self.client.get(
                f"{self.endpoint}/api/v1/recommendations",
                params=params,
            )
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Failed to query recommendations: {str(e)}")
            return None

    def get_correlations(
        self,
        model: Optional[str] = None,
        hours: int = 168,
    ) -> Optional[Dict[str, Any]]:
        """
        Get factor correlation analysis.

        Args:
            model: Optional model filter
            hours: Analysis window in hours

        Returns:
            Response dict with correlations, or None on error
        """
        try:
            params = {"hours": hours}
            if model:
                params["model"] = model

            response = self.client.get(
                f"{self.endpoint}/api/v1/correlations",
                params=params,
            )
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Failed to query correlations: {str(e)}")
            return None

    def submit_feedback(
        self,
        event_id: str,
        is_actual_failure: bool,
        corrected_failure_type: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Submit user feedback on a failure classification.

        Args:
            event_id: Event ID (evt_xxx)
            is_actual_failure: Whether this is confirmed as a failure
            corrected_failure_type: If classification should be corrected
            notes: Optional user notes

        Returns:
            Response dict with feedback_id, or None on error
        """
        try:
            payload = {
                "event_id": event_id,
                "is_actual_failure": is_actual_failure,
            }
            if corrected_failure_type:
                payload["corrected_failure_type"] = corrected_failure_type
            if notes:
                payload["notes"] = notes

            response = self.client.post(
                f"{self.endpoint}/api/v1/feedback",
                json=payload,
            )
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Failed to submit feedback: {str(e)}")
            return None

    def compare_models(
        self,
        primary_model: str,
        candidate_model: str,
        task_type: Optional[str] = None,
        sample_rate: float = 0.1,
        **kwargs: Any,
    ):
        """
        Create a shadow A/B comparison between two models.

        The primary model serves every request; a sampled fraction is also
        sent to the candidate in shadow mode. Both outcomes are reported on
        identical prompts, which is the strongest evidence for "model X is
        better at task Y". See sdk.comparison.ShadowComparison for details.

        Args:
            primary_model: Model serving live traffic
            candidate_model: Model to evaluate in shadow
            task_type: Task category attached to every event
            sample_rate: Fraction of calls that also run the candidate
            **kwargs: Forwarded to ShadowComparison (classify, comparison_id,
                primary_provider, candidate_provider)

        Returns:
            ShadowComparison instance
        """
        from .comparison import ShadowComparison

        return ShadowComparison(
            investigator=self,
            primary_model=primary_model,
            candidate_model=candidate_model,
            task_type=task_type,
            sample_rate=sample_rate,
            **kwargs,
        )

    def track(self):
        """
        Decorator to automatically track LLM function calls and report failures.

        Usage:
            @investigator.track()
            def call_llm(prompt):
                return llm.generate(prompt)
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                start_time = datetime.utcnow()

                try:
                    result = func(*args, **kwargs)
                    latency_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                    # Success - no failure to report
                    return result

                except Exception as e:
                    latency_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

                    # Report failure to API
                    try:
                        self.report_failure({
                            "timestamp": start_time.isoformat() + "Z",
                            "model_name": getattr(func, "__llm_model__", "unknown"),
                            "prompt": str(args[0]) if args else "unknown",
                            "response": "",
                            "failure_type": "timeout" if "timeout" in str(e).lower() else "semantic_error",
                            "failure_severity": "high",
                            "latency_ms": latency_ms,
                        })
                    except Exception as report_err:
                        logger.error(f"Failed to report tracked exception: {str(report_err)}")

                    raise

            return wrapper

        return decorator

    def close(self):
        """Close the HTTP client and flush any remaining events."""
        # Stop background flush thread
        self._stop_event.set()
        self._flush_thread.join(timeout=5)

        # Final flush
        self.flush()

        # Close HTTP client
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Convenience function for quick initialization
def create_investigator(
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> FailureInvestigator:
    """
    Create a FailureInvestigator instance with default settings.

    Args:
        api_key: API key (defaults to FAILURE_INVESTIGATOR_API_KEY env var)
        endpoint: Backend endpoint (defaults to FAILURE_INVESTIGATOR_ENDPOINT env var)

    Returns:
        FailureInvestigator instance
    """
    import os

    api_key = api_key or os.getenv("FAILURE_INVESTIGATOR_API_KEY")
    if not api_key:
        raise ValueError(
            "No API key provided. Pass api_key or set the "
            "FAILURE_INVESTIGATOR_API_KEY environment variable."
        )
    endpoint = endpoint or os.getenv("FAILURE_INVESTIGATOR_ENDPOINT", "http://localhost:8000")

    return FailureInvestigator(api_key=api_key, endpoint=endpoint)
