"""
dashboard_builder.py: ensambla el tablero ejecutivo multi-widget para el visor.

Contrato (sibling de echarts_option en la respuesta del Brain):
{
  "title": "...",
  "subtitle": "...",
  "live": true,
  "metrics": [{"label", "value", "tone"}],
  "widgets": [
    {"id", "kind": "echarts"|"qa"|"bullets", "title", "span"?, "option"?, "items"?}
  ]
}
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

try:
    from app.core.echarts_builder import (
        DEFAULT_BAR_COLOR,
        build_area_option,
        build_horizontal_bar_option,
        strip_chart_title,
    )
except ModuleNotFoundError:
    from core.echarts_builder import (  # type: ignore
        DEFAULT_BAR_COLOR,
        build_area_option,
        build_horizontal_bar_option,
        strip_chart_title,
    )


def _tone_for_delta(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("-") or s.startswith("−"):
        return "down"
    if s.startswith("+"):
        return "up"
    return "neutral"


def _first_sentences(text: str, n: int = 3) -> List[str]:
    """Extrae hasta n frases/bullets cortos de la narrativa del analista."""
    if not text or not text.strip():
        return []
    cleaned = re.sub(r"\*+", "", text)
    cleaned = re.sub(r"#{1,6}\s*", "", cleaned)
    # Preferir líneas con viñetas
    bullets = []
    for line in cleaned.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("-", "•", "–")) or re.match(r"^\d+[\.\)]\s", line):
            item = re.sub(r"^[-•–\d\.\)\s]+", "", line).strip()
            if len(item) > 12:
                bullets.append(item[:220])
        if len(bullets) >= n:
            return bullets
    # Fallback: frases
    parts = re.split(r"(?<=[\.\!\?])\s+", cleaned.replace("\n", " "))
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if len(p) < 20:
            continue
        out.append(p[:220])
        if len(out) >= n:
            break
    return out


def _metrics_from_option(option: Dict[str, Any]) -> List[Dict[str, str]]:
    """Deriva hasta 3 KPIs simples del series data del chart primario."""
    try:
        series = option.get("series") or []
        if not series:
            return []
        data = series[0].get("data") or []
        nums: List[float] = []
        for v in data:
            if isinstance(v, (int, float)):
                nums.append(float(v))
            elif isinstance(v, dict) and "value" in v:
                try:
                    nums.append(float(v["value"]))
                except (TypeError, ValueError):
                    continue
        if len(nums) < 2:
            if nums:
                return [{"label": "Total", "value": _fmt_num(nums[0]), "tone": "neutral"}]
            return []
        total = sum(nums)
        last = nums[-1]
        prev = nums[-2] if len(nums) >= 2 else nums[0]
        delta_pct = ((last - prev) / abs(prev) * 100.0) if prev else 0.0
        peak = max(nums)
        delta_s = f"{delta_pct:+.1f}%".replace(".", ",")
        return [
            {"label": "Total", "value": _fmt_num(total), "tone": "neutral"},
            {"label": "Variación", "value": delta_s, "tone": _tone_for_delta(delta_s)},
            {"label": "Máximo", "value": _fmt_num(peak), "tone": "up"},
        ]
    except Exception:
        return []


def _fmt_num(n: float) -> str:
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n)):,}".replace(",", ".")
    return f"{n:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _as_area_option(option: Dict[str, Any], *, color: str) -> Dict[str, Any]:
    """Convierte/refuerza el option primario como área suave para el panel wide."""
    opt = strip_chart_title(dict(option))
    # Si ya es line/bar con series, forzar look area
    series = opt.get("series")
    if isinstance(series, list) and series:
        s0 = dict(series[0])
        if s0.get("type") in ("bar", "line", None):
            s0["type"] = "line"
            s0["smooth"] = True
            s0["showSymbol"] = False
            s0["areaStyle"] = {
                "opacity": 0.35,
                "color": {
                    "type": "linear",
                    "x": 0, "y": 0, "x2": 0, "y2": 1,
                    "colorStops": [
                        {"offset": 0, "color": color},
                        {"offset": 1, "color": "rgba(57,255,20,0.02)"},
                    ],
                },
            }
            s0["itemStyle"] = {"color": color}
            s0["lineStyle"] = {"width": 2, "color": color}
            opt["series"] = [s0] + list(series[1:])
        # Quitar título interno (el card HTML ya lo muestra)
        if "title" in opt:
            opt["title"] = {"show": False}
        opt.setdefault("grid", {"left": 48, "right": 16, "top": 24, "bottom": 32})
    return opt


def _perception_from_primary(option: Dict[str, Any], *, color: str) -> Optional[Dict[str, Any]]:
    """Segundo chart: top categorías como barras horizontales (percepción/escenarios)."""
    try:
        series = option.get("series") or []
        if not series:
            return None
        s0 = series[0]
        data = s0.get("data") or []
        cats: List[str] = []
        vals: List[float] = []
        x_data = (option.get("xAxis") or {}).get("data") if isinstance(option.get("xAxis"), dict) else None
        y_data = (option.get("yAxis") or {}).get("data") if isinstance(option.get("yAxis"), dict) else None
        labels = x_data or y_data
        if s0.get("type") == "pie":
            for item in data:
                if isinstance(item, dict):
                    cats.append(str(item.get("name", "")))
                    vals.append(float(item.get("value") or 0))
        elif labels and isinstance(labels, list):
            for i, v in enumerate(data):
                if i >= len(labels):
                    break
                cats.append(str(labels[i]))
                if isinstance(v, (int, float)):
                    vals.append(float(v))
                elif isinstance(v, dict):
                    vals.append(float(v.get("value") or 0))
                else:
                    vals.append(0.0)
        if len(cats) < 2 or len(vals) < 2:
            return None
        # Top 5
        paired = sorted(zip(cats, vals), key=lambda kv: kv[1], reverse=True)[:5]
        cats = [p[0] for p in paired]
        vals = [p[1] for p in paired]
        # Normalizar a % si parecen partes
        total = sum(vals) or 1.0
        if all(v >= 0 for v in vals) and abs(total - 100) > 5:
            vals_pct = [round(v / total * 100, 1) for v in vals]
            opt = build_horizontal_bar_option(
                cats, vals_pct, title="", series_name="Participación %", color=color
            )
        else:
            opt = build_horizontal_bar_option(
                cats, vals, title="", series_name=str(s0.get("name") or "Valor"), color=color
            )
        opt["title"] = {"show": False}
        opt.setdefault("grid", {"left": 100, "right": 24, "top": 16, "bottom": 24})
        return opt
    except Exception:
        return None


def assemble_executive_dashboard(
    *,
    primary_option: Optional[Dict[str, Any]],
    narrative: str = "",
    user_query: str = "",
    primary_color: Optional[str] = None,
    title: str = "Panel unificado",
    subtitle: str = "InsightFlow · Análisis",
) -> Optional[Dict[str, Any]]:
    """
    Construye el objeto `dashboard` multi-widget.
    Si solo hay primary_option, degrada a un único widget echarts wide.
    """
    if not primary_option or not isinstance(primary_option, dict):
        return None

    color = (primary_color or "").strip() or DEFAULT_BAR_COLOR
    metrics = _metrics_from_option(primary_option)
    main_opt = _as_area_option(primary_option, color=color)
    perception = _perception_from_primary(primary_option, color=color)
    bullets = _first_sentences(narrative, 3)
    if not bullets:
        bullets = [
            "Revisa la gráfica principal para identificar el patrón dominante.",
            "Compara categorías extremas para priorizar acciones.",
            "Itera en el chat para profundizar en el segmento crítico.",
        ]

    widgets: List[Dict[str, Any]] = [
        {
            "id": "main_trend",
            "kind": "echarts",
            "title": title,
            "span": "wide",
            "option": main_opt,
        },
    ]
    if perception:
        widgets.append(
            {
                "id": "perception",
                "kind": "echarts",
                "title": "Percepción",
                "span": "narrow",
                "option": perception,
            }
        )
        # Escenarios: reordenar top 3 como barras horizontales distintas
        try:
            scen = _perception_from_primary(primary_option, color="#7CFF6B")
            if scen:
                widgets.append(
                    {
                        "id": "scenarios",
                        "kind": "echarts",
                        "title": "Escenarios comparados",
                        "span": "third",
                        "option": scen,
                    }
                )
        except Exception:
            pass

    qa_items: List[Dict[str, str]] = []
    q = (user_query or "").strip()
    if q:
        insight = bullets[0] if bullets else "Ver hallazgos en el resumen ejecutivo."
        qa_items.append({"q": q[:180], "a": insight})
    else:
        qa_items.append(
            {
                "q": "¿Qué destaca este análisis?",
                "a": bullets[0] if bullets else "Revisa el panel principal.",
            }
        )

    widgets.append(
        {
            "id": "qa",
            "kind": "qa",
            "title": "Flujo ilustrativo",
            "span": "third",
            "items": qa_items,
        }
    )
    widgets.append(
        {
            "id": "exec",
            "kind": "bullets",
            "title": "Resumen ejecutivo",
            "span": "third",
            "items": bullets[:3],
        }
    )

    # Si no hubo perception, asegurar al menos primary + qa + exec
    return {
        "title": title,
        "subtitle": subtitle,
        "live": True,
        "metrics": metrics,
        "widgets": widgets,
    }
