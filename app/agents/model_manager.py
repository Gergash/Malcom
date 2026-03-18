"""
ModelManager: gestión centralizada de modelos Gemini con health-check y fallback.

- Mantiene un cooldown por modelo ante errores 429 (sin llamadas extra a la API).
- Si todos los modelos están en cooldown, espera al que libere antes y reintenta.
- Expone health_status() para diagnóstico.
"""
import time
import logging
from typing import Any, Dict, List, Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAMES: List[str] = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-3-flash-preview",
]

DEFAULT_EMBEDDING_MODEL: str = "models/gemini-embedding-001"
DEFAULT_COOLDOWN_SECONDS: int = 60


def _is_rate_limit_error(exc: Exception) -> bool:
    """True si el error es 429 / rate limit / quota exhausted."""
    msg = str(exc).lower()
    if any(token in msg for token in ("429", "rate", "quota", "resource exhausted")):
        return True
    code = getattr(exc, "code", None)
    try:
        return code is not None and int(code) == 429
    except (TypeError, ValueError):
        return False


class ModelManager:
    """
    Administra instancias de GenerativeModel con health-check y fallback automático.

    Uso:
        manager = ModelManager(system_instruction="Eres un analista...")
        response = manager.generate_content("¿Cuál es la tendencia de ventas?")
        embeddings = manager.embed_content(["texto a vectorizar"])
    """

    def __init__(
        self,
        model_names: Optional[List[str]] = None,
        system_instruction: str = "",
        api_key: Optional[str] = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ):
        if api_key:
            genai.configure(api_key=api_key)

        self._model_names: List[str] = model_names or list(DEFAULT_MODEL_NAMES)
        self._cooldown_seconds = cooldown_seconds
        self._embedding_model = embedding_model

        self._models: Dict[str, Any] = {
             name: genai.GenerativeModel(
                model_name=name,
                system_instruction=system_instruction,
            )
            for name in self._model_names
        }
        # Timestamp monotónico en el que el modelo vuelve a estar disponible (0 = listo)
        self._cooldown_until: Dict[str, float] = {name: 0.0 for name in self._model_names}

    # ── health helpers ─────────────────────────────────────────────────

    def is_healthy(self, model_name: str) -> bool:
        """True si el modelo no está en período de cooldown."""
        return time.monotonic() >= self._cooldown_until.get(model_name, 0.0)

    def _mark_unhealthy(self, model_name: str) -> None:
        ready_at = time.monotonic() + self._cooldown_seconds
        self._cooldown_until[model_name] = ready_at
        logger.warning("ModelManager: %s en cooldown %ds.", model_name, self._cooldown_seconds)
        print(f"DEBUG ModelManager: {model_name} en cooldown {self._cooldown_seconds}s.")

    def _wait_for_next_available(self) -> None:
        """Espera hasta que el modelo con cooldown más corto esté disponible."""
        now = time.monotonic()
        waits = [max(0.0, self._cooldown_until[n] - now) for n in self._model_names]
        wait = min(waits)
        if wait > 0:
            print(f"DEBUG ModelManager: todos en cooldown, esperando {wait:.1f}s...")
            time.sleep(wait)

    def health_status(self) -> Dict[str, bool]:
        """Devuelve {model_name: is_healthy} para diagnóstico."""
        return {name: self.is_healthy(name) for name in self._model_names}

    # ── generate_content con fallback ──────────────────────────────────

    def generate_content(self, content: Any, **kwargs) -> Any:
        """
        Llama a generate_content en orden de prioridad.
        - Omite modelos en cooldown.
        - Ante 429 pone el modelo en cooldown y prueba el siguiente.
        - Si todos están en cooldown, espera al más próximo y reintenta una vez.
        """
        last_error: Optional[Exception] = None

        for attempt in range(2):  # intento normal + 1 tras esperar cooldown
            for name in self._model_names:
                if not self.is_healthy(name):
                    logger.debug("ModelManager: %s en cooldown, omitiendo.", name)
                    continue
                try:
                    print(f"DEBUG ModelManager: llamando a {name}...")
                    return self._models[name].generate_content(content, **kwargs)
                except Exception as exc:
                    if _is_rate_limit_error(exc):
                        print(f"DEBUG ModelManager: 429 en {name}, probando siguiente...")
                        self._mark_unhealthy(name)
                        last_error = exc
                        continue
                    raise  # error distinto a rate limit → re-lanzar inmediatamente

            if attempt == 0:
                self._wait_for_next_available()

        if last_error is not None:
            raise last_error
        raise RuntimeError("ModelManager: no hay modelos disponibles.")

    # ── embed_content con reintentos ───────────────────────────────────

    def embed_content(self, content: Any, model: Optional[str] = None, **kwargs) -> Any:
        """
        Wrapper de genai.embed_content con reintentos ante 429.
        content puede ser str o List[str].
        """
        target_model = model or self._embedding_model
        backoff = 10

        for attempt in range(3):
            try:
                return genai.embed_content(model=target_model, content=content, **kwargs)
            except Exception as exc:
                if _is_rate_limit_error(exc) and attempt < 2:
                    print(f"DEBUG ModelManager: 429 en embed_content, esperando {backoff}s...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise
