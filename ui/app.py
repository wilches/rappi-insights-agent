"""
Streamlit UI for the Rappi Operations Intelligence system.

Run: streamlit run ui/app.py

Two tabs:
    1. Chat  — interactive chat agent (maintains conversation history)
    2. Report — generate the weekly executive insights report
"""

import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import logging

import streamlit as st

from core.data_loader import load_unified_data
from agent.chat_agent import ChatAgent
from insights.engine import generate_insights
from insights.report_generator import generate_markdown_report


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Rappi Ops Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Data + agent loading (cached across reruns within one session)
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Loading operational data…")
def load_data():
    """Load and normalize both CSVs. Cached for the session."""
    return load_unified_data(
        metrics_path=Path("data/metrics.csv"),
        orders_path=Path("data/orders.csv"),
    )


def get_agent(df) -> ChatAgent:
    """
    Instantiate the chat agent once per session and stash it in session_state.
    Session state is Streamlit's way of persisting objects across reruns.
    """
    if "agent" not in st.session_state:
        st.session_state.agent = ChatAgent(df)
        st.session_state.messages = []  # list of {"role": "user"|"assistant", "content": str, "tool_calls": list}
    return st.session_state.agent


def reset_conversation():
    """Clear both the agent's history and the UI message log."""
    if "agent" in st.session_state:
        st.session_state.agent.reset()
    st.session_state.messages = []


# ---------------------------------------------------------------------------
# Load everything
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
df = load_data()
agent = get_agent(df)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("📊 Rappi Ops Intelligence")
    st.caption("Sistema de análisis conversacional para SP&A y Operations")

    st.divider()

    st.subheader("Dataset")
    st.metric("Zones", f"{df['ZONE'].nunique():,}")
    st.metric("Countries", df["COUNTRY"].nunique())
    st.metric("Metrics", df["METRIC"].nunique())
    st.metric("Weeks of data", df["week_offset"].nunique())

    st.divider()

    st.subheader("Sample questions")
    st.caption("Click to send")

    sample_questions = [
        "¿Cuáles son las 5 zonas con mayor Lead Penetration esta semana?",
        "Compara el Perfect Orders entre zonas Wealthy y Non Wealthy en México",
        "Muéstrame la evolución de Gross Profit UE en Chapinero las últimas 8 semanas",
        "¿Cuál es el promedio de Lead Penetration por país?",
        "¿Qué zonas tienen alto Lead Penetration pero bajo Perfect Orders?",
        "¿Qué zonas crecen más en órdenes y qué podría explicarlo?",
    ]
    for q in sample_questions:
        if st.button(q, key=f"sample_{q[:30]}", use_container_width=True):
            st.session_state.pending_user_input = q
            st.rerun()

    st.divider()
    if st.button("🔄 Reset conversation", use_container_width=True):
        reset_conversation()
        st.rerun()


# ---------------------------------------------------------------------------
# Main area — tabs
# ---------------------------------------------------------------------------

tab_chat, tab_report = st.tabs(["💬 Chat", "📄 Executive Report"])


# --------------------------- CHAT TAB ---------------------------

with tab_chat:
    st.header("Pregunta lo que quieras sobre las métricas operacionales")
    st.caption(
        "El agente usa Gemini con tool calling sobre tus datos reales. "
        "Todos los números vienen de pandas; el LLM sólo compone la respuesta."
    )

    # ---- 1. Resolve the input source (typed, sample button, or none) ----
    user_input = None
    if "pending_user_input" in st.session_state:
        user_input = st.session_state.pop("pending_user_input")

    # ---- 2. If we have new input, process it BEFORE rendering history ----
    if user_input:
        # Append user message to history
        st.session_state.messages.append({
            "role": "user",
            "content": user_input,
        })

        # Call the agent (may take a few seconds)
        with st.spinner("Pensando…"):
            try:
                response = agent.chat(user_input)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response.text,
                    "tool_calls": response.tool_calls,
                })
            except Exception as e:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"⚠️ Error: {type(e).__name__}: {e}",
                    "tool_calls": [],
                })

    # ---- 3. Render the full history (single source of truth) ----
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                with st.expander(
                    f"🔧 Tool calls ({len(msg['tool_calls'])})",
                    expanded=False,
                ):
                    for tc in msg["tool_calls"]:
                        st.code(
                            f"{tc['tool']}({tc['args']})\n→ {tc['result_summary']}",
                            language="python",
                        )


# --------------------------- REPORT TAB ---------------------------

with tab_report:
    st.header("Reporte Ejecutivo Automático")
    st.caption(
        "Ejecuta los 5 detectores, ranquea findings por severidad de negocio, "
        "y genera un reporte en markdown listo para SP&A y Operations."
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        generate_clicked = st.button(
            "🚀 Generate report",
            type="primary",
            use_container_width=True,
        )

    # Persist the last generated report across reruns
    if generate_clicked:
        try:
            with st.spinner("Running detectors…"):
                selected = generate_insights(df)
            counts = {k: len(v) for k, v in selected.items()}
            st.success(
                f"Selected findings — "
                + ", ".join(f"**{k}**: {v}" for k, v in counts.items())
            )
            with st.spinner("Generating narrative (LLM call)…"):
                report_md = generate_markdown_report(selected)
            st.session_state.last_report = report_md
        except Exception as e:
            st.error(f"⚠️ Error generating report: {type(e).__name__}: {e}")

    if "last_report" in st.session_state:
        st.divider()

        # Download button
        st.download_button(
            label="⬇️ Download markdown",
            data=st.session_state.last_report,
            file_name="executive_report.md",
            mime="text/markdown",
        )

        st.divider()

        # Render it
        st.markdown(st.session_state.last_report)

typed = st.chat_input("¿En qué métrica nos enfocamos hoy?")
if typed:
    st.session_state.pending_user_input = typed
    st.rerun()
