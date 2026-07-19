"""Streamlit dashboard for AI Failure Investigation System - Phase 2 Enhanced."""

import streamlit as st
import sys
import os
import time
import requests

# Fix imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load environment variables from the project-root .env, so the dashboard
# picks up FAILURE_INVESTIGATOR_API_KEY / _ENDPOINT without needing them
# exported into the shell. Existing environment variables take precedence.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(project_root, ".env"))
except ImportError:
    pass

from sdk import FailureInvestigator
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Page configuration
st.set_page_config(
    page_title="AI Failure Investigation",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Enhanced CSS with dark theme and color-coded severity
st.markdown("""
    <style>
    .metric-card {
        background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
        border: 1px solid #3a3a5c;
        border-radius: 12px;
        padding: 20px;
        margin: 8px 0;
        color: #e0e0ff;
    }
    .severity-critical { color: #ff4444; font-weight: bold; }
    .severity-high     { color: #ff8800; font-weight: bold; }
    .severity-medium   { color: #ffcc00; }
    .severity-low      { color: #44ff44; }
    .pattern-card {
        border-left: 4px solid #7c7cff;
        padding: 12px;
        margin: 8px 0;
        background: #1a1a2e;
        border-radius: 0 8px 8px 0;
    }
    .chart-container {
        background: #1a1a2e;
        padding: 10px;
        border-radius: 8px;
    }
    </style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_investigator():
    """Get cached Investigator instance."""
    api_key = os.getenv("FAILURE_INVESTIGATOR_API_KEY")
    if not api_key:
        st.error("FAILURE_INVESTIGATOR_API_KEY is not set. Configure it in your environment or .env file.")
        st.stop()
    endpoint = os.getenv("FAILURE_INVESTIGATOR_ENDPOINT", "http://localhost:8000")
    return FailureInvestigator(api_key=api_key, endpoint=endpoint)


@st.cache_data(ttl=60)
def get_model_names(_investigator, hours=168):
    """Distinct model names seen in the window, for filter dropdowns.

    The leading underscore on ``_investigator`` tells Streamlit not to hash it.
    """
    try:
        data = _investigator.get_models(hours=hours)
    except Exception:
        return []
    models = (data or {}).get("models") or []
    return sorted({m.get("model_name") for m in models if m.get("model_name")})


def main():
    st.title("🔍 AI Failure Investigation Dashboard")
    st.markdown("Monitor, analyze, and remediate LLM failures in real-time")

    investigator = get_investigator()

    # Sidebar controls
    st.sidebar.title("⚙️ Controls")

    # Auto-refresh toggle
    auto_refresh = st.sidebar.toggle("🔄 Auto-refresh", value=False)
    if auto_refresh:
        refresh_interval = st.sidebar.slider("Refresh interval (sec)", 10, 120, 30)
    else:
        refresh_interval = None

    # Navigation
    st.sidebar.markdown("---")
    st.sidebar.title("📊 Navigation")
    page = st.sidebar.radio(
        "Select page",
        ["Overview", "Failures", "Patterns", "Models", "Model Fit", "Analysis", "Correlations", "Settings"],
        label_visibility="collapsed",
    )

    # Page dispatcher
    if page == "Overview":
        show_overview(investigator)
    elif page == "Failures":
        show_failures(investigator)
    elif page == "Patterns":
        show_patterns(investigator)
    elif page == "Models":
        show_models(investigator)
    elif page == "Model Fit":
        show_model_fit(investigator)
    elif page == "Analysis":
        show_analysis(investigator)
    elif page == "Correlations":
        show_correlations(investigator)
    elif page == "Settings":
        show_settings()

    # Auto-refresh
    if auto_refresh:
        st.sidebar.caption(f"Refreshing every {refresh_interval}s...")
        time.sleep(refresh_interval)
        st.rerun()


def show_overview(investigator):
    """Overview dashboard with key metrics and trends."""
    st.header("📈 System Overview")

    col1, col2, col3, col4 = st.columns(4)

    stats = investigator.get_stats(hours=24)

    if stats:
        with col1:
            st.metric(
                "Total Events",
                f"{stats['total_events']:,}",
                delta_color="off",
            )
        with col2:
            st.metric(
                "Failures",
                f"{stats['total_failures']:,}",
                f"{stats['overall_failure_rate']:.2%}",
            )
        with col3:
            st.metric(
                "Active Patterns",
                stats['active_patterns'],
                f"{stats['patterns_with_remediation']} fixed",
            )
        with col4:
            trend_icon = "📈" if stats['failure_rate_trend'] == "increasing" else "📉" if stats['failure_rate_trend'] == "decreasing" else "→"
            st.metric(
                "Trend",
                stats['failure_rate_trend'],
                trend_icon,
                delta_color="inverse" if stats['failure_rate_trend'] == "increasing" else "off",
            )

        # Failure distribution
        st.subheader("Failure Type Distribution (24h)")
        col1, col2 = st.columns([2, 1])
        with col1:
            failure_types = stats['failure_type_distribution']
            if failure_types:
                st.bar_chart(pd.Series(failure_types))
            else:
                st.info("No failure data")
        with col2:
            st.markdown("### Breakdown")
            failure_types = stats['failure_type_distribution']
            for ftype, count in sorted(failure_types.items(), key=lambda x: x[1], reverse=True)[:5]:
                st.write(f"• **{ftype}**: {count}")

        # Severity breakdown
        st.subheader("Severity Distribution")
        col1, col2, col3, col4 = st.columns(4)
        severity = stats['severity_distribution']
        with col1:
            st.metric("🔴 Critical", severity.get('critical', 0))
        with col2:
            st.metric("🟠 High", severity.get('high', 0))
        with col3:
            st.metric("🟡 Medium", severity.get('medium', 0))
        with col4:
            st.metric("🟢 Low", severity.get('low', 0))

        # Avg confidence when failing
        if stats.get('average_confidence_when_fails'):
            st.metric(
                "Avg Confidence When Failing",
                f"{stats['average_confidence_when_fails']:.2f}",
            )

        # Top model
        if stats.get('model_with_highest_failures'):
            st.info(f"🔥 **Highest failures:** {stats['model_with_highest_failures']}")

    else:
        st.error("Failed to load statistics. Check API connection.")


def show_failures(investigator):
    """Failures list with filtering, pagination, and drill-down."""
    st.header("🔴 Failure Events")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        hours = st.slider("Time range (hours)", 1, 168, 24, key="failures_hours")
    with col2:
        model_names = get_model_names(investigator)
        model = st.selectbox("Filter model", ["All models"] + model_names)
        if model == "All models":
            model = None
    with col3:
        failure_type = st.selectbox(
            "Failure type",
            ["", "hallucination", "empty_response", "malformed_response", "timeout", "semantic_error", "confidence_mismatch", "retrieval_failure", "rate_limited", "token_limit"],
        )
    with col4:
        severity = st.selectbox("Severity", ["", "critical", "high", "medium", "low"])

    # Pagination state
    if "failures_page" not in st.session_state:
        st.session_state["failures_page"] = 1

    page = st.session_state["failures_page"]

    # Query
    failures = investigator.get_failures(
        model=model if model else None,
        failure_type=failure_type if failure_type else None,
        hours=hours,
        severity=severity if severity else None,
        limit=20,
        page=page,
    )

    if failures and failures.get('failures'):
        pagination = failures['pagination']

        # Pagination controls
        col_prev, col_info, col_next = st.columns([1, 3, 1], gap="small")
        with col_prev:
            if st.button("← Previous", disabled=page <= 1):
                st.session_state["failures_page"] = max(1, page - 1)
                st.rerun()
        with col_info:
            st.markdown(
                f"**Page {page} of {pagination['total_pages']}** ({pagination['total_count']} total failures)"
            )
        with col_next:
            if st.button("Next →", disabled=page >= pagination['total_pages']):
                st.session_state["failures_page"] = page + 1
                st.rerun()

        st.markdown("---")

        # Failure events as expandable cards
        st.subheader("Events")
        for _, row in pd.DataFrame(failures['failures']).iterrows():
            severity_class = f"severity-{row.get('failure_severity', 'low') or 'low'}"
            severity_icon = "🔴" if row.get('failure_severity') == "critical" else "🟠" if row.get('failure_severity') == "high" else "🟡" if row.get('failure_severity') == "medium" else "🟢"

            with st.expander(
                f"{severity_icon} [{row['failure_type'].upper()}] {row['model_name']} — {row['timestamp'][:19]}"
            ):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Event ID:** `{row['event_id']}`")
                    st.markdown(f"**Model:** {row['model_name']}")
                    st.markdown(f"**Type:** {row['failure_type']}")
                    st.markdown(f"**Confidence:** {row.get('confidence_score', 'N/A')}")
                with col2:
                    st.markdown(f"**Latency:** {row.get('latency_ms', 'N/A')} ms")
                    st.markdown(f"**Environment:** {row.get('environment', 'N/A')}")
                    st.markdown(f"**Severity:** {row.get('failure_severity', 'N/A')}")
                    st.markdown(f"**Retrieval:** {row.get('retrieval_score', 'N/A')}")

                # Show prompt/response preview
                st.markdown("---")
                st.markdown("**Prompt Preview:**")
                st.caption(row.get('prompt', 'N/A')[:200] + "...")

                st.markdown("**Response Preview:**")
                st.caption(row.get('response', 'N/A')[:200] + "...")

                # Feedback form
                with st.form(key=f"feedback_{row['event_id']}"):
                    st.markdown("**Provide Feedback**")
                    is_failure = st.checkbox("Confirm this is an actual failure", value=True)
                    corrected_type = st.selectbox(
                        "Correct failure type (if different)",
                        ["", "hallucination", "empty_response", "malformed_response", "timeout", "semantic_error", "confidence_mismatch"],
                        key=f"correct_{row['event_id']}",
                    )
                    notes = st.text_input("Notes (optional)", key=f"notes_{row['event_id']}")

                    if st.form_submit_button("✓ Submit Feedback"):
                        result = investigator.submit_feedback(
                            event_id=row["event_id"],
                            is_actual_failure=is_failure,
                            corrected_failure_type=corrected_type if corrected_type else None,
                            notes=notes if notes else None,
                        )
                        if result:
                            st.success("Feedback submitted!")
                        else:
                            st.error("Failed to submit feedback")

    elif failures:
        st.info("No failures found for the selected filters.")
    else:
        st.error("Failed to load failures. Check API connection.")


def show_patterns(investigator):
    """Failure patterns with summary and details."""
    st.header("🔍 Failure Patterns")

    col1, col2 = st.columns(2)
    with col1:
        model = st.text_input("Filter by model", "", key="patterns_model")
    with col2:
        failure_type = st.selectbox(
            "Filter by type",
            ["", "hallucination", "empty_response", "malformed_response", "timeout", "semantic_error"],
            key="patterns_type",
        )

    patterns = investigator.get_patterns(
        model=model if model else None,
        failure_type=failure_type if failure_type else None,
        limit=100,
    )

    if patterns:
        summary = patterns['summary']

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Patterns", summary['total_patterns'])
        with col2:
            st.metric("With Remediation", summary['patterns_with_remediation'])
        with col3:
            st.metric("Avg Occurrences", f"{summary['avg_occurrences_per_pattern']:.1f}")

        st.markdown("---")

        if patterns['patterns']:
            for pattern in sorted(patterns['patterns'], key=lambda x: x['occurrence_count'], reverse=True):
                with st.expander(
                    f"📊 {pattern['failure_type']} → {pattern['model_name']} ({pattern['occurrence_count']} times)"
                ):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Occurrences", pattern['occurrence_count'])
                        st.metric("Users Affected", pattern['unique_users_affected'])
                    with col2:
                        st.metric("Avg Confidence", f"{pattern.get('average_confidence', 0):.2f}")
                        st.metric("Avg Latency", f"{pattern.get('average_latency_ms', 0):.0f}ms")
                    with col3:
                        sev = pattern.get('severity_breakdown', {})
                        st.metric("🔴 Critical", sev.get('critical', 0))
                        st.metric("🟠 High", sev.get('high', 0))

                    if pattern.get('suggested_remediation'):
                        st.markdown(f"**💡 Suggested Remediation:**\n{pattern['suggested_remediation']}")

                    st.caption(
                        f"First: {pattern['first_seen'][:10]} | Last: {pattern['last_seen'][:10]}"
                    )

                    # Eval-set export: prepare on demand, then offer download
                    export_key = f"export_{pattern['pattern_id']}"
                    if st.button("📦 Prepare eval set (JSONL)", key=f"btn_{export_key}"):
                        jsonl = investigator.export_pattern(pattern['pattern_id'])
                        if jsonl:
                            st.session_state[export_key] = jsonl
                        else:
                            st.error("Export failed")
                    if export_key in st.session_state:
                        data = st.session_state[export_key]
                        st.download_button(
                            f"⬇️ Download {pattern['pattern_id']}.jsonl ({len(data.splitlines())} events)",
                            data=data,
                            file_name=f"{pattern['pattern_id']}.jsonl",
                            mime="application/x-ndjson",
                            key=f"dl_{export_key}",
                        )
    else:
        st.error("Failed to load patterns.")


def show_models(investigator):
    """Complete model performance page with charts."""
    st.header("📊 Model Performance")

    hours = st.slider("Time range (hours)", 1, 168, 24, key="models_hours")

    models_data = investigator.get_models(hours=hours)

    if not models_data or not models_data.get('models'):
        st.warning("No model data found for this time range.")
        return

    models = models_data['models']
    df = pd.DataFrame(models)

    # Summary metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Models Tracked", len(models))
    with col2:
        avg_failure_rate = df['failure_rate'].mean() if not df.empty else 0
        st.metric("Avg Failure Rate", f"{avg_failure_rate:.2%}")
    with col3:
        if not df.empty and df['failure_rate'].notna().any():
            worst_model = df.loc[df['failure_rate'].idxmax(), 'model_name']
            st.metric("Highest Failure Rate", worst_model)

    st.markdown("---")

    # Comparative charts
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Failure Rate by Model")
        chart_df = df.set_index('model_name')[['failure_rate']].sort_values('failure_rate', ascending=False)
        if not chart_df.empty:
            st.bar_chart(chart_df * 100)
        else:
            st.info("No data")

    with col2:
        st.subheader("Failure Count by Model")
        count_df = df.set_index('model_name')[['failure_count']].sort_values('failure_count', ascending=False)
        if not count_df.empty:
            st.bar_chart(count_df)
        else:
            st.info("No data")

    # Latency comparison
    st.subheader("Average Latency by Model")
    latency_df = df[df['average_latency_ms'].notna()].set_index('model_name')[['average_latency_ms']]
    if not latency_df.empty:
        st.bar_chart(latency_df)

    # Detail table
    st.subheader("Full Model Statistics")
    display_df = df[[
        'model_name', 'total_events', 'failure_count', 'failure_rate',
        'average_confidence', 'average_latency_ms', 'distinct_failure_types'
    ]].copy()
    display_df.columns = [
        'Model', 'Events', 'Failures', 'Rate',
        'Avg Confidence', 'Avg Latency (ms)', 'Failure Types'
    ]
    display_df['Rate'] = display_df['Rate'].apply(lambda x: f"{x:.2%}")
    st.dataframe(display_df, use_container_width=True, hide_index=True)


def show_model_fit(investigator):
    """Which model is good at which task, based on observed events."""
    st.header("🎯 Model Fit: Which Model for Which Task")

    st.markdown(
        "Rankings below come from **your observed traffic**, not benchmarks: "
        "models are ranked per task by failure rate, ties broken by cost per "
        "call, then latency. Only events ingested with a `task_type` participate."
    )

    col1, col2 = st.columns(2)
    with col1:
        hours = st.slider("Time range (hours)", 24, 2160, 720, key="fit_hours")
    with col2:
        min_events = st.number_input(
            "Min events to recommend a model", min_value=1, max_value=10000, value=20,
            help="Models with fewer events for a task are shown but never recommended.",
        )

    data = investigator.get_recommendations(hours=hours, min_events=int(min_events))

    if data is None:
        st.error("Failed to load recommendations. Check API connection.")
        return

    tasks = data.get("tasks", [])
    if not tasks:
        st.info(
            "No task-tagged events yet. Pass `task_type` when reporting events "
            "(e.g. `summarization`, `code_generation`, `rag_qa`) to populate this view."
        )
        return

    # ---- Recommendations at a glance ----
    st.subheader("Recommended Model per Task")
    rec_rows = []
    for task in tasks:
        rec_rows.append({
            "Task": task["task_type"],
            "Recommended": f"🏆 {task['recommended_model']}" if task["recommended_model"] else "— not enough data",
            "Events": task["total_events"],
            "Models Compared": len(task["ranked_models"]),
        })
    st.dataframe(pd.DataFrame(rec_rows), use_container_width=True, hide_index=True)

    for task in tasks:
        if task.get("caveat"):
            st.caption(f"⚠️ **{task['task_type']}**: {task['caveat']}")

    # ---- Success-rate matrix ----
    st.subheader("Success Rate: Task × Model")
    matrix_rows = []
    for task in tasks:
        for m in task["ranked_models"]:
            matrix_rows.append({
                "task_type": task["task_type"],
                "model_name": m["model_name"],
                "success_rate": m["success_rate"],
                "total_events": m["total_events"],
                "failure_rate": m["failure_rate"],
                "average_cost_usd": m["average_cost_usd"],
                "average_latency_ms": m["average_latency_ms"],
            })
    matrix_df = pd.DataFrame(matrix_rows)

    pivot = matrix_df.pivot_table(
        index="task_type", columns="model_name", values="success_rate"
    )
    st.dataframe(
        pivot.style.format("{:.1%}", na_rep="—").background_gradient(
            cmap="RdYlGn", axis=None, vmin=0.5, vmax=1.0
        ),
        use_container_width=True,
    )
    st.caption("Cells are success rates over the selected window; blank cells mean no traffic for that pair.")

    # ---- Cost vs reliability ----
    cost_df = matrix_df[matrix_df["average_cost_usd"].notna()]
    if not cost_df.empty:
        st.subheader("Cost vs Reliability")
        st.markdown("Bottom-left is best: cheap **and** reliable. Point size = event volume.")
        scatter_df = cost_df.rename(columns={
            "average_cost_usd": "Avg cost per call (USD)",
            "failure_rate": "Failure rate",
        })
        st.scatter_chart(
            scatter_df,
            x="Avg cost per call (USD)",
            y="Failure rate",
            color="model_name",
            size="total_events",
        )

    # ---- Per-task drill-down ----
    st.subheader("Task Drill-Down")
    task_names = [t["task_type"] for t in tasks]
    selected = st.selectbox("Task type", task_names)
    task = next(t for t in tasks if t["task_type"] == selected)

    detail_rows = []
    for rank, m in enumerate(task["ranked_models"], start=1):
        detail_rows.append({
            "Rank": f"🏆 {rank}" if m["model_name"] == task["recommended_model"] else str(rank),
            "Model": m["model_name"],
            "Provider": m["provider"] or "—",
            "Events": m["total_events"],
            "Success Rate": f"{m['success_rate']:.1%}",
            "Top Failure": m["top_failure_type"] or "—",
            "Avg Latency (ms)": f"{m['average_latency_ms']:.0f}" if m["average_latency_ms"] is not None else "—",
            "Avg Cost / Call": f"${m['average_cost_usd']:.5f}" if m["average_cost_usd"] is not None else "—",
            "Enough Data": "✓" if m["sample_sufficient"] else f"needs {data['min_events']}+",
        })
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)


def show_analysis(investigator):
    """Pattern analysis with heatmap and triggers."""
    st.header("🔬 Pattern Analysis")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🚀 Run Pattern Analysis Now"):
            # Trigger analysis endpoint
            endpoint = os.getenv("FAILURE_INVESTIGATOR_ENDPOINT", "http://localhost:8000")
            api_key = os.getenv("FAILURE_INVESTIGATOR_API_KEY", "")
            try:
                r = requests.post(
                    f"{endpoint}/api/v1/events/trigger-analysis",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"hours": 168},
                    timeout=5,
                )
                if r.status_code == 202:
                    st.success("✓ Pattern analysis triggered. Results updating...")
                else:
                    st.error(f"Trigger failed: {r.status_code}")
            except Exception as e:
                st.error(f"Connection error: {e}")

    patterns_data = investigator.get_patterns(limit=100)

    if not patterns_data or not patterns_data.get('patterns'):
        st.info("No patterns detected yet. Ingest more events or trigger analysis.")
        return

    patterns = patterns_data['patterns']
    summary = patterns_data['summary']

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Patterns", summary['total_patterns'])
    with col2:
        st.metric("With Remediation", summary['patterns_with_remediation'])
    with col3:
        st.metric("Avg Occurrences", f"{summary['avg_occurrences_per_pattern']:.1f}")

    # Heatmap using pivot
    st.subheader("Pattern Heatmap: Failure Type × Model")
    df = pd.DataFrame(patterns)
    if 'model_name' in df.columns and 'failure_type' in df.columns:
        pivot = df.pivot_table(
            index='failure_type',
            columns='model_name',
            values='occurrence_count',
            fill_value=0,
        )
        # Styled dataframe with color gradient
        st.dataframe(
            pivot.style.background_gradient(cmap='Reds', vmin=0),
            use_container_width=True,
        )

    # Pattern detail cards
    st.subheader("Pattern Details")
    for pattern in sorted(patterns, key=lambda x: x['occurrence_count'], reverse=True)[:10]:
        with st.expander(
            f"⚠️ {pattern['failure_type']} on {pattern['model_name']} ({pattern['occurrence_count']} times)"
        ):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Occurrences", pattern['occurrence_count'])
                st.metric("Users Affected", pattern['unique_users_affected'])
            with col2:
                st.metric("Avg Confidence", f"{pattern.get('average_confidence', 0):.2f}")
                st.metric("Avg Latency", f"{pattern.get('average_latency_ms', 0):.0f} ms")
            with col3:
                sev = pattern.get('severity_breakdown', {})
                st.metric("Critical", sev.get('critical', 0))
                st.metric("High", sev.get('high', 0))

            if pattern.get('suggested_remediation'):
                st.warning(f"💡 **Remediation:** {pattern['suggested_remediation']}")

            st.caption(f"First: {pattern['first_seen'][:10]} | Last: {pattern['last_seen'][:10]}")


def show_correlations(investigator):
    """Correlation analysis between factors and failures."""
    st.header("🔗 Failure Factor Correlations")

    st.markdown(
        "Identifies which operational factors are statistically associated with failure occurrence. "
        "Stronger correlation = more reliable signal."
    )

    col1, col2 = st.columns(2)
    with col1:
        hours = st.slider("Analysis window (hours)", 24, 720, 168, key="corr_hours")
    with col2:
        model_names = get_model_names(investigator)
        model_filter = st.selectbox("Filter by model (optional)", ["All models"] + model_names)
        if model_filter == "All models":
            model_filter = None

    correlations_data = investigator.get_correlations(
        model=model_filter if model_filter else None,
        hours=hours,
    )

    if not correlations_data:
        st.error("Failed to load correlations. Check API connection.")
        return

    corr_list = correlations_data.get('correlations', [])
    events_analyzed = correlations_data.get('events_analyzed', 0)

    if not corr_list:
        st.info(f"No significant correlations found in {events_analyzed} events. More data may be needed.")
        return

    st.caption(f"Analyzed {events_analyzed} events. Computed at {correlations_data.get('computed_at', '')[:19]}")

    # Strength bar chart
    st.subheader("Correlation Strengths")
    if corr_list:
        corr_df = pd.DataFrame(corr_list)
        chart_data = corr_df.set_index('factor_a')[['correlation_strength']].abs()
        st.bar_chart(chart_data)

    # Detail cards
    st.subheader("Correlation Details")
    for corr in sorted(corr_list, key=lambda x: abs(x['correlation_strength']), reverse=True):
        significance = "✓ SIGNIFICANT" if corr['is_significant'] else "○ Weak"
        with st.expander(
            f"{significance} | {corr['factor_a']} ↔ {corr['factor_b']} "
            f"(strength: {corr['correlation_strength']:.3f})"
        ):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Strength", f"{corr['correlation_strength']:.3f}")
            with col2:
                if corr.get('chi_squared'):
                    st.metric("Chi-Squared", f"{corr['chi_squared']:.1f}")
            with col3:
                if corr.get('p_value') is not None:
                    st.metric("P-Value", f"{corr['p_value']:.4f}")

            st.markdown(f"**Interpretation:** {corr['interpretation']}")


def show_settings():
    """Settings and about page."""
    st.header("⚙️ Settings")

    st.subheader("API Configuration")
    endpoint = os.getenv("FAILURE_INVESTIGATOR_ENDPOINT", "http://localhost:8000")
    api_key = os.getenv("FAILURE_INVESTIGATOR_API_KEY")

    st.text_input("API Endpoint", endpoint, disabled=True)
    # Never render the key itself - only whether it is configured
    st.text_input("API Key", "configured" if api_key else "not set", disabled=True)

    st.markdown("---")

    st.subheader("ℹ️ About")
    st.markdown("""
    **AI Failure Investigation System** v0.2.0 (Phase 2)

    An observability platform for tracking, analyzing, and diagnosing AI/LLM failures in production workflows.

    ### Features
    - 📊 Real-time failure tracking and monitoring
    - 🔍 Pattern detection with recurring issue identification
    - 📈 Performance analytics per model
    - 🔗 Factor correlation analysis
    - 💡 Automated remediation suggestions
    - 👥 User feedback collection
    - 🚀 Scalable event ingestion

    ### Technology Stack
    - **Backend:** FastAPI + SQLAlchemy + PostgreSQL + TimescaleDB
    - **Frontend:** Streamlit
    - **SDK:** Python HTTP client with batch processing
    - **Deployment:** Docker Compose

    [GitHub Repository](https://github.com/example/ai-failure-investigation)
    """)


if __name__ == "__main__":
    main()
