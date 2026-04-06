"""
orchestrator.py: motor central que enruta mensajes a los agentes correctos.

Extrae la lógica de negocio de app/main.py para que sea reutilizable
tanto por el bot de Telegram como por el endpoint FastAPI /api/v1/chat.

Responsabilidades:
  - Detectar si la consulta es de predicción o análisis general.
  - Invocar al agente correspondiente en un executor de hilos
    (los agentes son síncronos; el orquestador es async).
  - Devolver un dict estructurado con la respuesta y los artefactos generados.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil

try:
    from app.agents.analyst_agent import AnalystAgent
    from app.agents.predictor_agent import PredictorAgent
    from app.agents.knowledge_agent import DOC_EXTENSIONS
except ModuleNotFoundError:
    from agents.analyst_agent import AnalystAgent
    from agents.predictor_agent import PredictorAgent
    from agents.knowledge_agent import DOC_EXTENSIONS


PREDICTION_KEYWORDS = (
    "stock", "comprar", "buy", "cuánto", "cuanto", "how much",
    "pronóstico", "pronostico", "forecast",
    "recomendación", "recomendacion", "recommend",
    "inventory", "inventario", "pedido", "order",
    "esta semana", "this week", "semanas", "weeks", "predic",
)


class Orchestrator:
    """
    Enrutador de mensajes → agentes.

    Cada instancia está ligada a un chat_id para garantizar el aislamiento
    de archivos en data/{chat_id}/.
    """

    def __init__(self, chat_id: int | str) -> None:
        self.chat_id = str(chat_id)
        self.data_dir = Path("data") / self.chat_id
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def ingest_file(self, source_path: str, filename: str) -> dict:
        """
        Copia un archivo a data/{chat_id}/ y, si es documento, lo indexa.

        Retorna:
            {
                "saved_path": str,
                "indexed": bool,
                "chunks": int,
                "error": str | None,
                "message": str,
            }
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        filename = os.path.basename(filename or "archivo")
        target_path = self.data_dir / filename
        source_abs = os.path.abspath(source_path)
        target_abs = os.path.abspath(str(target_path))
        if source_abs != target_abs:
            shutil.copy2(source_abs, target_abs)

        suffix = target_path.suffix.lower()
        if suffix in DOC_EXTENSIONS:
            analyst = AnalystAgent()
            knowledge_agent = analyst.get_knowledge_agent(int(self.chat_id))
            n_chunks, err = knowledge_agent.index_file(str(target_path), source_id=filename)
            if err:
                return {
                    "saved_path": str(target_path),
                    "indexed": False,
                    "chunks": 0,
                    "error": err,
                    "message": f"Archivo '{filename}' guardado, pero no se pudo indexar: {err}",
                }
            return {
                "saved_path": str(target_path),
                "indexed": True,
                "chunks": int(n_chunks),
                "error": None,
                "message": f"Archivo '{filename}' guardado e indexado ({n_chunks} fragmentos).",
            }

        return {
            "saved_path": str(target_path),
            "indexed": False,
            "chunks": 0,
            "error": None,
            "message": f"Archivo '{filename}' guardado.",
        }

    async def process_message(self, message: str) -> dict:
        """
        Procesa un mensaje de texto y devuelve:

            {
                "response":   str,   # texto de respuesta del agente
                "has_pdf":    bool,  # ¿se generó reporte PDF?
                "has_excel":  bool,  # ¿se generó reporte Excel?
                "has_chart":  bool,  # ¿se generó imagen de gráfica?
                "pdf_path":   str | None,
                "excel_path": str | None,
                "chart_path": str | None,
            }
        """
        loop = asyncio.get_event_loop()

        if self._is_prediction_query(message):
            response_text = await loop.run_in_executor(
                None, self._run_predictor, message
            )
        else:
            response_text = await self._run_analyst(message, loop)

        return self._build_result(response_text)

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _is_prediction_query(self, message: str) -> bool:
        lower = message.lower()
        return any(kw in lower for kw in PREDICTION_KEYWORDS)

    def _run_predictor(self, message: str) -> str:
        predictor = PredictorAgent()
        user_data_folder = str(self.data_dir.resolve())
        return predictor.answer_business_question(
            message,
            local_file_path=None,
            user_data_folder=user_data_folder,
        ) or ""

    async def _run_analyst(self, message: str, loop: asyncio.AbstractEventLoop) -> str:
        analyst = AnalystAgent()
        user_data_folder = str(self.data_dir.resolve())

        def _sync_call():
            # analyze_data puede ser sync o async según la versión del agente.
            # Llamamos la versión sync aquí; si el agente expone un método async
            # directo, usarlo directamente en el await más abajo.
            import inspect
            result = analyst.analyze_data(
                message,
                local_file_path=None,
                user_data_folder=user_data_folder,
                chat_id=self.chat_id,
            )
            # Si el agente devuelve una coroutine (análisis async nativo), la ejecutamos
            if inspect.isawaitable(result):
                return None, result  # señal para await fuera del executor
            return result, None

        response_text, maybe_coro = await loop.run_in_executor(None, _sync_call)

        # Si analyze_data es async, la ejecutamos directamente en el event loop
        if maybe_coro is not None:
            response_text = await maybe_coro

        # Capturar reportes pendientes antes de que el objeto analyst se destruya
        self._pending_pdf = analyst.peek_pending_pdf_report()
        self._pending_excel = analyst.peek_pending_excel_report()
        analyst.clear_pending_pdf_report()
        analyst.clear_pending_excel_report()

        return response_text or ""

    def _build_result(self, response_text: str) -> dict:
        pdf_path = getattr(self, "_pending_pdf", None)
        excel_path = getattr(self, "_pending_excel", None)
        chart_name = f"output_plot_{self.chat_id}.png"
        chart_abs = self.data_dir / chart_name
        has_chart = chart_abs.is_file()

        return {
            "response": response_text,
            "has_pdf": bool(pdf_path and os.path.isfile(pdf_path)),
            "has_excel": bool(excel_path and os.path.isfile(excel_path)),
            "has_chart": has_chart,
            "pdf_path": pdf_path if (pdf_path and os.path.isfile(pdf_path)) else None,
            "excel_path": excel_path if (excel_path and os.path.isfile(excel_path)) else None,
            "chart_path": str(chart_abs) if has_chart else None,
        }
