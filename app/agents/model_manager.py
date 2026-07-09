"""
ModelManager: gestión centralizada de modelos con soporte híbrido Gemini + Ollama.

- Soporte para modelo local Ollama (soberanía de datos extrema).
- Enrutamiento inteligente: local prioritario para estructuración/Pandas/scripts locales.
- Fallback a Gemini para razonamiento conceptual complejo o tokens grandes.
- Aislamiento total: cuando se usa Ollama, cero llamadas a APIs de terceros.
"""
import time
import logging
import os
from typing import Any, Dict, List, Optional

import google.generativeai as genai
import requests

logger = logging.getLogger(__name__)

# Modelos recomendados para cuentas nuevas (Jul 2026). Ver:
# https://ai.google.dev/gemini-api/docs/models
DEFAULT_MODEL_NAMES: List[str] = [
    "models/gemini-3-flash-preview",  # compatible con google.generativeai; suele responder rápido
    "models/gemini-3.5-flash",
    "models/gemini-3.1-flash-lite",
]

DEFAULT_EMBEDDING_MODEL: str = "models/gemini-embedding-001"
DEFAULT_COOLDOWN_SECONDS: int = 60
FRIENDLY_PROCESSING_MSG = "Estoy procesando tu solicitud, dame un segundo..."

# ── Ollama configuration ─────────────────────────────────────────────
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "llama3.1"
OLLAMA_TIMEOUT = 300  # 5 minutos por defecto (antes 180 s)


def get_default_gemini_model_names() -> List[str]:
    """Lista de modelos Gemini desde GEMINI_MODELS (coma) o defaults actuales."""
    raw = os.getenv("GEMINI_MODELS", "").strip()
    if raw:
        names: List[str] = []
        for part in raw.split(","):
            p = part.strip()
            if not p:
                continue
            names.append(p if p.startswith("models/") else f"models/{p}")
        if names:
            return names
    return list(DEFAULT_MODEL_NAMES)


def get_primary_gemini_model() -> str:
    """Modelo principal para agentes que usan un solo GenerativeModel."""
    single = os.getenv("GEMINI_MODEL", "").strip()
    if single:
        return single if single.startswith("models/") else f"models/{single}"
    return get_default_gemini_model_names()[0]


LOCAL_PRIORITY_KEYWORDS = (
    "pandas",
    "dataframe",
    "estructurar",
    "formatear",
    "script local",
    "limpiar datos",
    "preprocesar",
    "soberanía",
    "local",
    "csv",
    "excel",
    "cargar_dataframe_limpio",
)


def _is_model_unavailable_error(exc: Exception) -> bool:
    """True si el modelo no existe o ya no está disponible para la cuenta (404)."""
    msg = str(exc).lower()
    if any(
        token in msg
        for token in (
            "404",
            "not found",
            "no longer available",
            "is not supported",
            "does not exist",
        )
    ):
        return True
    code = getattr(exc, "code", None)
    try:
        return code is not None and int(code) == 404
    except (TypeError, ValueError):
        return False


def _is_timeout_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    if any(t in msg for t in ("timeout", "timed out", "deadline exceeded", "504")):
        return True
    return False


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


def _is_gemini_auth_error(exc: Exception) -> bool:
    """True si la API key de Gemini es inválida, revocada o reportada como filtrada."""
    msg = str(exc).lower()
    if any(
        token in msg
        for token in (
            "403",
            "leaked",
            "api key",
            "api_key",
            "invalid",
            "permission denied",
            "not authorized",
        )
    ):
        return True
    code = getattr(exc, "code", None)
    try:
        return code is not None and int(code) == 403
    except (TypeError, ValueError):
        return False


