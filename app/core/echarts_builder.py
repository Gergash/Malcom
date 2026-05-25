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
    chart_type: str = "bar",
) -> Optional[Dict[str, Any]]:
    """
    Atajo end-to-end: agrupa el DataFrame por `group_by`, calcula la agregación
    indicada (count/sum/mean/max/min) y devuelve el option ECharts.

    `chart_type` puede ser: "bar" | "line" | "pie" | "horizontal_bar".
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    if group_by not in df.columns:
        return None

    if agg == "count":
        agg_series = df.groupby(group_by).size()
        agg_df = agg_series.reset_index(name=series_name)
        cat_col = group_by
        val_col = series_name
    else:
        if value_column is None or value_column not in df.columns:
            return None
        if agg not in {"sum", "mean", "max", "min"}:
            return None
        agg_series = getattr(df.groupby(group_by)[value_column], agg)()
        agg_df = agg_series.reset_index()
        cat_col = group_by
        val_col = value_column

    cats = agg_df[cat_col].tolist()
    vals = agg_df[val_col].tolist()
    if chart_type == "line":
        return build_line_option(cats, vals, title=title, series_name=series_name, color=color)
    if chart_type == "pie":
        return build_pie_option(cats, vals, title=title, series_name=series_name)
    if chart_type == "horizontal_bar":
        return build_horizontal_bar_option(cats, vals, title=title, series_name=series_name, color=color)
    return build_bar_option(cats, vals, title=title, series_name=series_name, color=color)


def build_line_option(
    categories: Sequence[Any],
    values: Sequence[Any],
    *,
    title: str = DEFAULT_TITLE,
    series_name: str = DEFAULT_SERIES_NAME,
    color: str = DEFAULT_BAR_COLOR,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Línea: ideal para series temporales o tendencias."""
    labels = _coerce_label_list(categories)
    nums = _coerce_int_list(values)
    labels, nums = _sort_chronological(labels, nums)
    return {
        "title": {"text": title, "left": "center", "textStyle": {"color": DEFAULT_TITLE_COLOR}},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": labels, "boundaryGap": False},
        "yAxis": {"type": "value", "splitLine": {"lineStyle": {"color": DEFAULT_SPLIT_LINE_COLOR}}},
        "series": [{
            "name": series_name, "type": "line", "data": nums,
            "smooth": smooth, "showSymbol": True,
            "itemStyle": {"color": color},
            "areaStyle": {"opacity": 0.18},
        }],
    }


def build_pie_option(
    categories: Sequence[Any],
    values: Sequence[Any],
    *,
    title: str = DEFAULT_TITLE,
    series_name: str = DEFAULT_SERIES_NAME,
) -> Dict[str, Any]:
    """Donut: ideal para proporciones de pocas categorías (<=10)."""
    labels = _coerce_label_list(categories)
    nums = _coerce_int_list(values)
    data = [{"name": l, "value": v} for l, v in zip(labels, nums)]
    return {
        "title": {"text": title, "left": "center", "textStyle": {"color": DEFAULT_TITLE_COLOR}},
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "legend": {"bottom": 8, "textStyle": {"color": "#8b98a8"}},
        "series": [{
            "name": series_name, "type": "pie",
            "radius": ["38%", "70%"],
            "avoidLabelOverlap": True,
            "itemStyle": {"borderColor": "#0e1116", "borderWidth": 2},
            "label": {"color": "#e8edf5"},
            "data": data,
        }],
    }


def build_horizontal_bar_option(
    categories: Sequence[Any],
    values: Sequence[Any],
    *,
    title: str = DEFAULT_TITLE,
    series_name: str = DEFAULT_SERIES_NAME,
    color: str = DEFAULT_BAR_COLOR,
) -> Dict[str, Any]:
    """Bar horizontal: ideal para rankings con categorías de etiqueta larga."""
    labels = _coerce_label_list(categories)
    nums = _coerce_int_list(values)
    paired = sorted(zip(labels, nums), key=lambda kv: kv[1])
    labels = [p[0] for p in paired]
    nums = [p[1] for p in paired]
    return {
        "title": {"text": title, "left": "center", "textStyle": {"color": DEFAULT_TITLE_COLOR}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "value", "splitLine": {"lineStyle": {"color": DEFAULT_SPLIT_LINE_COLOR}}},
        "yAxis": {"type": "category", "data": labels},
        "series": [{"name": series_name, "type": "bar", "data": nums, "itemStyle": {"color": color}}],
    }


