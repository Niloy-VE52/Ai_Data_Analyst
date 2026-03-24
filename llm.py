import os
import re
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
from metadata import metadata_to_prompt_str
from code_runner import run_chart_code

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

AUTO_ANALYSIS_SYSTEM = """You are an expert data analyst.

Given CSV metadata, suggest exactly 4 of the most insightful charts for this dataset.
Choose chart types that best reveal patterns, distributions, relationships, or trends.

Respond ONLY with a valid JSON array. No markdown, no code fences, no explanation. Example:
[
  {
    "title": "Short chart title",
    "chart_request": "Detailed instruction for what to plot and how"
  }
]
"""

CHART_SYSTEM = """You are an expert data analyst and Python developer.

The DataFrame is already available as `df`. Do NOT import pandas or load files.
Use Plotly Express (px) or Plotly Graph Objects (go).
Assign the final figure to a variable named `fig`. Do NOT call fig.show().
Use meaningful titles, axis labels, and colors.

Respond EXACTLY in this format:

EXPLANATION:
<one or two sentences describing what the chart shows>

CODE:
```python
<plotly code here>
```
"""

CHART_EXPLAIN_SYSTEM = """You are an expert data analyst.

You are given a chart title and the CSV metadata. Provide a clear, insightful explanation
of what this chart reveals about the data. Mention specific patterns, trends, outliers,
or notable findings. Be specific, reference column names and numbers where relevant.
Keep it to 3-5 sentences.
"""

INSIGHT_SYSTEM = """You are an expert data analyst.

The user has uploaded a CSV file. You are given its metadata and the chat history.
Answer the user's question with clear, concise analytical insight — no code, no charts.
Be specific, reference column names and numbers where relevant.
Keep the answer to 3-5 sentences unless a longer explanation is needed.
"""

EXPLAIN_WITH_CHART_SYSTEM = """You are an expert data analyst and Python developer.

The user asked a question and received a text answer. Now generate a chart that
visually supports or explains the answer.

The DataFrame is already available as `df`. Do NOT import pandas or load files.
Use Plotly Express (px) or Plotly Graph Objects (go).
Assign the final figure to a variable named `fig`. Do NOT call fig.show().
Use meaningful titles, axis labels, and colors.

Respond EXACTLY in this format:

EXPLANATION:
<one or two sentences describing what the chart shows and how it relates to the answer>

CODE:
```python
<plotly code here>
```
"""

SUMMARIZE_CHART_SYSTEM = """You are an expert data analyst.

The user has selected a specific chart and wants a deeper analytical summary.
You are given the chart title, the code that generated it, and the CSV metadata.

Provide a thorough analytical summary covering:
- What the chart reveals about the data
- Key patterns, trends, and distributions visible
- Notable outliers or anomalies
- Actionable insights or implications
- Suggestions for further analysis

Write 5-8 detailed sentences. Be specific with column names, values, and statistics.
"""


def is_chart_request(prompt: str) -> bool:
    keywords = r"\b(show|plot|draw|chart|graph|visuali[sz]e|display)\b"
    return bool(re.search(keywords, prompt, re.I))


def auto_analyse(metadata: dict, df) -> dict:
    """Generate 4 charts automatically on upload. Returns debug info on failure."""
    metadata_str = metadata_to_prompt_str(metadata)
    suggestion_prompt = f"Here is the CSV metadata:\n\n{metadata_str}\n\nSuggest 4 insightful charts."

    # Step 1: get suggestions
    suggestions = []
    suggestion_error = None
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            config=types.GenerateContentConfig(system_instruction=AUTO_ANALYSIS_SYSTEM),
            contents=suggestion_prompt,
        )
        raw = resp.text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"```$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()
        suggestions = json.loads(raw)
    except Exception as e:
        suggestion_error = str(e)
        numeric_cols = [
            c["name"] for c in metadata["columns"] if c.get("kind") == "numeric"
        ]
        cat_cols = [
            c["name"] for c in metadata["columns"] if c.get("kind") == "categorical"
        ]
        suggestions = []
        if numeric_cols:
            suggestions.append({
                "title": f"Distribution of {numeric_cols[0]}",
                "chart_request": f"Show a histogram of the '{numeric_cols[0]}' column."
            })
        if len(numeric_cols) >= 2:
            suggestions.append({
                "title": f"{numeric_cols[0]} vs {numeric_cols[1]}",
                "chart_request": f"Show a scatter plot of '{numeric_cols[0]}' vs '{numeric_cols[1]}'."
            })
        if cat_cols and numeric_cols:
            suggestions.append({
                "title": f"{numeric_cols[0]} by {cat_cols[0]}",
                "chart_request": f"Show a bar chart of average '{numeric_cols[0]}' grouped by '{cat_cols[0]}'."
            })
        if len(numeric_cols) >= 1:
            suggestions.append({
                "title": f"Box plot of {numeric_cols[0]}",
                "chart_request": f"Show a box plot of '{numeric_cols[0]}'."
            })
        if not suggestions:
            suggestions.append({
                "title": "Column overview",
                "chart_request": "Show a bar chart of the value counts of the first categorical column."
            })

    # Step 2: generate + run each chart
    charts = []
    errors = []
    for s in suggestions[:4]:
        result = _generate_chart(metadata, s["chart_request"], df)
        if result["type"] == "chart":
            fig, error = run_chart_code(result["code"], df)
            if fig:
                # Generate explanation for this chart
                explanation = _explain_chart(metadata, s["title"])
                charts.append({
                    "title": s["title"],
                    "figure": fig,
                    "code": result["code"],
                    "explanation": explanation,
                })
            else:
                errors.append(f"Code exec failed for '{s['title']}': {error}")
        else:
            errors.append(f"Chart gen failed for '{s['title']}': {result.get('content')}")

    return {"charts": charts, "errors": errors, "suggestion_error": suggestion_error}


