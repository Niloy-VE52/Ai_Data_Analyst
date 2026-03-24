import traceback
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


def run_chart_code(code: str, df: pd.DataFrame):
    """
    Safely execute LLM-generated Plotly code.

    The code has access to:
      - df       : the user's DataFrame
      - px       : plotly.express
      - go       : plotly.graph_objects
      - pd       : pandas

    Returns:
      (fig, None)         on success
      (None, error_str)   on failure
    """
    local_vars = {
        "df": df.copy(),
        "px": px,
        "go": go,
        "pd": pd,
    }

    try:
        exec(code, {"__builtins__": __builtins__}, local_vars)
    except Exception:
        return None, traceback.format_exc()

    fig = local_vars.get("fig")
    if fig is None:
        return None, "The generated code did not produce a variable named `fig`."

    if not hasattr(fig, "to_dict"):
        return None, f"`fig` is not a valid Plotly figure (got {type(fig)})."

    return fig, None


def fig_to_json(fig):
    """Convert a Plotly figure to a JSON-serializable dict."""
    import json as _json
    return _json.loads(fig.to_json())