def build_scatter_option(
    x_values: Sequence[Any],
    y_values: Sequence[Any],
    *,
    title: str = DEFAULT_TITLE,
    series_name: str = DEFAULT_SERIES_NAME,
    color: str = DEFAULT_BAR_COLOR,
    x_label: str = "X",
    y_label: str = "Y",
) -> Dict[str, Any]:
    """Dispersión: ideal para correlación entre dos variables numéricas."""
    xs = _coerce_int_list(x_values)
    ys = _coerce_int_list(y_values)
    pts = [[x, y] for x, y in zip(xs, ys)]
    return {
        "title": {"text": title, "left": "center", "textStyle": {"color": DEFAULT_TITLE_COLOR}},
        "tooltip": {"trigger": "item"},
        "xAxis": {"type": "value", "name": x_label, "splitLine": {"lineStyle": {"color": DEFAULT_SPLIT_LINE_COLOR}}},
        "yAxis": {"type": "value", "name": y_label, "splitLine": {"lineStyle": {"color": DEFAULT_SPLIT_LINE_COLOR}}},
        "series": [{"name": series_name, "type": "scatter", "symbolSize": 9, "data": pts, "itemStyle": {"color": color}}],
    }


def build_heatmap_option(
    matrix: Sequence[Sequence[float]],
    *,
    x_labels: Sequence[str],
    y_labels: Sequence[str],
    title: str = "Matriz de Correlación",
) -> Dict[str, Any]:
    """Heatmap: matriz de correlación (ej. .corr() de pandas)."""
    data = []
    flat: List[float] = []
    for i, row in enumerate(matrix):
        for j, v in enumerate(row):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                fv = 0.0
            if pd.isna(fv):
                fv = 0.0
            data.append([j, i, round(fv, 3)])
            flat.append(fv)
    vmin = min(flat) if flat else -1.0
    vmax = max(flat) if flat else 1.0
    return {
        "title": {"text": title, "left": "center", "textStyle": {"color": DEFAULT_TITLE_COLOR}},
        "tooltip": {"position": "top"},
        "grid": {"height": "65%", "top": "12%"},
        "xAxis": {"type": "category", "data": list(x_labels), "splitArea": {"show": True}, "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "category", "data": list(y_labels), "splitArea": {"show": True}},
        "visualMap": {
            "min": min(vmin, -1.0), "max": max(vmax, 1.0),
            "calculable": True, "orient": "horizontal", "left": "center", "bottom": "2%",
            "inRange": {"color": ["#28468C", "#0e1116", "#ff6d00"]},
            "textStyle": {"color": "#8b98a8"},
        },
        "series": [{
            "name": title, "type": "heatmap", "data": data,
            "label": {"show": True, "color": "#e8edf5", "fontSize": 10},
            "emphasis": {"itemStyle": {"shadowBlur": 10, "shadowColor": "rgba(0,0,0,0.5)"}},
        }],
    }


def correlation_heatmap_from_df(
    df: pd.DataFrame,
    *,
    numeric_only: bool = True,
    title: str = "Matriz de Correlación",
    max_columns: int = 12,
) -> Optional[Dict[str, Any]]:
    """Construye un heatmap ECharts a partir de la matriz de correlación del DataFrame."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    try:
        corr = df.corr(numeric_only=numeric_only)
    except Exception:
        return None
    if corr.empty:
        return None
    if len(corr.columns) > max_columns:
        corr = corr.iloc[:max_columns, :max_columns]
    return build_heatmap_option(
        corr.values.tolist(),
        x_labels=[str(c) for c in corr.columns],
        y_labels=[str(c) for c in corr.index],
        title=title,
    )


def build_stacked_bar_option(
    categories: Sequence[Any],
    series_dict: Dict[str, Sequence[Any]],
    *,
    title: str = DEFAULT_TITLE,
) -> Dict[str, Any]:
    """Barras apiladas: ideal para composiciones por categoría."""
    labels = _coerce_label_list(categories)
    series = []
    for name, values in series_dict.items():
        series.append({
            "name": str(name), "type": "bar", "stack": "total",
            "emphasis": {"focus": "series"},
            "data": _coerce_int_list(values),
        })
    return {
        "title": {"text": title, "left": "center", "textStyle": {"color": DEFAULT_TITLE_COLOR}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"bottom": 4, "textStyle": {"color": "#8b98a8"}},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value", "splitLine": {"lineStyle": {"color": DEFAULT_SPLIT_LINE_COLOR}}},
        "series": series,
    }
