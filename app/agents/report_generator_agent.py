"""
report_generator_agent.py: instrucciones de narrativa y estilo para informes (PDF/Excel).

Actúa como contrato entre la interfaz PowerUps (ReportConfig) y el AnalystAgent:
traduce Big Data en redacción alineada al stakeholder y al dialecto, sin que la IA "adivine" el diseño.
"""

from __future__ import annotations

from typing import Optional

try:
    from app.api.schemas import ReportConfig
except ModuleNotFoundError:
    from api.schemas import ReportConfig


def build_report_translator_instructions(config: Optional[ReportConfig]) -> str:
    """Bloque de prompt para el modelo: comunicación corporativa + reglas del ReportConfig."""
    if config is None:
        return ""

    return (
        "\n\n---\n"
        "REPORTE — COMUNICACIÓN CORPORATIVA Y BI (obligatorio si generas texto para PDF/Excel):\n"
        "Eres un experto en Comunicación Corporativa y BI. Redacta hallazgos siguiendo estas reglas:\n"
        "1. Adaptación de audiencia: si el lector es perfil ejecutivo, prioriza KPIs de rentabilidad, "
        "riesgo y visión macro; si es técnico, prioriza métricas de precisión, reproducibilidad y arquitectura; "
        "si es marketing, prioriza narrativa de cliente, conversión y mensajes claros.\n"
        "2. Sensibilidad cultural: usa variaciones del español acordes al dialecto indicado; tono que genere "
        "confianza local (sin forzar modismos artificiales).\n"
        "3. Consistencia visual: en cualquier referencia a formato de informe, respeta estrictamente los "
        "códigos hex y tamaños de fuente del contrato; el backend aplicará esos valores al PDF y Excel.\n"
        f"CONTRATO DE ESTILO ACTUAL:\n"
        f"- Perfil del stakeholder: {config.stakeholder_profile}\n"
        f"- Estilo de lenguaje: {config.language_style}\n"
        f"- Dialecto / región: {config.dialect}\n"
        f"- Color primario: {config.primary_color} | Secundario: {config.secondary_color}\n"
        f"- Tamaños: cuerpo {config.font_size_body} pt, títulos {config.font_size_titles} pt\n"
    )
