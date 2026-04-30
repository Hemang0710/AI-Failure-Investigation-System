"""Streamlit dashboard for AI Failure Investigation System."""

import streamlit as st
import sys
import os

# Fix imports - add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sdk import FailureInvestigator
import pandas as pd
from datetime import datetime, timedelta

# Page configuration
st.set_page_config(
    page_title="AI Failure Investigation",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
    <style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    </style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_investigator():
    """Get cached Investigator instance."""
    api_key = os.getenv("FAILURE_INVESTIGATOR_API_KEY", "sk-demo-12345")
    endpoint = os.getenv("FAILURE_INVESTIGATOR_ENDPOINT", "http://localhost:8000")
    return FailureInvestigator(api_key=api_key, endpoint=endpoint)


def main():
    st.title("🔍 AI Failure Investigation Dashboard")
    st.markdown("Monitor and analyze LLM failures in real-time")

    investigator = get_investigator()

    # Sidebar navigation
    page = st.sidebar.radio(
        "Navigation",
        ["Overview", "Failures", "Patterns", "Models", "Settings"],
    )

    if page == "Overview":
        show_overview(investigator)
    elif page == "Failures":
        show_failures(investigator)
    elif page == "Patterns":
        show_patterns(investigator)
    elif page == "Models":
        show_models(investigator)
    elif page == "Settings":
        show_settings()


def show_overview(investigator):
    """Overview dashboard with key metrics."""
    st.header("System Overview")

    col1, col2, col3 = st.columns(3)

    # Get stats
    stats = investigator.get_stats(hours=24)

    if stats:
        with col1:
            st.metric(
                "Total Events (24h)",
                f"{stats['total_events']:,}",
                delta=None,
            )

        with col2:
            st.metric(
                "Failures (24h)",
                f"{stats['total_failures']:,}",
                delta=f"{stats['overall_failure_rate']:.2%}",
            )

        with col3:
            st.metric(
                "Active Patterns",
                stats['active_patterns'],
                delta=f"{stats['patterns_with_remediation']} fixed",
            )

        # Failure type distribution
        st.subheader("Failure Type Distribution")
        failure_types = stats['failure_type_distribution']
        if failure_types:
            col1, col2 = st.columns([2, 1])
            with col1:
                st.bar_chart(failure_types)
            with col2:
                for ftype, count in failure_types.items():
                    st.write(f"**{ftype}**: {count}")

        # Severity breakdown
        st.subheader("Severity Breakdown")
        severity = stats['severity_distribution']
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Critical", severity.get('critical', 0))
        with col2:
            st.metric("High", severity.get('high', 0))
        with col3:
            st.metric("Medium", severity.get('medium', 0))
        with col4:
            st.metric("Low", severity.get('low', 0))

    else:
        st.error("Failed to load statistics. Check API connection.")


def show_failures(investigator):
    """Failures list and filter."""
    st.header("Failures")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        hours = st.slider("Time range (hours)", 1, 168, 24)
    with col2:
        model = st.text_input("Model name", "")
    with col3:
        failure_type = st.selectbox(
            "Failure type",
            ["", "hallucination", "empty_response", "malformed_response", "timeout", "semantic_error", "confidence_mismatch"],
        )
    with col4:
        severity = st.selectbox(
            "Severity",
            ["", "critical", "high", "medium", "low"],
        )

    # Query failures
    failures = investigator.get_failures(
        model=model if model else None,
        failure_type=failure_type if failure_type else None,
        hours=hours,
        severity=severity if severity else None,
        limit=50,
    )

    if failures:
        st.subheader(f"Results: {failures['pagination']['total_count']} failures")

        # Convert to DataFrame
        if failures['failures']:
            df = pd.DataFrame(failures['failures'])
            # Format timestamp
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
            st.dataframe(df, use_container_width=True)

            # Pagination info
            st.caption(
                f"Page {failures['pagination']['page']} of {failures['pagination']['total_pages']} "
                f"({failures['pagination']['limit']} results per page)"
            )
        else:
            st.info("No failures found.")

    else:
        st.error("Failed to load failures. Check API connection.")


def show_patterns(investigator):
    """Failure patterns."""
    st.header("Failure Patterns")

    col1, col2 = st.columns(2)
    with col1:
        model = st.text_input("Filter by model", "")
    with col2:
        failure_type = st.selectbox(
            "Filter by type",
            ["", "hallucination", "empty_response", "malformed_response"],
        )

    patterns = investigator.get_patterns(
        model=model if model else None,
        failure_type=failure_type if failure_type else None,
    )

    if patterns:
        summary = patterns['summary']
        st.subheader(f"Summary: {summary['total_patterns']} patterns detected")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Patterns", summary['total_patterns'])
        with col2:
            st.metric("With Remediation", summary['patterns_with_remediation'])
        with col3:
            st.metric("Avg Occurrences", f"{summary['avg_occurrences_per_pattern']:.1f}")

        # Pattern details
        if patterns['patterns']:
            for pattern in patterns['patterns']:
                with st.expander(f"Pattern {pattern['pattern_id']}: {pattern['failure_type']} ({pattern['occurrence_count']} occurrences)"):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Occurrences", pattern['occurrence_count'])
                    with col2:
                        st.metric("Unique Users", pattern['unique_users_affected'])
                    with col3:
                        st.metric("First Seen", pattern['first_seen'][:10])

                    if pattern['suggested_remediation']:
                        st.markdown(f"**Suggested Remediation:** {pattern['suggested_remediation']}")

                    st.markdown(f"**Avg Confidence:** {pattern['average_confidence']:.2f}")

    else:
        st.error("Failed to load patterns.")


def show_models(investigator):
    """Model performance."""
    st.header("Model Performance")

    hours = st.slider("Time range (hours)", 1, 168, 24, key="models_hours")

    models_data = investigator.get_stats(hours=hours)

    if models_data:
        # This is a simplified view - we'll create a dedicated models endpoint in Phase 2
        st.info("Model performance stats coming soon. Check system overview for failure rates.")

    else:
        st.error("Failed to load model data.")


def show_settings():
    """Settings page."""
    st.header("Settings")

    st.subheader("API Configuration")
    endpoint = os.getenv("FAILURE_INVESTIGATOR_ENDPOINT", "http://localhost:8000")
    api_key = os.getenv("FAILURE_INVESTIGATOR_API_KEY", "sk-demo-12345")

    st.text_input("API Endpoint", endpoint, disabled=True)
    st.text_input("API Key", api_key, disabled=True, type="password")

    st.subheader("About")
    st.markdown("""
    **AI Failure Investigation System** v0.1.0

    An observability platform for tracking and analyzing LLM failures.

    - Track hallucinations, empty responses, and more
    - Detect recurring failure patterns
    - Analyze model performance
    - Monitor system health

    [Documentation](https://github.com/example/ai-failure-investigation)
    """)


if __name__ == "__main__":
    main()
