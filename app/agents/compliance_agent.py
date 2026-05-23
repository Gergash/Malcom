"""
ComplianceAgent: diagnóstico normativo y aduanero para reportes de InsightFlow.

Actúa como asesor de cumplimiento en Colombia y complementa el análisis
descriptivo-cuantitativo con alertas regulatorias y operativas.
"""
from __future__ import annotations

import os
from typing import Optional

try:
    from app.agents.model_manager import ModelManager
except ModuleNotFoundError:
    from agents.model_manager import ModelManager

MAX_RESPONSE_CHARS = 1800
DEFAULT_MODEL_NAMES = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-3-flash-preview",
]


class ComplianceAgent:
    """Genera un bloque obligatorio de cumplimiento para reportes analizados."""

    def __init__(self, model_names: Optional[list[str]] = None):
        identity = (
            "Eres ComplianceAgent de InsightFlow: asesor senior de cumplimiento normativo, aduanero y tributario "
            "en Colombia para comercio exterior, DIAN, INVIMA, RIPS y documentación corporativa.\n"
            "Siempre entregas recomendaciones accionables, preventivas y prudentes (sin inventar normas exactas no visibles)."
        )
        self._manager = ModelManager(
            model_names=model_names or DEFAULT_MODEL_NAMES,
            system_instruction=identity,
            api_key=os.getenv("GEMINI_API_KEY"),
        )

    def _cap(self, text: str) -> str:
        if not text:
            return ""
        if len(text) <= MAX_RESPONSE_CHARS:
            return text
        return text[: MAX_RESPONSE_CHARS - 30].rstrip() + "\n[Diagnóstico recortado]"

    def build_diagnostic(
        self,
        user_query: str,
        analysis_stdout: str,
        document_context: str = "",
    ) -> str:
        """
        Construye el bloque "Diagnóstico de Cumplimiento e Impacto Operativo".
        """
        prompt = (
            "Con base en la evidencia analítica, redacta SOLO el bloque obligatorio titulado exactamente:\n"
            "Diagnóstico de Cumplimiento e Impacto Operativo\n\n"
            "Requisitos obligatorios:\n"
            "1) Cruce Arancelario: si hay partidas arancelarias (ej. 2208500000), explica implicaciones posibles de "
            "arancel e IVA en Colombia para ese sector.\n"
            "2) Alertas de Tratados: identifica si los países de origen/compra parecen tener acuerdo comercial con Colombia "
            "y advierte posible aprovechamiento o pérdida de preferencia arancelaria.\n"
            "3) Gestión de Riesgos: alerta sobre riesgos legales/tributarios/operativos y mitigaciones concretas "
            "(INVIMA, consistencia FOB/CIF, riesgo de subfacturación DIAN, hubs logísticos/Zonas Francas).\n\n"
            "Reglas de salida:\n"
            "- Si falta evidencia, dilo explícitamente como 'Dato faltante para confirmar'.\n"
            "- No inventes porcentajes exactos ni artículos legales no visibles en evidencia.\n"
            "- Formato breve: subtítulos + viñetas accionables.\n\n"
            f"Consulta del usuario:\n{user_query}\n\n"
            f"Salida técnica del análisis de datos:\n{analysis_stdout}\n\n"
            f"Contexto documental (si existe):\n{document_context or '(sin contexto adicional)'}"
        )
        try:
            response = self._manager.generate_content(prompt)
            return self._cap((response.text or "").strip())
        except Exception:
            # Fallback robusto si hay fallo del modelo.
            return (
                "Diagnóstico de Cumplimiento e Impacto Operativo\n"
                "- Cruce Arancelario: Dato faltante para confirmar códigos arancelarios y su impacto exacto de arancel/IVA.\n"
                "- Alertas de Tratados: Dato faltante para confirmar país de origen y elegibilidad de preferencias.\n"
                "- Gestión de Riesgos: validar vigencias regulatorias (INVIMA), coherencia FOB/CIF y trazabilidad documental "
                "antes de declaración para reducir exposición ante DIAN."
            )