def _explain_chart(metadata: dict, chart_title: str) -> str:
    """Generate a short explanation for a chart based on its title and metadata."""
    metadata_str = metadata_to_prompt_str(metadata)
    prompt = f"CSV metadata:\n\n{metadata_str}\n\nChart title: {chart_title}\n\nExplain what this chart reveals about the data."
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            config=types.GenerateContentConfig(system_instruction=CHART_EXPLAIN_SYSTEM),
            contents=prompt,
        )
        return response.text.strip()
    except Exception:
        return ""


def ask_gemini(metadata: dict, user_question: str, df, chat_history: list, explain_with_chart: bool = False) -> dict:
    if is_chart_request(user_question):
        return _generate_chart(metadata, user_question, df)
    else:
        text_result = _generate_insight(metadata, user_question, chat_history)
        if explain_with_chart and text_result["type"] == "text":
            chart_result = _generate_explain_chart(metadata, user_question, text_result["content"], df)
            if chart_result["type"] == "chart":
                text_result["chart_code"] = chart_result["code"]
                text_result["chart_explanation"] = chart_result.get("explanation", "")
        return text_result


def _generate_chart(metadata: dict, request: str, df) -> dict:
    metadata_str = metadata_to_prompt_str(metadata)
    prompt = f"CSV metadata:\n\n{metadata_str}\n\nChart request: {request}"
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            config=types.GenerateContentConfig(system_instruction=CHART_SYSTEM),
            contents=prompt,
        )
        return _parse_chart_response(response.text.strip())
    except Exception as e:
        return {"type": "error", "content": str(e)}


def _generate_insight(metadata: dict, question: str, chat_history: list) -> dict:
    metadata_str = metadata_to_prompt_str(metadata)
    history_str = ""
    if chat_history:
        lines = []
        for msg in chat_history[-6:]:
            role = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"{role}: {msg['text']}")
        history_str = "\n".join(lines)

    prompt = f"""CSV metadata:

{metadata_str}

{"Chat history:" + chr(10) + history_str + chr(10) if history_str else ""}
User question: {question}
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            config=types.GenerateContentConfig(system_instruction=INSIGHT_SYSTEM),
            contents=prompt,
        )
        return {"type": "text", "content": response.text.strip()}
    except Exception as e:
        return {"type": "error", "content": str(e)}


def _generate_explain_chart(metadata: dict, question: str, answer: str, df) -> dict:
    """Generate a chart that visually supports a text answer."""
    metadata_str = metadata_to_prompt_str(metadata)
    prompt = f"""CSV metadata:

{metadata_str}

User question: {question}
Text answer given: {answer}

Generate a chart that visually explains or supports this answer.
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            config=types.GenerateContentConfig(system_instruction=EXPLAIN_WITH_CHART_SYSTEM),
            contents=prompt,
        )
        return _parse_chart_response(response.text.strip())
    except Exception as e:
        return {"type": "error", "content": str(e)}


def summarize_chart(metadata: dict, chart_title: str, chart_code: str) -> str:
    """Generate a deep analytical summary for a selected chart."""
    metadata_str = metadata_to_prompt_str(metadata)
    prompt = f"""CSV metadata:

{metadata_str}

Chart title: {chart_title}
Chart code:
```python
{chart_code}
```

Provide a thorough analytical summary of what this chart reveals.
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            config=types.GenerateContentConfig(system_instruction=SUMMARIZE_CHART_SYSTEM),
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        return f"Error generating summary: {e}"


def _parse_chart_response(raw: str) -> dict:
    code_match = re.search(r"```python\s*(.*?)```", raw, re.DOTALL)
    if not code_match:
        return {"type": "text", "content": raw}
    code = code_match.group(1).strip()
    explanation = ""
    exp_match = re.search(r"EXPLANATION:\s*(.*?)(?=CODE:|```)", raw, re.DOTALL)
    if exp_match:
        explanation = exp_match.group(1).strip()
    else:
        before = raw[: code_match.start()].strip()
        explanation = before.replace("EXPLANATION:", "").strip()
    return {"type": "chart", "code": code, "explanation": explanation}