import pandas as pd
import json


def extract_metadata(df: pd.DataFrame) -> dict:
    meta = {
        "shape": {"rows": df.shape[0], "columns": df.shape[1]},
        "columns": [],
        "sample_rows": df.head(5).to_dict(orient="records"),
    }

    for col in df.columns:
        series = df[col]
        col_info = {
            "name": col,
            "dtype": str(series.dtype),
            "null_count": int(series.isna().sum()),
            "null_pct": round(series.isna().mean() * 100, 2),
        }

        if pd.api.types.is_numeric_dtype(series):
            clean = series.dropna()
            col_info.update({
                "kind": "numeric",
                "min": round(float(clean.min()), 4) if len(clean) else None,
                "max": round(float(clean.max()), 4) if len(clean) else None,
                "mean": round(float(clean.mean()), 4) if len(clean) else None,
                "std": round(float(clean.std()), 4) if len(clean) else None,
                "median": round(float(clean.median()), 4) if len(clean) else None,
            })
        elif pd.api.types.is_datetime64_any_dtype(series):
            col_info.update({
                "kind": "datetime",
                "min": str(series.min()),
                "max": str(series.max()),
            })
        else:
            n_unique = series.nunique()
            col_info.update({
                "kind": "categorical",
                "n_unique": int(n_unique),
                "top_values": (
                    series.value_counts().head(10).to_dict()
                    if n_unique <= 50
                    else {}
                ),
            })

        meta["columns"].append(col_info)

    return meta


def metadata_to_prompt_str(metadata: dict) -> str:
    return json.dumps(metadata, indent=2, default=str)