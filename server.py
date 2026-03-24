import os
import json
import pandas as pd
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from metadata import extract_metadata, metadata_to_prompt_str
from llm import auto_analyse, ask_gemini, summarize_chart
from code_runner import run_chart_code, fig_to_json

app = Flask(__name__, static_folder="static")

# ── In-memory state ──────────────────────────────────────────────
state = {
    "df": None,
    "metadata": None,
    "auto_charts": [],     # list of {title, code, explanation, figure_json}
    "chat_charts": [],     # list of {title, code, figure_json}
}


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/upload", methods=["POST"])
def upload_csv():
    """Upload CSV → metadata + 4 auto-charts."""
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        df = pd.read_csv(file)
    except Exception as e:
        return jsonify({"error": f"Failed to parse CSV: {e}"}), 400

    state["df"] = df
    state["metadata"] = extract_metadata(df)
    state["chat_charts"] = []

    # Auto-analyse
    result = auto_analyse(state["metadata"], df)

    auto_charts = []
    for chart in result["charts"]:
        chart_data = {
            "title": chart["title"],
            "code": chart["code"],
            "explanation": chart.get("explanation", ""),
            "figure_json": fig_to_json(chart["figure"]),
        }
        auto_charts.append(chart_data)

    state["auto_charts"] = auto_charts

    # Build sample rows for preview
    sample = df.head(10).to_dict(orient="records")
    columns = list(df.columns)

    return jsonify({
        "shape": {"rows": df.shape[0], "columns": df.shape[1]},
        "columns": columns,
        "sample": sample,
        "auto_charts": auto_charts,
        "errors": result.get("errors", []),
        "suggestion_error": result.get("suggestion_error"),
    })


@app.route("/api/chat", methods=["POST"])
def chat():
    """Handle user query — text and/or chart response."""
    if state["df"] is None:
        return jsonify({"error": "No CSV uploaded yet"}), 400

    data = request.get_json()
    question = data.get("question", "").strip()
    explain_with_chart = data.get("explain_with_chart", False)
    chat_history = data.get("chat_history", [])

    if not question:
        return jsonify({"error": "No question provided"}), 400

    response = ask_gemini(
        metadata=state["metadata"],
        user_question=question,
        df=state["df"],
        chat_history=chat_history,
        explain_with_chart=explain_with_chart,
    )

    result = {"type": response["type"]}

    if response["type"] == "chart":
        result["explanation"] = response.get("explanation", "")
        result["code"] = response.get("code", "")
        fig, error = run_chart_code(response["code"], state["df"])
        if fig:
            result["figure_json"] = fig_to_json(fig)
            # Track chat chart
            state["chat_charts"].append({
                "title": result["explanation"][:60] or "Chat chart",
                "code": result["code"],
                "figure_json": result["figure_json"],
            })
        else:
            result["error"] = error

    elif response["type"] == "text":
        result["content"] = response["content"]
        # Check if explain_with_chart produced a chart
        if response.get("chart_code"):
            result["chart_explanation"] = response.get("chart_explanation", "")
            result["chart_code"] = response["chart_code"]
            fig, error = run_chart_code(response["chart_code"], state["df"])
            if fig:
                result["chart_figure_json"] = fig_to_json(fig)
                state["chat_charts"].append({
                    "title": result["chart_explanation"][:60] or "Supporting chart",
                    "code": result["chart_code"],
                    "figure_json": result["chart_figure_json"],
                })
            else:
                result["chart_error"] = error

    else:
        result["content"] = response.get("content", "Unknown error")

    return jsonify(result)


@app.route("/api/deep-summary", methods=["POST"])
def deep_summary():
    """Get deeper analytical summary for a chart."""
    if state["metadata"] is None:
        return jsonify({"error": "No CSV uploaded yet"}), 400

    data = request.get_json()
    source = data.get("source", "auto")   # "auto" or "chat"
    index = data.get("index", 0)

    charts = state["auto_charts"] if source == "auto" else state["chat_charts"]

    if index < 0 or index >= len(charts):
        return jsonify({"error": "Invalid chart index"}), 400

    chart = charts[index]
    summary = summarize_chart(state["metadata"], chart["title"], chart["code"])

    return jsonify({"summary": summary})


@app.route("/api/all-charts", methods=["GET"])
def all_charts():
    """Return list of all chart titles for the deep summary selector."""
    charts = []
    for i, c in enumerate(state["auto_charts"]):
        charts.append({"label": f"Auto Chart {i+1}: {c['title']}", "source": "auto", "index": i})
    for i, c in enumerate(state["chat_charts"]):
        charts.append({"label": f"Chat Chart {i+1}: {c['title']}", "source": "chat", "index": i})
    return jsonify({"charts": charts})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