class ModelManager:
    """
    Administra modelos Gemini y Ollama con enrutamiento híbrido inteligente.

    Uso:
        manager = ModelManager(system_instruction="Eres un analista...")
        response = manager.generate_content("analiza este CSV", sovereignty_mode=True)
        embeddings = manager.embed_content(["texto a vectorizar"])
    """

    def __init__(
        self,
        model_names: Optional[List[str]] = None,
        system_instruction: str = "",
        api_key: Optional[str] = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
        # Ollama params
        ollama_model: Optional[str] = None,
        ollama_base_url: Optional[str] = None,
    ):
        if api_key:
            genai.configure(api_key=api_key)

        self._model_names: List[str] = model_names or get_default_gemini_model_names()
        self._cooldown_seconds = cooldown_seconds
        self._embedding_model = embedding_model

        # Gemini models
        self._models: Dict[str, Any] = {
            name: genai.GenerativeModel(
                model_name=name,
                system_instruction=system_instruction,
            )
            for name in self._model_names
        }
        self._cooldown_until: Dict[str, float] = {name: 0.0 for name in self._model_names}
        self._unavailable: set[str] = set()

        # Ollama (configurable por .env para soportar host local o nube sin cambiar código)
        env_ollama_model = os.getenv("OLLAMA_MODEL", "").strip()
        env_ollama_base = os.getenv("OLLAMA_BASE_URL", "").strip()
        env_ollama_timeout = os.getenv("OLLAMA_TIMEOUT_SEC", "").strip()
        gemini_timeout_raw = os.getenv("GEMINI_REQUEST_TIMEOUT_SEC", "90").strip()

        self._ollama_model = (ollama_model or env_ollama_model or OLLAMA_DEFAULT_MODEL).strip()
        self._ollama_base_url = (ollama_base_url or env_ollama_base or OLLAMA_DEFAULT_BASE_URL).strip().rstrip("/")
        self._ollama_timeout = OLLAMA_TIMEOUT
        if env_ollama_timeout.isdigit():
            self._ollama_timeout = max(5, int(env_ollama_timeout))
        self._gemini_timeout = 90
        if gemini_timeout_raw.isdigit():
            self._gemini_timeout = max(15, int(gemini_timeout_raw))
        self._system_instruction = system_instruction

    def _gemini_request_options(self) -> dict[str, int]:
        return {"timeout": self._gemini_timeout}

    def _call_gemini(self, name: str, content: Any, **kwargs: Any) -> Any:
        opts = kwargs.pop("request_options", None) or self._gemini_request_options()
        return self._models[name].generate_content(content, request_options=opts, **kwargs)

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

    # ── Routing logic ─────────────────────────────────────────────────

    def _all_gemini_unhealthy(self) -> bool:
        """True si todos los modelos Gemini están en cooldown o no disponibles."""
        active = [n for n in self._model_names if n not in self._unavailable]
        if not active:
            return True
        return all(not self.is_healthy(name) for name in active)

    def _should_route_to_local(
        self,
        content: Any,
        force_local: bool = False,
        sovereignty_mode: bool = False,
    ) -> bool:
        """
        Política de enrutamiento actualizada (Mayo 2026):

        - Gemini es el modelo prioritario.
        - Solo se usa Ollama cuando:
            a) el usuario fuerza `force_local=True` o `sovereignty_mode=True`, o
            b) todos los modelos Gemini alcanzaron su límite de tasa (429)
               y están en cooldown.
        """
        if force_local or sovereignty_mode:
            return True

        # Si todavía hay al menos un modelo Gemini disponible → usarlo primero
        if not self._all_gemini_unhealthy():
            return False

        # Todos los Gemini están en cooldown → fallback a Ollama
        return True

    def _friendly_response(self) -> Any:
        """Respuesta amable cuando Ollama falla y Gemini no está disponible."""

        class _FriendlyResponse:
            text = FRIENDLY_PROCESSING_MSG

        return _FriendlyResponse()

    def _is_ollama_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return "ollama" in msg or isinstance(exc, requests.RequestException)

    def _try_gemini_force(self, content: Any, **kwargs) -> Optional[Any]:
        """Intenta Gemini aunque esté en cooldown (p. ej. tras fallo de Ollama)."""
        for name in self._model_names:
            if name in self._unavailable:
                continue
            try:
                logger.info("ModelManager: reintento Gemini en %s tras fallo Ollama.", name)
                return self._call_gemini(name, content, **kwargs)
            except Exception as exc:
                if _is_model_unavailable_error(exc):
                    self._unavailable.add(name)
                    continue
                if _is_timeout_error(exc):
                    logger.warning("ModelManager: timeout en %s (%ss), probando siguiente", name, self._gemini_timeout)
                    continue
                if _is_rate_limit_error(exc):
                    continue
                logger.warning("ModelManager: Gemini %s falló en reintento: %s", name, exc)
                continue
        return None

    def _generate_ollama_or_none(self, content: Any, **kwargs) -> Optional[Any]:
        """Llama a Ollama; devuelve None si hay error de conexión (sin propagar al chat)."""
        try:
            return self._generate_ollama(content, **kwargs)
        except RuntimeError as exc:
            if self._is_ollama_error(exc):
                logger.warning("Ollama no disponible (%s): %s", self._ollama_base_url, exc)
                return None
            raise
        except requests.RequestException as exc:
            logger.warning("Ollama connection error (%s): %s", self._ollama_base_url, exc)
            return None

    # ── Ollama call (aislamiento total) ───────────────────────────────

    def _generate_ollama(self, content: Any, **kwargs) -> Any:
        """
        Llama a Ollama manteniendo aislamiento total (sin llamadas a Gemini).
        """
        prompt = str(content)
        if self._system_instruction:
            prompt = f"{self._system_instruction}\n\n{prompt}"

        url = f"{self._ollama_base_url}/api/generate"
        payload = {
            "model": self._ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.2),
                "num_predict": kwargs.get("max_tokens", 2048),
            },
        }

        try:
            resp = requests.post(url, json=payload, timeout=self._ollama_timeout)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "").strip()

            class OllamaResponse:
                def __init__(self, text: str):
                    self.text = text

            return OllamaResponse(text)
        except requests.RequestException as e:
            logger.warning("Ollama connection error (%s): %s", self._ollama_base_url, e)
            raise RuntimeError(f"Ollama connection error ({self._ollama_base_url}): {e}") from e
        except Exception as e:
            raise RuntimeError(f"Ollama generation error: {e}") from e

    def _ollama_fallback_or_friendly(self, content: Any, **kwargs) -> Any:
        """Tras fallo Ollama: Gemini forzado o mensaje amable (nunca error técnico al usuario)."""
        forced = self._try_gemini_force(content, **kwargs)
        if forced is not None:
            return forced
        return self._friendly_response()

    # ── generate_content con enrutamiento híbrido ─────────────────────

    def generate_content(self, content: Any, **kwargs) -> Any:
        """
        Política de enrutamiento (Mayo 2026):

        1. Gemini es el proveedor principal.
        2. Solo se cae a Ollama cuando:
           - el usuario fuerza `force_local` / `sovereignty_mode`, o
           - todos los modelos Gemini han alcanzado su límite de tasa (429)
             y están en cooldown.
        """
        force_local = kwargs.pop("force_local", False)
        sovereignty_mode = kwargs.pop("sovereignty_mode", False)

        # ── Caso 1: usuario obliga a usar Ollama ─────────────────────
        if self._should_route_to_local(content, force_local, sovereignty_mode):
            print(f"DEBUG ModelManager: enrutando a Ollama ({self._ollama_model})")
            ollama_result = self._generate_ollama_or_none(content, **kwargs)
            if ollama_result is not None:
                return ollama_result
            return self._ollama_fallback_or_friendly(content, **kwargs)

        # ── Caso 2: Gemini primero ───────────────────────────────────
        last_error: Optional[Exception] = None

        for attempt in range(2):
            for name in self._model_names:
                if name in self._unavailable:
                    continue
                if not self.is_healthy(name):
                    continue
                try:
                    print(f"DEBUG ModelManager: llamando a {name} (cloud)...")
                    return self._call_gemini(name, content, **kwargs)
                except Exception as exc:
                    if _is_model_unavailable_error(exc):
                        logger.warning("ModelManager: %s no disponible, probando siguiente: %s", name, exc)
                        print(f"DEBUG ModelManager: {name} no disponible (404), saltando...")
                        self._unavailable.add(name)
                        last_error = exc
                        continue
                    if _is_timeout_error(exc):
                        logger.warning("ModelManager: timeout en %s, probando siguiente", name)
                        print(f"DEBUG ModelManager: timeout en {name}, saltando...")
                        last_error = exc
                        continue
                    if _is_rate_limit_error(exc):
                        print(f"DEBUG ModelManager: 429 en {name}, marcando cooldown...")
                        self._mark_unhealthy(name)
                        last_error = exc
                        continue
                    if _is_gemini_auth_error(exc):
                        logger.error(
                            "ModelManager: Gemini rechazó la API key (%s). "
                            "Rota GEMINI_API_KEY en .env y reinicia brain.",
                            exc,
                        )
                        for n in self._model_names:
                            self._mark_unhealthy(n)
                        ollama_result = self._generate_ollama_or_none(content, **kwargs)
                        if ollama_result is not None:
                            return ollama_result
                        return self._friendly_response()
                    raise

            if attempt == 0:
                self._wait_for_next_available()

        # ── Caso 3: todos los Gemini están en cooldown → fallback Ollama ─
        if self._all_gemini_unhealthy():
            print(f"DEBUG ModelManager: todos los modelos Gemini en cooldown → fallback Ollama ({self._ollama_model})")
            ollama_result = self._generate_ollama_or_none(content, **kwargs)
            if ollama_result is not None:
                return ollama_result
            return self._friendly_response()

        if last_error is not None:
            raise last_error
        raise RuntimeError("ModelManager: no hay modelos disponibles.")

    # ── embed_content (siempre Gemini por ahora) ──────────────────────

    def embed_content(self, content: Any, model: Optional[str] = None, **kwargs) -> Any:
        """
        Embeddings permanecen en Gemini (Ollama embeddings se pueden añadir después).
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
                if _is_gemini_auth_error(exc):
                    logger.error("embed_content: API key Gemini inválida o filtrada: %s", exc)
                    raise RuntimeError(
                        "GEMINI_API_KEY inválida o reportada como filtrada. "
                        "Genera una nueva en Google AI Studio y actualiza .env."
                    ) from exc
                raise
