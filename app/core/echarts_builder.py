"""
echarts_builder.py: transforma agregaciones de Pandas en objetos `option`
nativos de Apache ECharts listos para `myChart.setOption(...)`.

Estructura objetivo (importaciones agrupadas por mes / continente / etc.):
{
    "title": { "text": "Distribución Temporal de Operaciones", "left": "center",
               "textStyle": { "color": "#ffffff" } },
    "tooltip": { "trigger": "axis", "axisPointer": { "type": "shadow" } },
    "xAxis": { "type": "category", "data": [...] },
    "yAxis": { "type": "value", "splitLine": { "lineStyle": { "color": "#333333" } } },
    "series": [{
        "name": "Registros", "type": "bar", "data": [...],
        "itemStyle": { "color": "#ff6d00" }
    }]
}
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd


DEFAULT_TITLE = "Distribución Temporal de Operaciones"
DEFAULT_SERIES_NAME = "Registros"
DEFAULT_BAR_COLOR = "#ff6d00"
DEFAULT_TITLE_COLOR = "#ffffff"
DEFAULT_SPLIT_LINE_COLOR = "#333333"


_MONTH_ORDER_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
_MONTH_ORDER_EN = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


def _coerce_int_list(values: Iterable[Any]) -> List[int | float]:
    out: List[int | float] = []
    for v in values:
        if v is None:
            out.append(0)
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            out.append(0)
            continue
        if pd.isna(f):
            out.append(0)
        elif f.is_integer():
            out.append(int(f))
        else:
            out.append(round(f, 4))
    return out


def _coerce_label_list(values: Iterable[Any]) -> List[str]:
    return ["" if v is None else str(v) for v in values]


def _sort_chronological(labels: List[str], values: List[int | float]) -> tuple[List[str], List[int | float]]:
    """Si las etiquetas son meses (es/en), ordénalas cronológicamente."""
    lowered = [s.strip().lower() for s in labels]
    table: Optional[List[str]] = None
    if all(s in _MONTH_ORDER_ES for s in lowered if s):
        table = _MONTH_ORDER_ES
    elif all(s in _MONTH_ORDER_EN for s in lowered if s):
        table = _MONTH_ORDER_EN
    if table is None:
        return labels, values
    paired = sorted(
        zip(labels, values),
        key=lambda kv: table.index(kv[0].strip().lower()) if kv[0].strip().lower() in table else 99,
    )
    new_labels = [p[0] for p in paired]
    new_values = [p[1] for p in paired]
    return new_labels, new_values


def build_bar_option(
    categories: Sequence[Any],
    values: Sequence[Any],
    *,
    title: str = DEFAULT_TITLE,
    series_name: str = DEFAULT_SERIES_NAME,
    color: str = DEFAULT_BAR_COLOR,
) -> Dict[str, Any]:
    """Construye el objeto ECharts `option` con la estructura exacta requerida."""
    labels = _coerce_label_list(categories)
    nums = _coerce_int_list(values)
    labels, nums = _sort_chronological(labels, nums)

    return {
        "title": {
            "text": title,
            "left": "center",
            "textStyle": {"color": DEFAULT_TITLE_COLOR},
        },
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "shadow"},
        },
        "xAxis": {
            "type": "category",
            "data": labels,
        },
        "yAxis": {
            "type": "value",
            "splitLine": {"lineStyle": {"color": DEFAULT_SPLIT_LINE_COLOR}},
        },
        "series": [
            {
                "name": series_name,
                "type": "bar",
                "data": nums,
                "itemStyle": {"color": color},
            }
        ],
    }


def dataframe_to_echarts_option(
    df: pd.DataFrame,
    *,
    title: str = DEFAULT_TITLE,
    series_name: str = DEFAULT_SERIES_NAME,
    color: str = DEFAULT_BAR_COLOR,
    category_column: Optional[str] = None,
    value_column: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Acepta un DataFrame ya agregado (groupby + count/sum) con al menos
    dos columnas: categoría (eje X) y valor (eje Y).

    Si no se indican columnas, infiere:
      - category_column = primera columna no numérica.
      - value_column    = primera columna numérica.

    Retorna None si no se pueden inferir las columnas.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None

    cat_col = category_column
    val_col = value_column

    if cat_col is None:
        non_numeric = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        cat_col = non_numeric[0] if non_numeric else df.columns[0]

    if val_col is None:
        numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != cat_col]
        if not numeric:
            return None
        val_col = numeric[0]

    if cat_col not in df.columns or val_col not in df.columns:
        return None

    return build_bar_option(
        df[cat_col].tolist(),
        df[val_col].tolist(),
        title=title,
        series_name=series_name,
        color=color,
    )


def aggregate_and_build_option(
    df: pd.DataFrame,
    group_by: str,
    *,
    value_column: Optional[str] = None,
    agg: str = "count",
    title: str = DEFAULT_TITLE,
    series_name: str = DEFAULT_SERIES_NAME,
    color: str = DEFAULT_BAR_COLOR,
) -> Optional[Dict[str, Any]]:
    """
    Atajo end-to-end: agrupa el DataFrame por `group_by`, calcula la agregación
    indicada (count/sum/mean) y devuelve el option ECharts.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    if group_by not in df.columns:
        return None

    if agg == "count":
        agg_series = df.groupby(group_by).size()
        agg_df = agg_series.reset_index(name=series_name)
        return dataframe_to_echarts_option(
            agg_df,
            title=title,
            series_name=series_name,
            color=color,
            category_column=group_by,
            value_column=series_name,
        )

    if value_column is None or value_column not in df.columns:
        return None
    if agg not in {"sum", "mean", "max", "min"}:
        return None
    grouped = df.groupby(group_by)[value_column]
    agg_series = getattr(grouped, agg)()
    agg_df = agg_series.reset_index()
    return dataframe_to_echarts_option(
        agg_df,
        title=title,
        series_name=series_name,
        color=color,
        category_column=group_by,
        value_column=value_column,
    )
