import streamlit as st
import pandas as pd
from metadata import extract_metadata
from llm import auto_analyse, ask_gemini, summarize_chart
from code_runner import run_chart_code

st.set_page_config(page_title="CSV Chart Analyst", page_icon="📊", layout="wide")

st.title("📊 CSV Chart Analyst")
st.caption("Upload a CSV — instant charts on load, then ask anything.")

for key, default in [
    ("messages", []),
    ("df", None),
    ("metadata", None),
    ("auto_charts", []),
    ("auto_errors", []),
    ("analysed_file", None),
    ("deep_summary", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Sidebar ──────────────────────────────────────────────────────
with st.sidebar:
    st.header("Upload your CSV")
    uploaded = st.file_uploader("Choose a CSV file", type=["csv"])

    if uploaded and st.session_state.analysed_file != uploaded.name:
        df = pd.read_csv(uploaded)
        st.session_state.df = df
        st.session_state.metadata = extract_metadata(df)
        st.session_state.messages = []
        st.session_state.auto_charts = []
        st.session_state.auto_errors = []
        st.session_state.deep_summary = None
        st.session_state.analysed_file = uploaded.name

        with st.spinner("Generating charts…"):
            result = auto_analyse(st.session_state.metadata, df)

        st.session_state.auto_charts = result["charts"]
        st.session_state.auto_errors = result.get("errors", [])

        if result.get("suggestion_error"):
            st.warning(f"Suggestion step fell back to defaults: {result['suggestion_error']}")

    if st.session_state.df is not None:
        st.success(
            f"Loaded: {st.session_state.df.shape[0]} rows × "
            f"{st.session_state.df.shape[1]} columns"
        )
        st.dataframe(st.session_state.df.head(5), use_container_width=True)

    st.divider()
    if st.button("🗑️ Clear chat"):
        st.session_state.messages = []
        st.session_state.deep_summary = None
        st.rerun()

# ── Auto-charts ──────────────────────────────────────────────────
if st.session_state.auto_charts:
    st.subheader("📈 Auto-generated Charts")
    cols = st.columns(2)
    for i, chart in enumerate(st.session_state.auto_charts):
        with cols[i % 2]:
            st.markdown(f"**Chart {i+1}: {chart['title']}**")
            st.plotly_chart(chart["figure"], use_container_width=True)
            # Show explanation under each chart
            if chart.get("explanation"):
                st.info(chart["explanation"])
            with st.expander("View code"):
                st.code(chart["code"], language="python")

    # Show any per-chart errors
    if st.session_state.auto_errors:
        with st.expander("⚠️ Some charts failed to generate"):
            for err in st.session_state.auto_errors:
                st.text(err)

    st.divider()
    st.markdown(
        "💬 **Ask a question below** — e.g. *'What insights can you give from chart 2?'* "
        "or *'Show me a scatter plot of X vs Y'*"
    )

elif st.session_state.analysed_file:
    st.error("⚠️ Auto-chart generation failed for all charts.")
    if st.session_state.auto_errors:
        for err in st.session_state.auto_errors:
            st.text(err)

# ── Chat history ─────────────────────────────────────────────────
if st.session_state.messages:
    st.subheader("💬 Conversation")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("text"):
            st.markdown(msg["text"])
        if msg.get("figure"):
            st.plotly_chart(msg["figure"], use_container_width=True)
        if msg.get("code"):
            with st.expander("View generated code"):
                st.code(msg["code"], language="python")
        if msg.get("error"):
            st.error(msg["error"])

# ── Explain with chart toggle + Chat input ───────────────────────
if st.session_state.df is not None:
    chart_toggle = st.toggle("📊 Explain answer with a chart", value=False)
else:
    chart_toggle = False

prompt = st.chat_input(
    "Ask for insights or say 'show me a chart of X vs Y'…",
    disabled=st.session_state.df is None,
)

if st.session_state.df is None:
    st.info("👈 Upload a CSV file to get started.")

if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        assistant_msg = {"role": "assistant"}

        chat_history = [
            {"role": m["role"], "text": m.get("text", "")}
            for m in st.session_state.messages
            if m.get("text")
        ]

        with st.spinner("Thinking…"):
            response = ask_gemini(
                metadata=st.session_state.metadata,
                user_question=prompt,
                df=st.session_state.df,
                chat_history=chat_history,
                explain_with_chart=chart_toggle,
            )

        if response["type"] == "chart":
            text = response.get("explanation", "")
            st.markdown(text)
            with st.expander("View generated code"):
                st.code(response["code"], language="python")
            fig, error = run_chart_code(response["code"], st.session_state.df)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
                assistant_msg["figure"] = fig
            else:
                st.error(f"Code execution failed: {error}")
                assistant_msg["error"] = error
            assistant_msg["text"] = text
            assistant_msg["code"] = response["code"]

        elif response["type"] == "text":
            st.markdown(response["content"])
            assistant_msg["text"] = response["content"]

            # If explain_with_chart toggle is on and LLM returned chart code
            if response.get("chart_code"):
                chart_exp = response.get("chart_explanation", "")
                if chart_exp:
                    st.markdown(f"**Chart explanation:** {chart_exp}")
                with st.expander("View generated code"):
                    st.code(response["chart_code"], language="python")
                fig, error = run_chart_code(response["chart_code"], st.session_state.df)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                    assistant_msg["figure"] = fig
                    assistant_msg["code"] = response["chart_code"]
                else:
                    st.error(f"Chart code execution failed: {error}")
                    assistant_msg["error"] = error

        else:
            st.error(response.get("content", "Unknown error"))
            assistant_msg["error"] = response.get("content")

        st.session_state.messages.append(assistant_msg)

# ── Deep Summary for ANY chart ───────────────────────────────────
# Collect all charts: auto-generated + any from chat messages
all_charts = []
for i, c in enumerate(st.session_state.auto_charts):
    all_charts.append({
        "label": f"Auto Chart {i+1}: {c['title']}",
        "title": c["title"],
        "code": c["code"],
    })

chat_chart_idx = 0
for msg in st.session_state.messages:
    if msg["role"] == "assistant" and msg.get("code") and msg.get("figure"):
        chat_chart_idx += 1
        label = msg.get("text", "")[:50] or f"Chat chart {chat_chart_idx}"
        all_charts.append({
            "label": f"Chat Chart {chat_chart_idx}: {label}",
            "title": label,
            "code": msg["code"],
        })

if all_charts:
    st.divider()
    st.subheader("🔍 Get Deeper Summary")
    chart_labels = [c["label"] for c in all_charts]
    selected = st.selectbox("Select any chart for deeper analysis", chart_labels)

    if st.button("📝 Get Deeper Summary"):
        idx = chart_labels.index(selected)
        chart = all_charts[idx]
        with st.spinner("Generating deeper summary…"):
            summary = summarize_chart(
                st.session_state.metadata,
                chart["title"],
                chart["code"],
            )
        st.session_state.deep_summary = summary

    if st.session_state.deep_summary:
        st.markdown(st.session_state.deep_summary)